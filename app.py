"""Local commerce-video library. No remote data is invented or seeded."""
import csv
import datetime as dt
import io
import json
import os
import re
import secrets
import shutil
import sqlite3
import subprocess
import sys
import threading
import tempfile
import uuid
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse
from collector import Collector, browser_ready, COOKIES, SEEDS

ROOT = Path(__file__).resolve().parent
DB_PATH = Path(os.environ.get('VIDEO_DB', str(ROOT / 'data/library.sqlite3')))
DOWNLOADS = Path(os.environ.get('VIDEO_DOWNLOADS', str(ROOT / 'downloads')))
PORT = int(os.environ.get('PORT', '8765'))
TOKEN = secrets.token_urlsafe(32)
POOL = ThreadPoolExecutor(max_workers=2)
CATEGORIES = {
    '美妆个护': ['护肤', '彩妆', '美发护发', '香水香氛', '个人护理'],
    '女装与女士内衣': ['女装', '女士内衣', '家居服'],
    '运动与户外': ['健身器材', '运动服饰', '户外用品'],
    '保健': ['营养补充', '健康护理'],
    '手机与数码': ['手机配件', '影音设备', '数码配件'],
    '家居用品': ['清洁用品', '收纳用品', '床上用品', '家居装饰'],
    '厨房用品': ['厨具', '餐具', '厨房小工具'],
    '食品与饮料': ['零食', '饮料', '粮油调味'],
    '母婴用品': ['婴童护理', '喂养用品', '童装'],
    '宠物用品': ['宠物食品', '宠物护理', '宠物玩具'],
    '男装与男士内衣': ['男装', '男士内衣'],
    '鞋靴': ['女鞋', '男鞋', '运动鞋'],
    '箱包配饰': ['箱包', '珠宝饰品', '时尚配饰'],
    '家电': ['生活电器', '厨房电器'],
    '汽车与摩托车': ['汽车用品', '汽车配件'],
    '玩具与爱好': ['玩具', '手工与爱好'],
    '其他': []
}


class Connection(sqlite3.Connection):
    def __exit__(self, *args):
        try:
            return super().__exit__(*args)
        finally:
            self.close()


def connect():
    conn = sqlite3.connect(str(DB_PATH), timeout=15, factory=Connection)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    DOWNLOADS.mkdir(parents=True, exist_ok=True)
    with connect() as conn:
        conn.executescript('''
        PRAGMA journal_mode=WAL;
        CREATE TABLE IF NOT EXISTS videos (
          video_id TEXT PRIMARY KEY, payload TEXT NOT NULL, saved_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS tasks (
          id TEXT PRIMARY KEY, video_id TEXT, status TEXT, error TEXT,
          filename TEXT, created_at TEXT
        );
        ''')
        conn.execute("UPDATE tasks SET status='failed', error='服务重启，任务已中断，请重新下载' WHERE status IN ('queued','running')")


def number(value, integer=False):
    if value is None or str(value).strip() in ('', '-', 'null', 'None'):
        return None
    s = str(value).strip().replace(',', '').replace('$', '').replace('%', '')
    factor = 1
    for suffix, scale in [('万', 10000), ('亿', 100000000), ('K', 1000), ('M', 1000000)]:
        if s.upper().endswith(suffix):
            s, factor = s[:-len(suffix)], scale
            break
    n = float(s) * factor
    if not (0 <= n < 1e18):
        raise ValueError('指标必须是有效的非负数字')
    return int(n) if integer else n


def web_url(value):
    value = str(value or '').strip()
    if not value:
        return ''
    parsed = urlparse(value)
    if parsed.scheme not in ('http', 'https') or not parsed.hostname or parsed.username:
        raise ValueError('链接必须为 http 或 https 地址')
    return value


def normalize(row):
    if not isinstance(row, dict):
        raise ValueError('每条数据必须为对象')
    if isinstance(row.get('video_id'), (float, int)) and abs(row['video_id']) > 2**53:
        raise ValueError('长视频 ID 请用字符串传入，避免精度损失')
    url = web_url(row.get('video_url'))
    vid = str(row.get('video_id') or '').strip()
    if not vid:
        match = re.search(r'/video/(\d+)', url)
        vid = match.group(1) if match else ''
    if not re.fullmatch(r'[0-9]{1,30}', vid):
        raise ValueError('缺少有效 video_id 或 TikTok 视频链接')
    source = str(row.get('source') or '').strip()
    if not source:
        raise ValueError('请提供 source 数据来源，例如手动整理或平台导出')
    category = str(row.get('category') or '未分类').strip()
    subcategory = str(row.get('subcategory') or '').strip()
    products = row.get('products', [])
    if isinstance(products, str):
        products = json.loads(products) if products.strip() else []
    if not products and (row.get('product_name') or row.get('product_id')):
        products = [{k: row.get('product_' + k) for k in ('id', 'name', 'url', 'image', 'price', 'currency', 'shop')}]
    if not isinstance(products, list) or any(not isinstance(p, dict) for p in products):
        raise ValueError('products 必须为商品对象数组')
    normalized_products = []
    for p in products:
        if isinstance(p.get('id'), (float, int)) and abs(p['id']) > 2**53:
            raise ValueError('长商品 ID 请用字符串传入，避免精度损失')
        normalized_products.append({
            'id': str(p.get('id') or ''), 'name': str(p.get('name') or ''),
            'url': web_url(p.get('url')), 'image': web_url(p.get('image')),
            'price': number(p.get('price')), 'currency': str(p.get('currency') or 'USD'),
            'shop': str(p.get('shop') or ''), 'source': str(p.get('source') or source),
            'evidence': str(p.get('evidence') or row.get('product_evidence') or '来源提供，尚未独立核验')
        })
    commerce = row.get('is_commerce')
    if isinstance(commerce, str):
        commerce = {'true': True, '1': True, '是': True, 'false': False, '0': False, '否': False}.get(commerce.lower())
    if commerce is not None and not isinstance(commerce, bool):
        raise ValueError('is_commerce 必须是 true、false 或空值')
    published = str(row.get('published_at') or '').strip()
    if published:
        try:
            stamp = dt.datetime.fromisoformat(published.replace('Z', '+00:00'))
        except ValueError:
            raise ValueError('published_at 请使用 ISO 日期，例如 2026-11-12T20:56:10-08:00')
        if stamp.tzinfo is None:
            raise ValueError('published_at 需要包含时区，例如 -08:00 或 Z')
        published = stamp.astimezone(dt.timezone.utc).isoformat()
    result = {k: str(row.get(k) or '') for k in ('title', 'author', 'metrics_period', 'commerce_evidence',
              'target_market', 'market_evidence', 'category_evidence', 'search_query')}
    sources = row.get('field_sources', {})
    if isinstance(sources,str):
        sources=json.loads(sources) if sources.strip() else {}
    result['field_sources'] = sources if isinstance(sources,dict) else {}
    result.update(video_id=vid, video_url=url, cover_url=web_url(row.get('cover_url')),
                  country=str(row.get('country') or 'US').upper(), category=category,
                  subcategory=subcategory, source=source, products=normalized_products,
                  is_commerce=commerce, published_at=published,
                  collected_at=dt.datetime.now(dt.timezone.utc).isoformat())
    for k in ('views', 'likes', 'comments', 'shares', 'estimated_sales', 'duration'):
        result[k] = number(row.get(k), True)
    for k in ('estimated_revenue', 'engagement_rate', 'ad_view_ratio'):
        result[k] = number(row.get(k))
    result['currency'] = str(row.get('currency') or 'USD')
    return result


def import_rows(rows):
    if not isinstance(rows, list) or len(rows) > 5000:
        raise ValueError('请传入数组，每次最多 5000 条')
    prepared = []
    for i, row in enumerate(rows, 1):
        try:
            prepared.append(normalize(row))
        except (ValueError, TypeError) as exc:
            raise ValueError('第 %d 行：%s；本次未导入任何数据' % (i, exc))
    with connect() as conn:
        for row in prepared:
            conn.execute('INSERT INTO videos VALUES (?,?,?) ON CONFLICT(video_id) DO UPDATE SET payload=excluded.payload,saved_at=excluded.saved_at',
                         (row['video_id'], json.dumps(row, ensure_ascii=False), row['collected_at']))
    return {'imported': len(prepared), 'message': '已按视频 ID 保存；相同 ID 更新为本次完整记录'}


def save_collected(rows):
    prepared=[]
    for row in rows:
        try:
            current=get_video(row['video_id'])
        except ValueError:
            current={}
        merged=dict(current)
        sources=dict(current.get('field_sources',{}))
        for key,value in row.items():
            if key in ('category','category_evidence') and row.get('category')=='未分类' and current.get('category') not in (None,'未分类'):
                continue
            if key in ('country','market_evidence') and row.get('country')=='UNKNOWN' and current.get('country') not in (None,'UNKNOWN'):
                continue
            if value is not None and value not in ('',[]) and (key!='category' or value!='未分类' or not current.get('category')):
                merged[key]=value
                if key not in ('field_sources','source'):sources[key]=row['source']
        for key,value in current.items():
            if key not in sources and value is not None and value not in ('',[]):sources[key]=current['source']
        merged['field_sources']=sources
        prepared.append(merged)
    return import_rows(prepared)


COLLECTOR = Collector(save_collected)


def filtered(params):
    def value(k, default=''):
        return params.get(k, [default])[0]
    with connect() as conn:
        rows = [json.loads(r['payload']) for r in conn.execute('SELECT payload FROM videos')]
    total = len(rows)
    categories = sorted({r['category'] for r in rows} | set(CATEGORIES))
    subcategories = {}
    for row in rows:
        if row['subcategory']:
            subcategories.setdefault(row['category'], set()).add(row['subcategory'])
    for key in ('country', 'category', 'subcategory'):
        if value(key):
            rows = [r for r in rows if r.get(key) == value(key) or
                    (key=='country' and r.get('country')=='UNKNOWN' and r.get('target_market')==value(key))]
    if value('commerce') == 'true':
        rows = [r for r in rows if r.get('is_commerce') is True]
    if value('products') == 'true':
        rows = [r for r in rows if r.get('products')]
    if value('q'):
        q = value('q').casefold()
        rows = [r for r in rows if q in ' '.join([r['title'], r['author']] + [p['name'] for p in r['products']]).casefold()]
    for param, key in [('min_views', 'views'), ('min_sales', 'estimated_sales'), ('min_revenue', 'estimated_revenue')]:
        if value(param):
            minimum = number(value(param))
            rows = [r for r in rows if r.get(key) is not None and r[key] >= minimum]
    for param, inclusive in [('from', True), ('to', False)]:
        if value(param):
            date = dt.date.fromisoformat(value(param))
            # Browser passes UTC boundaries derived from the user's local calendar.
            boundary = value(param + '_utc')
            if boundary:
                threshold = dt.datetime.fromisoformat(boundary.replace('Z', '+00:00')).astimezone(dt.timezone.utc).isoformat()
            else:
                if not inclusive:
                    date += dt.timedelta(days=1)
                threshold = dt.datetime.combine(date, dt.time(), tzinfo=dt.timezone.utc).isoformat()
            rows = [r for r in rows if r['published_at'] and (r['published_at'] >= threshold if inclusive else r['published_at'] < threshold)]
    key = value('sort', 'published_at')
    if key not in ('published_at', 'views', 'estimated_sales', 'estimated_revenue', 'engagement_rate'):
        key = 'published_at'
    if (value('min_revenue') or key == 'estimated_revenue') and len({r['currency'] for r in rows if r.get('estimated_revenue') is not None}) > 1:
        raise ValueError('销售额包含多种币种，请先选择单一市场再筛选或排序')
    missing = [r for r in rows if r.get(key) is None or r.get(key) == '']
    rows = sorted([r for r in rows if r.get(key) is not None and r.get(key) != ''], key=lambda r: r[key], reverse=value('order', 'desc') != 'asc') + missing
    return {'items': rows, 'filtered': len(rows), 'total': total, 'categories': categories,
            'subcategories': {k:sorted(v) for k,v in subcategories.items()}}


def get_video(vid):
    with connect() as conn:
        r = conn.execute('SELECT payload FROM videos WHERE video_id=?', (vid,)).fetchone()
    if not r:
        raise ValueError('视频不存在')
    return json.loads(r['payload'])


def task_update(task_id, **fields):
    with connect() as conn:
        conn.execute('UPDATE tasks SET ' + ','.join(k+'=?' for k in fields) + ' WHERE id=?', (*fields.values(), task_id))


def download_worker(task_id, row):
    task_update(task_id, status='running')
    folder = DOWNLOADS / task_id
    folder.mkdir(exist_ok=True)
    cookie_file=None
    try:
        cookie_args=[]
        if COOKIES.is_file():
            with tempfile.NamedTemporaryFile(prefix='download-cookies-',dir=str(DB_PATH.parent),delete=False) as fp:
                fp.write(COOKIES.read_bytes())
                cookie_file=Path(fp.name)
            cookie_args=['--cookies',str(cookie_file)]
        proc = subprocess.run([sys.executable, '-m', 'yt_dlp', *cookie_args, '--ignore-config', '--no-playlist',
            '--socket-timeout', '25', '--retries', '1', '--max-filesize', '500M',
            '-f', 'best[vcodec!=none]/bestvideo', '-o', str(folder / 'video.%(ext)s'), '--', row['video_url']],
            capture_output=True, text=True, timeout=240)
        files = [p for p in folder.glob('video.*') if p.suffix not in ('.part', '.ytdl', '.json') and p.stat().st_size]
        if proc.returncode or not files:
            message = proc.stderr.strip().splitlines()
            raise ValueError((message[-1] if message else '未获取到视频文件')[:600])
        media = max(files, key=lambda p: p.stat().st_size)
        if media.suffix.lower() in ('.m4a', '.mp3', '.aac', '.ogg', '.wav'):
            raise ValueError('来源仅返回音频，未获取到视频画面')
        (folder / 'metadata.json').write_text(json.dumps(row, ensure_ascii=False, indent=2), encoding='utf-8')
        task_update(task_id, status='done', filename=str(media.relative_to(DOWNLOADS)), error='')
    except subprocess.TimeoutExpired:
        task_update(task_id, status='failed', error='下载超时，请稍后重试')
    except Exception as exc:
        task_update(task_id, status='failed', error=str(exc)[:600])
    finally:
        if cookie_file is not None:cookie_file.unlink(missing_ok=True)


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def send(self, data, status=200, kind='application/json; charset=utf-8', headers=None):
        if not isinstance(data, bytes):
            data = json.dumps(data, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header('Content-Type', kind)
        self.send_header('Content-Length', str(len(data)))
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Cache-Control', 'no-store')
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(data)

    def valid_host(self):
        return self.headers.get('Host') in ('127.0.0.1:%d' % PORT, 'localhost:%d' % PORT)

    def do_GET(self):
        if not self.valid_host():
            return self.send({'error': '无效主机'}, 403)
        path = urlparse(self.path).path
        params = parse_qs(urlparse(self.path).query, keep_blank_values=True)
        try:
            if path == '/api/config':
                import importlib.util
                return self.send({'token': TOKEN, 'categories': CATEGORIES, 'downloader_ready': importlib.util.find_spec('yt_dlp') is not None,
                                  'live_search_ready': browser_ready(), 'category_seeds':SEEDS,
                                  'message': '免费浏览器采集：类目由文案推断，销售市场未核验；部分搜索需要手动登录'})
            if path == '/api/collector':
                return self.send(COLLECTOR.status())
            if path == '/api/videos':
                result = filtered(params)
                page = max(1, int(params.get('page', ['1'])[0]))
                result['items'] = result['items'][(page-1)*30:page*30]
                result['page'] = page
                return self.send(result)
            if path == '/api/tasks':
                with connect() as conn:
                    return self.send({'items': [dict(r) for r in conn.execute('SELECT * FROM tasks ORDER BY created_at DESC LIMIT 100')]})
            if path == '/api/export':
                rows = filtered(params)['items']
                ids = params.get('ids', [''])[0]
                if ids:
                    selected = set(ids.split(','))
                    rows = [r for r in rows if r['video_id'] in selected]
                if params.get('format', ['json'])[0] == 'csv':
                    stream = io.StringIO()
                    fields = ['video_id','title','author','video_url','country','target_market','market_evidence','category','subcategory','category_evidence','published_at','views','likes','comments','shares','estimated_sales','estimated_revenue','currency','engagement_rate','ad_view_ratio','metrics_period','is_commerce','commerce_evidence','source','search_query','collected_at','products','field_sources']
                    writer = csv.DictWriter(stream, fieldnames=fields, extrasaction='ignore')
                    writer.writeheader()
                    for row in rows:
                        row = dict(row, products=json.dumps(row['products'], ensure_ascii=False),field_sources=json.dumps(row.get('field_sources',{}),ensure_ascii=False))
                        row = {k: ("'"+v if isinstance(v,str) and v.startswith(('=','+','-','@','\t','\r','\n')) else v) for k,v in row.items()}
                        writer.writerow(row)
                    return self.send(('\ufeff'+stream.getvalue()).encode(), kind='text/csv; charset=utf-8', headers={'Content-Disposition': 'attachment; filename="videos.csv"'})
                return self.send(json.dumps(rows, ensure_ascii=False, indent=2).encode(), headers={'Content-Disposition': 'attachment; filename="videos.json"'})
            if path.startswith('/api/file/'):
                task_id = path.rsplit('/', 1)[-1]
                with connect() as conn:
                    task = conn.execute("SELECT * FROM tasks WHERE id=? AND status='done'", (task_id,)).fetchone()
                if not task:
                    return self.send({'error': '文件尚未就绪'}, 404)
                media = (DOWNLOADS / task['filename']).resolve()
                if DOWNLOADS.resolve() not in media.parents or not media.is_file():
                    return self.send({'error': '文件不存在'}, 404)
                import mimetypes
                self.send_response(200)
                self.send_header('Content-Type', mimetypes.guess_type(str(media))[0] or 'application/octet-stream')
                self.send_header('Content-Disposition', 'attachment; filename="%s%s"' % (task['video_id'], media.suffix))
                self.send_header('Content-Length', str(media.stat().st_size))
                self.end_headers()
                with media.open('rb') as fp:
                    shutil.copyfileobj(fp, self.wfile)
                return
            assets = {'/': 'index.html', '/app.js': 'app.js', '/style.css': 'style.css'}
            if path in assets:
                kind = {'/':'text/html; charset=utf-8', '/app.js':'text/javascript; charset=utf-8', '/style.css':'text/css; charset=utf-8'}[path]
                return self.send((ROOT / 'static' / assets[path]).read_bytes(), kind=kind)
            return self.send({'error':'未找到'}, 404)
        except (ValueError, TypeError) as exc:
            self.send({'error': str(exc)}, 400)

    def do_POST(self):
        if not self.valid_host() or self.headers.get('X-Local-Token') != TOKEN:
            return self.send({'error':'请刷新本地页面重试'}, 403)
        try:
            size = int(self.headers.get('Content-Length', '0'))
            if not 0 < size <= 10*1024*1024:
                raise ValueError('请求为空或超过 10MB')
            data = json.loads(self.rfile.read(size))
            path = urlparse(self.path).path
            if path == '/api/import':
                return self.send(import_rows(data.get('rows')))
            if path == '/api/collect':
                return self.send(COLLECTOR.start(data))
            if path == '/api/collector/action':
                return self.send(COLLECTOR.signal(data.get('action')))
            if path == '/api/download':
                import importlib.util
                if importlib.util.find_spec('yt_dlp') is None:
                    raise ValueError('尚未安装下载组件，请按本地使用说明安装 yt-dlp')
                ids = data.get('ids')
                if not isinstance(ids, list) or not 0 < len(ids) <= 50:
                    raise ValueError('每次请选择 1～50 条视频')
                rows = [get_video(str(vid)) for vid in dict.fromkeys(ids)]
                for row in rows:
                    host = (urlparse(row['video_url']).hostname or '').lower()
                    if not (host == 'tiktok.com' or host.endswith('.tiktok.com')):
                        raise ValueError('下载仅接受 TikTok 视频页面链接')
                task_ids = []
                for row in rows:
                    with connect() as conn:
                        existing = conn.execute("SELECT id FROM tasks WHERE video_id=? AND status IN ('queued','running')", (row['video_id'],)).fetchone()
                        if existing:
                            task_ids.append(existing['id'])
                            continue
                        task_id = uuid.uuid4().hex
                        conn.execute('INSERT INTO tasks VALUES (?,?,?,?,?,?)', (task_id, row['video_id'], 'queued', '', '', dt.datetime.now(dt.timezone.utc).isoformat()))
                    task_ids.append(task_id)
                    POOL.submit(download_worker, task_id, row)
                return self.send({'task_ids': task_ids})
            self.send({'error':'未找到接口'}, 404)
        except (ValueError, TypeError, KeyError) as exc:
            self.send({'error':str(exc)}, 400)


if __name__ == '__main__':
    init_db()
    print('Local: http://127.0.0.1:%d' % PORT, flush=True)
    ThreadingHTTPServer(('127.0.0.1', PORT), Handler).serve_forever()

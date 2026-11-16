"""Free, ordinary-browser collection. No paid endpoints or fabricated metrics."""
import datetime as dt
import importlib.util
import json
import os
import re
import threading
import time
import uuid
from pathlib import Path
from urllib.parse import quote, urlparse

ROOT = Path(__file__).resolve().parent
PROFILE = ROOT / 'data/tiktok-browser'
COOKIES = ROOT / 'data/tiktok-cookies.txt'
SEEDS = {
    '美妆个护': 'skincare makeup', '女装与女士内衣': 'women clothing shapewear',
    '运动与户外': 'fitness outdoor', '保健': 'supplements wellness',
    '手机与数码': 'phone accessories', '家居用品': 'home cleaning',
    '厨房用品': 'kitchen gadgets', '食品与饮料': 'snacks drinks',
    '母婴用品': 'baby products', '宠物用品': 'pet supplies',
    '男装与男士内衣': 'mens clothing', '鞋靴': 'shoes sneakers',
    '箱包配饰': 'bags jewelry', '家电': 'home appliances',
    '汽车与摩托车': 'car accessories', '玩具与爱好': 'toys crafts', '其他': 'viral products'
}
SUBSEEDS = {
    '护肤':'skincare', '彩妆':'makeup', '美发护发':'hair care', '香水香氛':'perfume',
    '个人护理':'personal care', '清洁用品':'cleaning products', '收纳用品':'home organization',
    '床上用品':'bedding', '家居装饰':'home decor', '厨具':'cookware', '餐具':'tableware',
    '厨房小工具':'kitchen gadgets', '女装':'women clothing', '女士内衣':'shapewear',
    '家居服':'loungewear', '健身器材':'fitness equipment', '运动服饰':'sportswear',
    '户外用品':'outdoor gear', '营养补充':'supplements', '健康护理':'wellness',
    '手机配件':'phone accessories', '影音设备':'audio video', '数码配件':'tech accessories',
    '零食':'snacks', '饮料':'drinks', '粮油调味':'cooking seasoning',
    '婴童护理':'baby care', '喂养用品':'baby feeding', '童装':'kids clothing',
    '宠物食品':'pet food', '宠物护理':'pet grooming', '宠物玩具':'pet toys',
    '男装':'mens clothing', '男士内衣':'mens underwear', '女鞋':'women shoes',
    '男鞋':'men shoes', '运动鞋':'sneakers', '箱包':'bags', '珠宝饰品':'jewelry',
    '时尚配饰':'fashion accessories', '生活电器':'home appliances', '厨房电器':'kitchen appliances',
    '汽车用品':'car accessories', '汽车配件':'car parts', '玩具':'toys', '手工与爱好':'crafts'
}
CATEGORY_RULES = {
    '美妆个护': r'skincare|skin care|makeup|mascara|lipstick|serum|moisturiz|beauty|perfume|hair care|护肤|彩妆|美妆',
    '女装与女士内衣': r'shapewear|women.?s? clothing|legging|dress|bra\b|女装|内衣',
    '运动与户外': r'fitness|workout|camping|outdoor|gym\b|运动|健身|露营',
    '保健': r'supplement|vitamin|magnesium|probiotic|collagen|保健|维生素',
    '手机与数码': r'phone case|phone stand|charger|earbud|headphone|数码|手机',
    '家居用品': r'cleaning|organizer|organisation|organization|bedding|pillow|home decor|收纳|清洁|枕头',
    '厨房用品': r'kitchen|cookware|tableware|vegetable cutter|厨房|厨具',
    '食品与饮料': r'snacks|coffee|chocolate|drink|食品|零食|饮料',
    '母婴用品': r'baby|toddler|母婴|婴儿', '宠物用品': r'pet food|pet toy|cat toy|dog toy|pet grooming|宠物',
    '男装与男士内衣': r'mens clothing|men.s clothing|男装',
    '鞋靴': r'sneaker|shoe|sandal|boot\b|鞋', '箱包配饰': r'handbag|jewelry|necklace|earring|手提包|首饰',
    '家电': r'vacuum|air fryer|blender|appliance|吸尘器|家电',
    '汽车与摩托车': r'car accessory|car accessories|car parts|motorcycle|汽车',
    '玩具与爱好': r'toys|crafts|玩具|手工'
}


def browser_ready():
    if importlib.util.find_spec('playwright') is None:
        return False
    if Path('/Applications/Google Chrome.app/Contents/MacOS/Google Chrome').exists():
        return True
    # The portable install uses the full Chromium build, including in headless mode.
    try:
        import playwright
        cache = Path(os.environ.get('PLAYWRIGHT_BROWSERS_PATH', str(Path.home() / 'Library/Caches/ms-playwright')))
        return bool(list(cache.glob('chromium-*/chrome-mac-arm64/Google Chrome for Testing.app/Contents/MacOS/Google Chrome for Testing')) or list(cache.glob('chromium-*/chrome-linux*/chrome')))
    except (ImportError, OSError):
        return False


def extract_items(payload):
    """Recognize video objects inside search API/hydration envelopes, preserving IDs."""
    found, stack, seen = {}, [payload], 0
    while stack and seen < 50000:
        node = stack.pop(); seen += 1
        if isinstance(node, list):
            stack.extend(node)
        elif isinstance(node, dict):
            vid = str(node.get('id') or node.get('aweme_id') or '')
            if re.fullmatch(r'[0-9]{1,30}', vid) and isinstance(node.get('video'), dict) and isinstance(node.get('author'), dict):
                found[vid] = node
            else:
                stack.extend(v for v in node.values() if isinstance(v, (dict, list)))
    return list(found.values())


def products_from(item):
    products, stack, count = {}, [item], 0
    while stack and count < 1500:
        node = stack.pop(); count += 1
        if isinstance(node, list):
            stack.extend(node)
        elif isinstance(node, dict):
            pid = node.get('productId') or node.get('product_id')
            url = node.get('productUrl') or node.get('product_url') or node.get('anchor_url') or ''
            if not pid and isinstance(url, str):
                match = re.search(r'/(?:view/product|pdp)/([0-9]+)', url)
                pid = match.group(1) if match else None
            if pid:
                # Price fields differ in units between payloads: do not guess cents vs dollars.
                title = node.get('productName') or node.get('product_name') or node.get('title') or ''
                if isinstance(title, str):
                    products[str(pid)] = {'id': str(pid), 'name': title,
                        'url': url if isinstance(url,str) and url.startswith(('https://','http://')) else '',
                        'price': None, 'evidence':'TikTok 视频响应中的明确商品 ID / 商品链接', 'source':'TikTok 视频页面响应'}
            stack.extend(v for v in node.values() if isinstance(v, (dict,list)))
    return list(products.values())


def inferred_category(text):
    for category, pattern in CATEGORY_RULES.items():
        match = re.search(pattern, text, re.I)
        if match:
            return category, '文案关键词推断：' + match.group(0) + '；不是官方类目'
    return '未分类', '没有足够文案证据判断类目'


def item_to_row(item, target_market, query):
    vid = str(item.get('id') or item.get('aweme_id'))
    author = item.get('author') or {}
    handle = author.get('uniqueId') or author.get('unique_id') or ''
    video = item.get('video') or {}
    stats = item.get('statsV2') or item.get('stats') or item.get('statistics') or {}
    title = str(item.get('desc') or '')
    category, evidence = inferred_category(title)
    products = products_from(item)
    commerce, commerce_evidence = None, ''
    if item.get('isECVideo') in (1, '1', True):
        commerce, commerce_evidence = True, 'TikTok 响应明确标记 isECVideo=1'
    elif products:
        commerce, commerce_evidence = True, 'TikTok 视频响应包含明确商品 ID / 商品链接'
    elif re.search(r'tiktokshop|shop\s*tiktok|creator earns commission|#ad\b', title, re.I):
        commerce_evidence = '文案有带货或广告线索，尚未确认商品挂载'
    stamp = item.get('createTime') or item.get('create_time')
    published = ''
    if stamp:
        try: published = dt.datetime.fromtimestamp(int(stamp), dt.timezone.utc).isoformat()
        except (ValueError, TypeError, OverflowError, OSError): pass
    cover = video.get('cover') or video.get('originCover') or ''
    if isinstance(cover, dict):
        cover = (cover.get('url_list') or [''])[0]
    def metric(*keys):
        for key in keys:
            if key in stats and stats[key] is not None:
                try: return int(stats[key])
                except (TypeError,ValueError): pass
        return None
    views, likes, comments, shares = metric('playCount','play_count'), metric('diggCount','digg_count'), metric('commentCount','comment_count'), metric('shareCount','share_count')
    return dict(video_id=vid, video_url='https://www.tiktok.com/@%s/video/%s' % (handle,vid),
        title=title, author=handle or str(author.get('nickname') or ''), cover_url=cover if isinstance(cover,str) else '',
        country='UNKNOWN', target_market=target_market, market_evidence='搜索目标市场；未从响应核验销售市场',
        category=category, category_evidence=evidence, subcategory='', search_query=query,
        is_commerce=commerce, commerce_evidence=commerce_evidence, published_at=published,
        views=views, likes=likes, comments=comments, shares=shares,
        engagement_rate=(likes+comments+shares)/views*100 if views and all(x is not None for x in (likes,comments,shares)) else None,
        duration=video.get('duration'), estimated_sales=None, estimated_revenue=None,
        source='TikTok 公开网页搜索（免费浏览器采集）', products=products)


class Collector:
    def __init__(self, save_rows):
        self.save_rows = save_rows
        self.lock = threading.Lock()
        self.job = None
        self.finish = threading.Event()
        self.cancel = threading.Event()

    def status(self):
        with self.lock:
            return dict(self.job) if self.job else {'status':'idle', 'message':'尚未开始采集'}

    def update(self, **fields):
        with self.lock:
            self.job.update(fields)

    def start(self, request):
        if not browser_ready():
            raise ValueError('浏览器组件尚未就绪，请运行 .venv/bin/python -m playwright install chromium')
        mode = request.get('mode','search')
        if mode not in ('search','login'):
            raise ValueError('无效采集操作')
        market = str(request.get('market') or 'US').upper()
        if market not in ('US','GB','ID','TH','MY','VN'):
            raise ValueError('请选择一个目标市场')
        category = str(request.get('category') or '')
        subcategory = str(request.get('subcategory') or '')
        query = str(request.get('query') or '').strip()
        if mode == 'search' and not query:
            query = SUBSEEDS.get(subcategory) or SEEDS.get(category) or ''
            if not query: raise ValueError('请输入商品关键词，或先选择带货类目')
        if len(query)>150: raise ValueError('关键词最多 150 个字符')
        limit = int(request.get('limit',20))
        if not 1<=limit<=50: raise ValueError('每次采集 1～50 条')
        with self.lock:
            if self.job and self.job['status'] in ('running','awaiting_login','cancelling'):
                raise ValueError('已有浏览器任务运行中，请完成或取消后再试')
            self.finish.clear();self.cancel.clear()
            self.job = dict(id=uuid.uuid4().hex, status='running', mode=mode, query=query,
                market=market, imported=0, message='正在打开独立 TikTok 浏览器窗口',
                started_at=dt.datetime.now(dt.timezone.utc).isoformat())
        threading.Thread(target=self.run, args=(mode,query,market,limit), daemon=True).start()
        return self.status()

    def signal(self, action):
        if action=='cancel': self.cancel.set()
        elif action=='finish': self.finish.set()
        else: raise ValueError('无效操作')
        return self.status()

    def export_cookies(self, context):
        rows=['# Netscape HTTP Cookie File']
        for c in context.cookies(['https://www.tiktok.com']):
            if c['domain'].lstrip('.') != 'tiktok.com': continue
            rows.append('\t'.join([c['domain'], 'TRUE' if c['domain'].startswith('.') else 'FALSE',
                c['path'], 'TRUE' if c['secure'] else 'FALSE', str(max(0,int(c['expires']))), c['name'], c['value']]))
        COOKIES.parent.mkdir(parents=True,exist_ok=True)
        fd=os.open(COOKIES,os.O_WRONLY|os.O_CREAT|os.O_TRUNC,0o600)
        with os.fdopen(fd,'w') as fp:fp.write('\n'.join(rows)+'\n')
        os.chmod(COOKIES,0o600)

    def run(self, mode, query, market, limit):
        context = None
        try:
            from playwright.sync_api import sync_playwright
            with sync_playwright() as p:
                PROFILE.mkdir(parents=True,exist_ok=True,mode=0o700)
                channel='chrome' if Path('/Applications/Google Chrome.app/Contents/MacOS/Google Chrome').exists() else 'chromium'
                context = p.chromium.launch_persistent_context(str(PROFILE), headless=os.environ.get('COLLECTOR_HEADLESS')=='1',
                    channel=channel, locale='en-US', timezone_id='America/Los_Angeles', viewport={'width':1280,'height':900},
                    accept_downloads=False)
                try:
                    page = context.pages[0] if context.pages else context.new_page()
                    if mode=='login':
                        page.goto('https://www.tiktok.com/login',wait_until='domcontentloaded',timeout=45000)
                        self.update(status='awaiting_login',message='请在弹出的 TikTok 窗口完成登录，再回工作台点击“完成登录”；无需粘贴密码或 Cookie')
                        deadline=time.monotonic()+300
                        while not self.finish.is_set() and not self.cancel.is_set() and time.monotonic()<deadline:
                            page.wait_for_timeout(500)
                        if self.cancel.is_set():
                            self.update(status='cancelled',message='已取消登录');return
                        logged_in=any(c['name'] in ('sessionid','sessionid_ss') for c in context.cookies(['https://www.tiktok.com']))
                        if not logged_in:
                            self.update(status='needs_login',message='尚未检测到 TikTok 登录会话，请重新打开登录窗口完成登录');return
                        self.export_cookies(context)
                        self.update(status='done',message='已保存独立浏览器登录会话，可以开始关键词采集');return
                    found, api_codes, api_seen = {}, [], []
                    def receive(response):
                        parsed=urlparse(response.url)
                        if not (parsed.hostname or '').endswith('tiktok.com') or '/api/search/' not in parsed.path:return
                        api_seen.append(response.status)
                        if response.status!=200:return
                        try:
                            payload=response.json()
                            if isinstance(payload,dict) and payload.get('status_code') is not None:api_codes.append(payload['status_code'])
                            for item in extract_items(payload):
                                found[str(item.get('id') or item.get('aweme_id'))]=item
                        except Exception:pass
                    page.on('response',receive)
                    search_query=query if re.search(r'tiktok\s*shop',query,re.I) else query+' tiktok shop'
                    response=page.goto('https://www.tiktok.com/search/video?q='+quote(search_query),wait_until='domcontentloaded',timeout=45000)
                    if response and response.status>=400:
                        raise ValueError('TikTok 页面返回 HTTP %s；请确认网络可正常打开 TikTok' % response.status)
                    self.update(message='正在读取搜索结果；遇到登录或验证时请在浏览器窗口手动完成')
                    for i in range(15):
                        if self.cancel.is_set():break
                        page.wait_for_timeout(1000)
                        if len(found)>=limit:break
                        if i in (3,7,11):
                            for script in page.locator('script#__UNIVERSAL_DATA_FOR_REHYDRATION__,script#SIGI_STATE').all():
                                try:
                                    for item in extract_items(json.loads(script.text_content() or '{}')):
                                        found[str(item.get('id') or item.get('aweme_id'))]=item
                                except (ValueError,TypeError):pass
                            page.mouse.wheel(0,900)
                    if self.cancel.is_set():
                        self.update(status='cancelled',message='已取消采集，未保存本次结果');return
                    if not found:
                        body=page.locator('body').inner_text(timeout=5000).lower()
                        if 2483 in api_codes or 'log in to search' in body or 'login to search' in body:
                            self.update(status='needs_login',message='TikTok 搜索要求登录。请先点击“登录 TikTok”，完成后重新采集');return
                        if any(w in body for w in ('captcha','verify to continue','verify you are human','security check')):
                            self.update(status='blocked',message='TikTok 返回验证页面，本次没有采集到数据。请在登录窗口中手动完成验证后重试');return
                        logged_in=any(c['name'] in ('sessionid','sessionid_ss') for c in context.cookies(['https://www.tiktok.com']))
                        if not logged_in:
                            self.update(status='needs_login',message='未登录会话没有取得搜索视频。请点击“登录 TikTok”，手动完成登录后重新采集');return
                        if not api_seen:
                            self.update(status='blocked',message='页面未提供可读取的搜索数据，可能需要登录或验证；请先完成 TikTok 登录后重试');return
                        self.update(status='empty',message='本次搜索未获取到视频；请更换更具体的英文商品词，或检查登录状态');return
                    rows=[item_to_row(item,market,query) for item in list(found.values())[:limit]]
                    result=self.save_rows(rows)
                    self.export_cookies(context)
                    self.update(status='done',imported=result['imported'],message='已保存 %d 条候选视频；类目为文案推断，实际销售市场未核验' % result['imported'])
                finally:
                    context.close()
        except Exception as exc:
            # Do not expose request URLs, headers, cookie values or the full browser trace.
            message=str(exc).splitlines()[0][:250]
            if 'Executable doesn\'t exist' in message: message='浏览器未安装，请运行 .venv/bin/python -m playwright install chromium'
            elif 'Timeout' in type(exc).__name__:message='访问 TikTok 超时，请确认当前网络能正常打开 TikTok 后重试'
            self.update(status='failed',message=message or '采集失败，请检查网络和浏览器状态')

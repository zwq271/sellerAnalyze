import csv
import io
import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from unittest.mock import patch
import app


class LibraryTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        app.DB_PATH = Path(self.tmp.name) / 'library.sqlite3'
        app.DOWNLOADS = Path(self.tmp.name) / 'downloads'
        app.init_db()

    def tearDown(self):
        self.tmp.cleanup()

    def record(self, vid='7460373937537551634', **fields):
        return dict(video_id=vid, video_url='https://www.tiktok.com/@test/video/'+vid,
                    source='自动测试夹具，不是真实采集', country='US', category='美妆个护',
                    is_commerce=True, products=[{'id':'1730228441641554287','name':'测试商品','price':11.68}], **fields)

    def test_preserves_ids_products_zero_and_unknown(self):
        app.import_rows([self.record(views=0, estimated_sales=None)])
        row = app.get_video('7460373937537551634')
        self.assertEqual(row['products'][0]['id'], '1730228441641554287')
        self.assertIsNone(row['estimated_sales'])
        self.assertEqual(row['views'], 0)
        self.assertEqual(row['products'][0]['price'], 11.68)

    def test_filter_commerce_category_and_missing_metrics(self):
        unknown = self.record('2', estimated_sales=None)
        unknown['is_commerce'] = None
        app.import_rows([self.record('1', views=30000, estimated_sales=10), unknown])
        result = app.filtered({'commerce':['true'],'min_views':['10000'],'category':['美妆个护']})
        self.assertEqual([r['video_id'] for r in result['items']], ['1'])
        self.assertEqual(len(app.filtered({'min_sales':['0']})['items']), 1)

    def test_import_is_atomic_and_duplicate_updates(self):
        with self.assertRaises(ValueError):
            app.import_rows([self.record('1'), {'video_id':'2'}])
        self.assertEqual(app.filtered({})['total'],0)
        app.import_rows([self.record('1', views=1)])
        app.import_rows([self.record('1', views=2)])
        self.assertEqual(app.filtered({})['total'],1)
        self.assertEqual(app.get_video('1')['views'],2)

    def test_sort_unknown_last_and_timezone(self):
        app.import_rows([self.record('1', views=None, published_at='2026-11-12T23:30:00-08:00'),
                         self.record('2', views=0, published_at='2026-11-13T09:00:00Z')])
        self.assertEqual([r['video_id'] for r in app.filtered({'sort':['views'],'order':['asc']})['items']],['2','1'])
        result=app.filtered({'from':['2026-11-12'],'from_utc':['2026-11-12T08:00:00Z'],
                             'to':['2026-11-12'],'to_utc':['2026-11-13T08:00:00Z']})
        self.assertEqual([r['video_id'] for r in result['items']], ['1'])

    def test_rejects_id_precision_loss_and_invalid_dates(self):
        for fields in [{'video_id':7460373937537551634}, {'published_at':'2026-11-12'}]:
            row=self.record();row.update(fields)
            with self.assertRaises(ValueError):app.normalize(row)

    def test_http_export_selected_and_csv_injection(self):
        app.import_rows([self.record('1',title='=1+1'),self.record('2',title='正常')])
        server=app.ThreadingHTTPServer(('127.0.0.1',0),app.Handler)
        app.PORT=server.server_port
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        base='http://127.0.0.1:%d'%app.PORT
        try:
            content=urllib.request.urlopen(base+'/api/export?format=csv&ids=1').read().decode('utf-8-sig')
            rows=list(csv.DictReader(io.StringIO(content)))
            self.assertEqual(len(rows),1)
            self.assertEqual(rows[0]['title'],"'=1+1")
            self.assertEqual(json.loads(rows[0]['products'])[0]['id'],'1730228441641554287')
            request=urllib.request.Request(base+'/api/import',data=b'{"rows":[]}',headers={'Content-Type':'application/json'})
            with self.assertRaises(urllib.error.HTTPError) as err:urllib.request.urlopen(request)
            self.assertEqual(err.exception.code,403)
        finally:
            server.shutdown();server.server_close();thread.join()

    def test_audio_only_download_is_not_success(self):
        row=app.normalize(self.record('1'))
        with app.connect() as conn:
            conn.execute('INSERT INTO tasks VALUES (?,?,?,?,?,?)',('test-task','1','queued','','','now'))
        def fake_download(*args,**kwargs):
            (app.DOWNLOADS/'test-task'/'video.m4a').write_bytes(b'audio')
            return type('Result',(),{'returncode':0,'stderr':''})()
        with patch('app.subprocess.run',side_effect=fake_download):app.download_worker('test-task',row)
        with app.connect() as conn:
            task=conn.execute('SELECT * FROM tasks').fetchone()
            self.assertEqual(task['status'],'failed')
            self.assertIn('仅返回音频',task['error'])


if __name__=='__main__':unittest.main()

"""Run local browser checks against a temporary database, never the user's data."""
import csv
import io
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
from playwright.sync_api import sync_playwright

ROOT=Path(__file__).resolve().parents[1]

def main():
    with tempfile.TemporaryDirectory() as folder:
        with socket.socket() as sock:
            sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
        env=dict(os.environ,PORT=str(port),VIDEO_DB=folder+'/test.sqlite3',VIDEO_DOWNLOADS=folder+'/downloads')
        process=subprocess.Popen([sys.executable,str(ROOT/'app.py')],env=env,stdout=subprocess.DEVNULL)
        base='http://127.0.0.1:%d'%port
        try:
            for _ in range(30):
                try:urllib.request.urlopen(base,timeout=1);break
                except OSError:time.sleep(.1)
            with sync_playwright() as p:
                browser=p.chromium.launch(channel='chrome',headless=True)
                page=browser.new_page(viewport={'width':1440,'height':1100},locale='zh-CN')
                errors=[]
                page.on('pageerror',lambda e:errors.append(str(e)))
                page.goto(base)
                page.locator('#collect-start').wait_for(state='visible')
                page.wait_for_function("document.querySelector('#rows').children.length===0 && document.querySelector('#page-info').textContent.includes('本地共')")
                previews=ROOT/'data/previews';previews.mkdir(parents=True,exist_ok=True)
                page.screenshot(path=str(previews/'desktop.png'),full_page=True)
                assert page.locator('#collect-start').is_enabled()
                assert page.locator('#commerce').is_checked() is False
                page.locator('#import-open').click()
                fixture=[{'video_id':'7460373937537551634','video_url':'https://www.tiktok.com/@test/video/7460373937537551634',
                    'title':'界面验证样例 — skincare serum','country':'UNKNOWN','target_market':'US','category':'美妆个护',
                    'category_evidence':'自动化测试夹具','source':'自动化测试夹具，不是真实视频','views':2000,
                    'is_commerce':None,'products':[{'id':'1','name':'测试商品一'},{'id':'2','name':'测试商品二','price':9.99}]}]
                page.locator('#import-text').fill(json.dumps(fixture,ensure_ascii=False))
                page.locator('#import-submit').click()
                page.locator('#rows tr').wait_for()
                assert page.locator('#rows tr').count()==1
                assert '销售市场未核验' in page.locator('#rows').inner_text()
                page.locator('[data-detail]').click()
                assert '关联商品 · 2' in page.locator('#detail-content').inner_text()
                assert '测试商品二' in page.locator('#detail-content').inner_text()
                page.locator('[data-close="details-dialog"]').click()
                page.locator('.toggle-label').click()
                page.wait_for_function("document.querySelector('#rows').children.length===0")
                page.locator('.toggle-label').click()
                page.locator('#rows tr').wait_for()
                with page.expect_download() as download:
                    page.locator('#export-csv').click()
                rows=list(csv.DictReader(io.StringIO(Path(download.value.path()).read_text(encoding='utf-8-sig'))))
                assert len(rows)==1 and rows[0]['country']=='UNKNOWN'
                assert len(json.loads(rows[0]['products']))==2
                page.set_viewport_size({'width':390,'height':844})
                assert page.evaluate('document.documentElement.scrollWidth<=innerWidth'), 'Mobile page overflows'
                assert not errors,errors
                browser.close()
            print('UI OK: desktop/mobile, import, market labels, product details, commerce filter, CSV export; isolated test database')
        finally:
            process.terminate();process.wait(timeout=10)

if __name__=='__main__':main()

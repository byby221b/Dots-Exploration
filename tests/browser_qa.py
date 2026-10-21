"""Optional Playwright QA. Synthetic content exists only in a temporary directory."""
import functools
import json
import shutil
import sys
import tempfile
import threading
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from playwright.sync_api import sync_playwright
from test_archive import setup, fixture
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from generate import build

class QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self,*args): pass

with tempfile.TemporaryDirectory() as temp:
    root=Path(temp); setup(root)
    a=fixture(); a.update(id='qa-trending',channel='trending',series='测试动态',title='仅测试：每日动态',date='2026-10-06',topics=['动态'])
    a['blocks']=[{'type':'paragraph','text':'仅测试的每日动态正文。'}]
    (root/'content/articles/qa-trending.json').write_text(json.dumps(a,ensure_ascii=False))
    build(root,root/'site',True)
    handler=functools.partial(QuietHandler,directory=str(root/'site'))
    server=ThreadingHTTPServer(('127.0.0.1',0),handler)
    threading.Thread(target=server.serve_forever,daemon=True).start()
    base=f'http://127.0.0.1:{server.server_port}'
    results=[]
    try:
        with sync_playwright() as p:
            browser=p.chromium.launch(headless=True,executable_path=shutil.which('chromium'),chromium_sandbox=True)
            for width in [1440,768,375,320]:
                page=browser.new_page(viewport={'width':width,'height':1000},device_scale_factor=1)
                errors=[]; remote=[]
                page.on('pageerror',lambda e:errors.append(str(e)))
                page.on('request',lambda r: remote.append(r.url) if not r.url.startswith(base) else None)
                page.goto(base+'/index.html'); page.wait_for_selector('.card')
                assert page.locator('.card:visible').count()==2
                assert page.evaluate('document.documentElement.scrollWidth <= innerWidth'),f'Overflow {width}'
                page.locator('#q').fill('answerneedle'); assert page.locator('.card:visible').count()==1
                page.reload(); assert page.locator('#q').input_value()=='answerneedle'
                page.locator('button[type=reset]').click(); page.wait_for_function('document.querySelectorAll(".card:not([hidden])").length===2')
                page.locator('#series').select_option('测试动态'); assert page.locator('.card:visible').count()==1
                page.locator('#series').select_option(''); page.locator('#from').fill('2026-10-06'); assert page.locator('.card:visible').count()==1
                page.locator('#to').fill('2026-10-05'); assert page.locator('#filter-error').inner_text()
                page.locator('button[type=reset]').click(); page.wait_for_function('document.querySelectorAll(".card:not([hidden])").length===2')
                page.locator('#q').fill('notfound'); assert page.locator('#no-results').is_visible()
                page.goto(base+'/exploration/index.html'); assert page.locator('.card:visible').count()==1
                page.locator('.card h2 a').click(); assert page.locator('h1').inner_text()=='仅测试：阅读与公式'
                assert not page.locator('details').evaluate('(el)=>el.open')
                page.locator('summary').click(); assert page.locator('details').evaluate('(el)=>el.open')
                assert page.locator('details').inner_text().find('answerneedle')>=0
                assert page.locator('img').evaluate('(el)=>el.complete && el.naturalWidth>0')
                assert page.locator('.sources a').get_attribute('href')=='https://example.org/paper'
                assert page.evaluate('document.documentElement.scrollWidth <= innerWidth'),f'Article overflow {width}'
                page.screenshot(path=f'/tmp/dots-article-{width}.png',full_page=True)
                page.goto(base+'/index.html'); page.screenshot(path=f'/tmp/dots-index-{width}.png',full_page=True)
                assert not errors, errors
                assert not remote, remote
                results.append({'viewport':width,'search_filters_details_images_links':True,'overflow':False,'remote_requests':len(remote),'console_errors':len(errors)})
                page.close()
            context=browser.new_context(java_script_enabled=False)
            page=context.new_page(); page.goto(base+'/index.html'); assert page.locator('.card').count()==2
            page.locator('.card h2 a').last.click(); assert page.locator('.prose').is_visible()
            browser.close()
        print(json.dumps({'browser':'Chromium','synthetic_only':True,'results':results,'no_js_reading':True},indent=2))
    finally:
        server.shutdown(); server.server_close()

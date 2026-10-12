"""Read-only browser checks of the real, generated pilot, including a Pages base path."""
import functools,json,shutil,threading,tempfile
from pathlib import Path
from http.server import SimpleHTTPRequestHandler,ThreadingHTTPServer
from playwright.sync_api import sync_playwright
ROOT=Path(__file__).resolve().parents[1]
class Quiet(SimpleHTTPRequestHandler):
 def log_message(self,*args):pass
output=Path('/tmp/dots-pilot-qa');output.mkdir(exist_ok=True)
with tempfile.TemporaryDirectory() as d:
 shutil.copytree(ROOT/'site',Path(d)/'Dots-Exploration')
 server=ThreadingHTTPServer(('127.0.0.1',0),functools.partial(Quiet,directory=d))
 threading.Thread(target=server.serve_forever,daemon=True).start()
 base=f'http://127.0.0.1:{server.server_port}/Dots-Exploration/'
 articles=[json.loads(p.read_text()) for p in sorted((ROOT/'content/articles').glob('*.json'))]
 results=[]
 try:
  with sync_playwright() as p:
   browser=p.chromium.launch(executable_path=shutil.which('chromium'),args=['--no-sandbox'])
   for width in [1440,768,375,320]:
    page=browser.new_page(viewport={'width':width,'height':1000},device_scale_factor=1)
    errors=[];failures=[];external=[]
    page.on('pageerror',lambda e:errors.append(str(e)))
    page.on('response',lambda r:failures.append(r.url) if r.status>=400 else None)
    page.on('request',lambda r:external.append(r.url) if not r.url.startswith(base) else None)
    page.goto(base);assert page.locator('.card:visible').count()==13
    page.screenshot(path=str(output/f'index-{width}.png'),full_page=True)
    page.locator('#q').fill('逆方差');assert page.locator('.card:visible').count()==1
    page.reload();assert page.locator('#q').input_value()=='逆方差'
    page.locator('button[type=reset]').click();page.wait_for_function('document.querySelectorAll(".card:not([hidden])").length===13')
    page.locator('#series').select_option('每日 Trending');assert page.locator('.card:visible').count()==7
    page.locator('#from').fill('2026-10-11');assert page.locator('.card:visible').count()==1
    page.locator('#to').fill('2026-10-05');assert page.locator('#filter-error').inner_text()
    page.locator('button[type=reset]').click();page.wait_for_function('document.querySelectorAll(".card:not([hidden])").length===13')
    page.locator('#q').fill('notfoundxyz');assert page.locator('#no-results').is_visible()
    page.goto(base+'trending/');assert page.locator('.card:visible').count()==7
    page.goto(base+'exploration/');assert page.locator('.card:visible').count()==6
    page.locator('.card h2 a').first.click();assert page.locator('.prose').is_visible()
    images=0;disclosures=0
    for a in articles:
     page.goto(base+f'articles/{a["id"]}/');assert page.locator('h1').inner_text()==a['title']
     assert page.locator('.sources a').evaluate_all('(els)=>els.map(e=>e.href)')==[s['url'] for s in a['sources']]
     for detail in page.locator('details').all():
      assert not detail.evaluate('(e)=>e.open');detail.locator('summary').click();assert detail.evaluate('(e)=>e.open');disclosures+=1
     for im in page.locator('img').all():
      im.scroll_into_view_if_needed();im.evaluate('(e)=>e.decode()');assert im.evaluate('(e)=>e.naturalWidth>0 && e.clientWidth>0');images+=1
     assert page.evaluate('document.documentElement.scrollWidth<=innerWidth'),(width,a['id'])
     if a['id'].startswith(('math-','interview-','research-','japanese-','tech-')) and width in (1440,375):
      page.screenshot(path=str(output/f'{a["id"]}-{width}.png'),full_page=True)
    assert images==14 and disclosures==4,(images,disclosures)
    assert not errors and not failures and not external,(errors,failures,external)
    results.append(dict(width=width,articles=13,images=images,disclosures=disclosures,overflow=False,errors=errors,failed_requests=failures,external_requests=external))
    page.close()
   context=browser.new_context(java_script_enabled=False);page=context.new_page();page.goto(base);assert page.locator('.card').count()==13
   page.goto(base+'articles/interview-challenge-2026-10-10/');page.locator('summary').last.click();assert page.locator('details').last.evaluate('(e)=>e.open')
   browser.close()
 finally:server.shutdown()
report={'browser':'Chromium','real_pilot':True,'base_path':'/Dots-Exploration/','results':results,'no_js_reading':True}
(output/'results.json').write_text(json.dumps(report,indent=2));print(json.dumps(report,indent=2))

"""Read-only QA of the real catalog, including a Pages subpath and batch increments."""
import argparse,functools,json,shutil,sys,threading,tempfile
from pathlib import Path
from http.server import SimpleHTTPRequestHandler,ThreadingHTTPServer
from playwright.sync_api import sync_playwright
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
from generate import load_articles,archive_catalog
from verify import check_increment
class Quiet(SimpleHTTPRequestHandler):
 def log_message(self,*args):pass


def main():
 parser=argparse.ArgumentParser();parser.add_argument('--output',type=Path,default=ROOT/'.qa/reading')
 parser.add_argument('--baseline',type=Path)
 for key in ('articles','images','trending','exploration'):parser.add_argument('--expect-added-'+key,type=int)
 args=parser.parse_args();output=args.output;output.mkdir(parents=True,exist_ok=True)
 articles=load_articles(ROOT,True);catalog=archive_catalog(articles)
 assert catalog==json.loads((ROOT/'site/catalog.json').read_text()),'Stale catalog'
 increment=None
 if args.baseline:
  expected={k:getattr(args,'expect_added_'+k) for k in ('articles','images','trending','exploration')}
  assert all(v is not None for v in expected.values()),'Specify all four expected increments'
  increment=check_increment(catalog,json.loads(args.baseline.read_text()),expected)
 else:assert all(getattr(args,'expect_added_'+k) is None for k in ('articles','images','trending','exploration')),'Baseline required'
 counts=catalog['channels']; total=len(articles);lookup={a['id']:a for a in catalog['articles']}
 expected_images=sum(len(a['images']) for a in lookup.values()); expected_details=sum(a['disclosures'] for a in lookup.values())
 results=[]
 with tempfile.TemporaryDirectory() as d:
  shutil.copytree(ROOT/'site',Path(d)/'Dots-Exploration')
  server=ThreadingHTTPServer(('127.0.0.1',0),functools.partial(Quiet,directory=d))
  threading.Thread(target=server.serve_forever,daemon=True).start();base=f'http://127.0.0.1:{server.server_port}/Dots-Exploration/'
  try:
   with sync_playwright() as p:
    browser=p.chromium.launch(executable_path=shutil.which('chromium'),args=['--no-sandbox'])
    for width in [1440,768,375,320]:
     page=browser.new_page(viewport={'width':width,'height':1000},device_scale_factor=1)
     errors=[];failures=[];external=[]
     page.on('pageerror',lambda e:errors.append(str(e)))
     page.on('response',lambda r:failures.append(r.url) if r.status>=400 else None)
     page.on('request',lambda r:external.append(r.url) if not r.url.startswith(base) else None)
     page.goto(base);assert page.locator('.card:visible').count()==total
     assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
     page.screenshot(path=str(output/f'index-{width}.png'),full_page=True)
     term=articles[0]['title']
     page.locator('#q').fill(term);assert page.locator('.card:visible').count()>=1
     page.reload();assert page.locator('#q').input_value()==term
     def reset():
      page.locator('button[type=reset]').click();page.wait_for_function('(n)=>document.querySelectorAll(".card:not([hidden])").length===n',arg=total)
     reset();series=articles[0]['series'];page.locator('#series').select_option(series)
     assert page.locator('.card:visible').count()==sum(a['series']==series for a in articles)
     reset();page.locator('#from').fill(catalog['end']);assert page.locator('.card:visible').count()==sum(a['date']==catalog['end'] for a in articles)
     page.locator('#to').fill('1900-01-01');assert page.locator('#filter-error').inner_text()
     reset();page.locator('#q').fill('notfoundxyz');assert page.locator('#no-results').is_visible()
     for channel in counts:
      page.goto(base+channel+'/');assert page.locator('.card:visible').count()==counts[channel]
      if counts[channel]:page.locator('.card h2 a').first.click();assert page.locator('.prose').is_visible()
     images=0;disclosures=0;cards=0
     for a in articles:
      page.goto(base+f'articles/{a["id"]}/');assert page.locator('h1').inner_text()==a['title']
      assert page.locator('.sources a').evaluate_all('(els)=>els.map(e=>e.href)')==[s['url'] for s in a['sources']]
      assert page.locator('.trend-item').count()==lookup[a['id']]['trending_items'];cards+=page.locator('.trend-item').count()
      # No nested hint/solution headings can leak into the opening navigation.
      assert page.locator('.contents a').evaluate_all('(els)=>els.every(e=>!document.querySelector(e.getAttribute("href")).closest("details"))')
      if page.locator('.contents a').count():
       page.locator('.contents a').first.click();assert page.evaluate('!!document.querySelector(location.hash)')
      if width in (1440,375):
       page.evaluate('scrollTo(0,0)');page.screenshot(path=str(output/f'{a["id"]}-{width}-top.png'))
      for detail in page.locator('details').all():
       assert not detail.evaluate('(e)=>e.open');detail.locator('summary').click();assert detail.evaluate('(e)=>e.open');disclosures+=1
      for index,im in enumerate(page.locator('img').all()):
       im.scroll_into_view_if_needed();im.evaluate('(e)=>e.decode()');assert im.evaluate('(e)=>e.naturalWidth>0 && e.clientWidth>0');images+=1
       assert im.evaluate('(e)=>e.closest("a").href===e.src')
       if width in (1440,375):im.locator('xpath=ancestor::figure').screenshot(path=str(output/f'{a["id"]}-{width}-figure-{index}.png'))
      assert page.evaluate('document.documentElement.scrollWidth<=innerWidth'),(width,a['id'])
      assert page.locator('.table-wrap').evaluate_all('(els)=>els.every(e=>e.getBoundingClientRect().right<=innerWidth)'),(width,a['id'],'table')
      if width in (1440,375):page.screenshot(path=str(output/f'{a["id"]}-{width}.png'),full_page=True)
     assert images==expected_images and disclosures==expected_details and cards==catalog['trending_items'],(images,disclosures,cards)
     assert not errors and not failures and not external,(errors,failures,external)
     results.append(dict(width=width,articles=total,images=images,disclosures=disclosures,trending_cards=cards,overflow=False,errors=errors,failed_requests=failures,external_requests=external));page.close()
    context=browser.new_context(java_script_enabled=False,viewport={'width':375,'height':1000});page=context.new_page();page.goto(base);assert page.locator('.card').count()==total
    for a in articles:
     page.goto(base+f'articles/{a["id"]}/');assert page.locator('h1').inner_text()==a['title']
     for detail in page.locator('details').all():
      detail.locator('summary').click();assert detail.evaluate('(e)=>e.open')
     for im in page.locator('img').all():
      im.scroll_into_view_if_needed();assert im.evaluate('(e)=>e.complete && e.naturalWidth>0')
     assert page.evaluate('document.documentElement.scrollWidth<=innerWidth'),('no-js',a['id'])
    browser.close()
  finally:server.shutdown()
 report={'browser':'Chromium','real_content':True,'catalog':catalog,'increment':increment,'base_path':'/Dots-Exploration/','results':results,'no_js_reading':True}
 (output/'results.json').write_text(json.dumps(report,ensure_ascii=False,indent=2));print(json.dumps({k:v for k,v in report.items() if k!='catalog'},indent=2))
if __name__=='__main__':main()

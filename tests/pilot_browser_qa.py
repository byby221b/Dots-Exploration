"""Read-only QA of the real catalog, including a Pages subpath and batch increments."""
import argparse,functools,hashlib,json,re,shutil,subprocess,sys,threading,tempfile
from contextlib import contextmanager
from urllib.parse import urlsplit
from pathlib import Path
from http.server import SimpleHTTPRequestHandler,ThreadingHTTPServer
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
from generate import load_articles,archive_catalog
from verify import check_increment
class Quiet(SimpleHTTPRequestHandler):
 def log_message(self,*args):pass


PUBLIC_BASE = 'https://byby221b.github.io/Dots-Exploration/'


def public_base(value):
 # Remote QA is scoped to the authorized Pages destination, never arbitrary URLs.
 if value not in (PUBLIC_BASE, PUBLIC_BASE.rstrip('/')):
  raise argparse.ArgumentTypeError('Use the authorized HTTPS Pages root without query or fragment')
 return PUBLIC_BASE


def parse_args(argv=None):
 parser=argparse.ArgumentParser(description=__doc__)
 parser.add_argument('--output',type=Path,default=ROOT/'.qa/reading')
 parser.add_argument('--baseline',type=Path)
 parser.add_argument('--base-url',type=public_base,help='Verify the deployed authorized Pages site')
 parser.add_argument('--commit',help='Exact deployed commit SHA; required with --base-url')
 for key in ('articles','images','trending','exploration'):parser.add_argument('--expect-added-'+key,type=int)
 args=parser.parse_args(argv)
 if bool(args.base_url) != bool(args.commit):parser.error('--base-url and --commit must be supplied together')
 if args.commit and not re.fullmatch('[0-9a-f]{40}',args.commit):parser.error('--commit must be a full lowercase SHA')
 increments=[getattr(args,'expect_added_'+k) for k in ('articles','images','trending','exploration')]
 if args.baseline:
  if any(v is None or v<0 for v in increments):parser.error('Baseline requires all four nonnegative increments')
 elif any(v is not None for v in increments):parser.error('Baseline required with increments')
 return args


def verify_checkout(commit, root=ROOT):
 def git(*args):return subprocess.check_output(['git',*args],cwd=root).decode().strip()
 assert git('rev-parse','HEAD')==commit,'Checkout does not match the deployed commit'
 assert not git('status','--porcelain=v1','--untracked-files=all'),'Remote QA requires a clean committed checkout'


@contextmanager
def preview_base(remote=None):
 if remote:
  yield remote
  return
 with tempfile.TemporaryDirectory() as d:
  shutil.copytree(ROOT/'site',Path(d)/'Dots-Exploration')
  server=ThreadingHTTPServer(('127.0.0.1',0),functools.partial(Quiet,directory=d))
  thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
  try:yield f'http://127.0.0.1:{server.server_port}/Dots-Exploration/'
  finally:server.shutdown();server.server_close();thread.join()


def verify_remote_build(request, base, root=ROOT):
 # Default TLS verification remains enabled. Reject redirects and stale/partial deployments.
 site=root/'site';manifest_bytes=(site/'build-manifest.json').read_bytes()
 manifest=json.loads(manifest_bytes)
 for name,digest in [('build-manifest.json',hashlib.sha256(manifest_bytes).hexdigest()),*manifest.items()]:
  assert hashlib.sha256((site/name).read_bytes()).hexdigest()==digest,('Local build mismatch',name)
  response=request.get(base+name,max_redirects=0,timeout=30000)
  try:
   assert response.status==200,('Remote HTTP status',name,response.status)
   assert hashlib.sha256(response.body()).hexdigest()==digest,('Remote build mismatch',name)
  finally:response.dispose()
 return hashlib.sha256(manifest_bytes).hexdigest()


def main():
 args=parse_args()
 if args.commit:verify_checkout(args.commit)
 output=args.output;output.mkdir(parents=True,exist_ok=True)
 from playwright.sync_api import sync_playwright
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
 with preview_base(args.base_url) as base:
  with sync_playwright() as p:
   browser=p.chromium.launch(executable_path=shutil.which('chromium'),chromium_sandbox=True)
   request=browser.new_context().request if args.base_url else None
   manifest_sha256=verify_remote_build(request,base) if args.base_url else None
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
   if args.base_url:verify_remote_build(request,base)
   browser.close()
 report={'browser':'Chromium','real_content':True,'catalog':catalog,'increment':increment,'base_path':urlsplit(base).path,'base_url':base,'commit':args.commit,'manifest_sha256':manifest_sha256,'results':results,'no_js_reading':True}
 (output/'results.json').write_text(json.dumps(report,ensure_ascii=False,indent=2));print(json.dumps({k:v for k,v in report.items() if k!='catalog'},indent=2))
if __name__=='__main__':main()

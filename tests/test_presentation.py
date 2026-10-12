"""Content invariants for presentation and data-derived archive coverage."""
import copy,json,re,sys,tempfile,unittest
from html.parser import HTMLParser
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from generate import ROOT,inline,load_articles,render_blocks,archive_catalog,contents_nav,shell
from verify import check_increment
from test_archive import setup,fixture

class Meaning(HTMLParser):
    def __init__(self):
        super().__init__();self.words=[];self.links=[];self.images=[];self.skip=0
    def handle_starttag(self,tag,attrs):
        a=dict(attrs)
        if 'reading-aid' in a.get('class','').split():self.skip=1;return
        if self.skip:self.skip+=1;return
        if tag=='a' and a.get('href','').startswith('https://'):self.links.append((a['href']))
        if tag=='img':self.images.append((a['src'].removeprefix('../../'),a.get('alt')))
    def handle_endtag(self,tag):
        if self.skip:self.skip-=1
    def handle_data(self,data):
        if not self.skip:self.words.append(data)
    @property
    def signature(self):return (re.sub(r'\s+','',''.join(self.words)),self.links,self.images)

def meaning(markup):
    p=Meaning();p.feed(markup);return p.signature

def expected(blocks):
    texts=[];links=[];images=[]
    for b in blocks:
        k=b['type']
        if k=='image':images.append((b['src'],b['alt']));continue
        if k=='details':
            sig=meaning(inline(b['summary']));child=expected(b['blocks']);texts.extend([sig[0],child[0]]);links.extend(sig[1]+child[1]);images.extend(child[2]);continue
        values=([b['text']] if k in ('paragraph','heading','quote','code') else b['items'] if k=='list' else b['headers']+[x for row in b['rows'] for x in row])
        for value in values:
            if k=='code':texts.append(value)
            else:
                sig=meaning(inline(value));texts.append(sig[0]);links.extend(sig[1])
    return (re.sub(r'\s+','',''.join(texts)),links,images)

class PresentationTests(unittest.TestCase):
    def test_math_subscripts_and_superscripts_are_safe(self):
        markup=inline('q~{i} r~{A} e^{x} <sub onclick="bad()">i</sub> ~{<img>}')
        self.assertIn('q<sub>i</sub> r<sub>A</sub> e<sup>x</sup>',markup)
        self.assertNotIn('<img',markup);self.assertNotIn('<sub onclick=',markup)
        self.assertIn('&lt;sub',markup)
    def test_source_subheadings_preserved_and_validated(self):
        blocks=[{'type':'heading','text':'Main'},{'type':'heading','text':'Subsection','level':3}]
        markup,_=render_blocks(blocks,Path('.'))
        self.assertIn('<h2 id="section-0">Main',markup)
        self.assertIn('<h3 id="section-1">Subsection',markup)
        for invalid in (1,4,True,'3'):
            with self.assertRaises(ValueError):render_blocks([{'type':'heading','text':'Bad','level':invalid}],Path('.'))
    def test_revision_label_does_not_duplicate_title_in_navigation(self):
        a=fixture();a['title']='Softmax（修订版）';a['blocks']=[{'type':'heading','text':'Softmax'},{'type':'heading','text':'问题'},{'type':'heading','text':'推导'}]
        self.assertNotIn('>Softmax</a>',contents_nav(a))
        markup,_=render_blocks(a['blocks'],Path('.'),title=a['title'])
        self.assertIn('<p class="source-title">Softmax</p>',markup)
    def test_all_canonical_text_links_and_images_are_preserved(self):
        for a in load_articles(ROOT,True):
            with self.subTest(article=a['id']):self.assertEqual(meaning(a['_body']),expected(a['blocks']))
    def test_trending_cards_and_metadata(self):
        blocks=[{'type':'heading','text':'开源'}, {'type':'paragraph','text':'[标题](https://example.org/a) [讨论](https://example.org/b)'}, {'type':'paragraph','text':'当日热榜'}, {'type':'paragraph','text':'完整介绍与限制。'}, {'type':'paragraph','text':'正文里的 [链接](https://example.org/c) 不能开新卡片。'}]
        markup,_=render_blocks(blocks,Path('.'),channel='trending')
        self.assertEqual(markup.count('class="trend-item"'),1);self.assertIn('class="item-meta">当日热榜',markup)
        self.assertEqual(meaning(markup),expected(blocks))
    def test_no_solution_heading_in_opening_navigation(self):
        a=fixture();a['blocks']=[{'type':'heading','text':'题目'},{'type':'details','summary':'提示','blocks':[{'type':'heading','text':'secretanswer'}]},{'type':'heading','text':'来源'}]
        nav=contents_nav(a);self.assertNotIn('secretanswer',nav);self.assertIn('#section-2',nav)
        markup,_=render_blocks(a['blocks'],Path('.'));self.assertIn('<h3 id="section-1-0">secretanswer',markup)
    def test_catalog_and_footer_follow_new_dates(self):
        a=fixture();a['date']='2027-01-03';a['_body']='';b=copy.deepcopy(a);b['id']='second';b['date']='2027-02-15'
        c=archive_catalog([a,b]);self.assertEqual(c['articles_count'],2);self.assertEqual(c['images_count'],1)
        markup=shell('test','',catalog=c);self.assertIn('2027-01-03 — 2027-02-15',markup);self.assertNotIn('2026-10-05',markup)
    def test_exact_batch_increment_and_no_removed_articles(self):
        a=fixture();a['blocks']=[];base=archive_catalog([a]);b=copy.deepcopy(a);b['id']='second';b['channel']='trending'
        changed=archive_catalog([a,b]);good={'articles':1,'images':0,'trending':1,'exploration':0}
        self.assertEqual(check_increment(changed,base,good),good)
        with self.assertRaises(AssertionError):check_increment(changed,base,good|{'articles':2})
        with self.assertRaises(AssertionError):check_increment(archive_catalog([b]),base,good)

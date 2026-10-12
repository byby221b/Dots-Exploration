import base64
import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from generate import ROOT, build, load_articles
from import_content import import_package
from verify import verify

# Test-only synthetic data; never imported into content/ or the public site.
def fixture():
    return {'id':'qa-article','revision':1,'date':'2026-10-05','channel':'exploration','series':'测试系列','title':'仅测试：阅读与公式','summary':'仅用于自动化验证的合成内容。','topics':['检索','公式'],'public_reviewed':True,'blocks':[{'type':'paragraph','text':'测试全文关键词 fulltextneedle 与 **强调**，以及 [公开来源](https://example.org/paper)。'},{'type':'heading','text':'测试小节'},{'type':'image','src':'assets/qa.png','alt':'仅测试公式 x = y','caption':'合成测试图'},{'type':'details','summary':'展开面试提示答案','blocks':[{'type':'paragraph','text':'测试答案 answerneedle。'}]},{'type':'table','headers':['项目','内容'],'rows':[['测试','验证']]},{'type':'code','text':'<script>never execute</script>'}], 'sources':[{'title':'测试来源','url':'https://example.org/paper'}]}

def setup(root):
    (root/'content/articles').mkdir(parents=True)
    (root/'content/assets').mkdir()
    (root/'web').mkdir()
    for p in (ROOT/'web').iterdir(): (root/'web'/p.name).write_bytes(p.read_bytes())
    (root/'content/articles/qa-article.json').write_text(json.dumps(fixture(),ensure_ascii=False))
    (root/'content/assets/qa.png').write_bytes(base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/l9sAAAAASUVORK5CYII='))

class ArchiveTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.root=Path(self.tmp.name); setup(self.root)
    def tearDown(self): self.tmp.cleanup()
    def write(self,a): (self.root/'content/articles/qa-article.json').write_text(json.dumps(a))
    def test_deterministic_and_links(self):
        build(self.root,self.root/'site',True); verify(self.root)
        build(self.root,self.root/'second',True)
        a={str(p.relative_to(self.root/'site')):p.read_bytes() for p in (self.root/'site').rglob('*') if p.is_file()}
        b={str(p.relative_to(self.root/'second')):p.read_bytes() for p in (self.root/'second').rglob('*') if p.is_file()}
        self.assertEqual(a,b)
        text=(self.root/'site/articles/qa-article/index.html').read_text()
        self.assertIn('<details>',text); self.assertIn('&lt;script&gt;',text)
        self.assertNotIn('<script>never',text)
    def test_private_and_unknown_metadata_rejected(self):
        for change in [{'summary':'person' + '@' + 'example.com'},{'mail_id':'private'},{'public_reviewed':False},{'date':'2026-02-30'}]:
            a=fixture(); a.update(change); self.write(a)
            with self.assertRaises(ValueError): load_articles(self.root,True)
    def test_unsafe_or_missing_resources(self):
        for src in ['assets/no.png','../../secret.png','https://example.org/image.png']:
            a=fixture(); a['blocks'][2]['src']=src; self.write(a)
            with self.assertRaises(ValueError): load_articles(self.root,True)
        a=fixture(); a['sources'][0]['url']='javascript:alert(1)'; self.write(a)
        with self.assertRaises(ValueError): load_articles(self.root,True)
    def test_duplicate_body_rejected(self):
        a=fixture(); a['id']='different-id'; a['title']='Different title'
        (self.root/'content/articles/different-id.json').write_text(json.dumps(a))
        with self.assertRaises(ValueError): load_articles(self.root,True)
    def test_empty_public_rejected(self):
        (self.root/'content/articles/qa-article.json').unlink()
        with self.assertRaises(ValueError): load_articles(self.root,True)
    def test_revision_and_failed_import_rollback(self):
        package=self.root/'incoming'; (package/'articles').mkdir(parents=True)
        p=package/'articles/qa-article.json'; a=fixture(); p.write_text(json.dumps(a))
        import_package(package,self.root) # idempotent
        before=(self.root/'content/articles/qa-article.json').read_bytes()
        a['summary']='Changed'; p.write_text(json.dumps(a))
        with self.assertRaises(ValueError): import_package(package,self.root)
        self.assertEqual(before,(self.root/'content/articles/qa-article.json').read_bytes())
        a['revision']=2; p.write_text(json.dumps(a)); import_package(package,self.root)
        self.assertEqual(load_articles(self.root,True)[0]['revision'],2)

if __name__=='__main__': unittest.main()


class InlineReferences(unittest.TestCase):
    def test_bracketed_citations_preserve_labels(self):
        from generate import inline
        self.assertIn('>[1]</a>', inline('[[1]](https://example.org/a)'))
        self.assertTrue(inline('[1] [Paper](https://example.org/a)').startswith('[1] <a'))

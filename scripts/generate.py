#!/usr/bin/env python3
"""Deterministic static archive builder. Python standard library only."""
import argparse
import hashlib
import html
import json
import re
import shutil
import tempfile
from datetime import date
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
CHANNELS = {'trending': '每日 Trending', 'exploration': '每周探索'}
TOP_KEYS = {'id','revision','date','channel','series','title','summary','topics','blocks','sources','public_reviewed'}
PRIVATE = re.compile(r'[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}|(?:gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]+)|-----BEGIN .*PRIVATE KEY-----|\b(?:message_id|thread_id|email_id|send_history|private_feedback|rating_algorithm)\b', re.I)

def require(ok, message):
    if not ok:
        raise ValueError(message)

def clean(text):
    require(isinstance(text, str) and text.strip(), 'Expected nonempty text')
    require(not PRIVATE.search(text), 'Potential private metadata or credential detected')
    return text

def url(value):
    clean(value)
    p = urlsplit(value)
    require(p.scheme == 'https' and p.hostname and not p.username and not p.password, 'Source links must be public HTTPS URLs')
    require(not p.query or not re.search(r'token|signature|credential|auth|email', p.query, re.I), 'Possible signed/private source URL')
    require(not p.hostname.endswith(('.local', '.internal')) and p.hostname not in {'localhost','127.0.0.1'}, 'Private URL')
    return value

def inline(text):
    # Escape all HTML before supporting a deliberately small, safe inline syntax.
    clean(text)
    parts = re.split(r'(\[(?:[^\[\]\n]|\[[^\[\]\n]*\])+\]\(https://[^\s)]+\))', text)
    out = []
    for part in parts:
        m = re.fullmatch(r'\[((?:[^\[\]\n]|\[[^\[\]\n]*\])+)\]\((https://[^\s)]+)\)', part)
        if m:
            out.append(f'<a href="{html.escape(url(m[2]), quote=True)}" rel="noreferrer">{html.escape(m[1])}</a>')
        else:
            s = html.escape(part)
            s = re.sub(r'`([^`\n]+)`', r'<code>\1</code>', s)
            s = re.sub(r'\*\*([^*\n]+)\*\*', r'<strong>\1</strong>', s)
            s = re.sub(r'~\{([A-Za-z0-9+-]+)\}', r'<sub>\1</sub>', s)
            s = re.sub(r'\^\{([A-Za-z0-9+-]+)\}', r'<sup>\1</sup>', s)
            out.append(s.replace('\n', '<br>'))
    return ''.join(out)

def link_title(text):
    """Only all-link paragraphs can start a Trending card; never guess from prose."""
    pattern = r'\[(?:[^\[\]\n]|\[[^\[\]\n]*\])+\]\(https://[^\s)]+\)'
    return bool(re.match(pattern, text)) and not re.sub(pattern, '', text).strip()


def source_heading(value, title, channel):
    original_title = re.sub(r'[（(]修订版[）)]$', '', title or '')
    return bool(original_title and original_title in value) or (channel == 'trending' and value.startswith('📡'))


def render_blocks(blocks, assets, depth=0, *, channel=None, path=(), title=None):
    require(isinstance(blocks,list) and blocks and depth < 8, 'Invalid or too deeply nested article blocks')
    rendered = []
    text = []
    trend_open = False
    metadata_next = False
    for index, b in enumerate(blocks):
        require(isinstance(b,dict), 'Invalid block')
        kind = b.get('type')
        allowed = {'paragraph': {'type','text'}, 'heading': {'type','text','level'}, 'quote': {'type','text'}, 'code': {'type','text'}, 'list': {'type','items','ordered'}, 'image': {'type','src','alt','caption'}, 'details': {'type','summary','blocks'}, 'table': {'type','headers','rows'}}
        require(kind in allowed and set(b) <= allowed[kind], f'Unknown block fields: {kind}')
        anchor = 'section-' + '-'.join(map(str, path + (index,)))
        is_title = channel == 'trending' and kind == 'paragraph' and link_title(b.get('text', ''))
        if trend_open and (is_title or kind == 'heading'):
            rendered.append('</article>'); trend_open = False
        if is_title:
            rendered.append('<article class="trend-item">')
            trend_open = True
        if kind in {'paragraph','heading','quote','code'}:
            value = clean(b['text']); text.append(value)
            tag = {'paragraph':'p','heading':'h3' if depth else 'h2','quote':'blockquote','code':'pre'}[kind]
            if kind == 'heading' and 'level' in b:
                require(type(b['level']) is int and b['level'] in (2,3), 'Heading level must be 2 or 3')
                tag = 'h' + str(max(b['level'], 3 if depth else 2))
            attrs = f' id="{anchor}"' if kind == 'heading' else ''
            if kind == 'heading' and source_heading(value, title, channel):
                tag = 'p'; attrs = ' class="source-title"'
            elif is_title:
                tag = 'h3'; attrs = ' class="item-title"'
            elif metadata_next and trend_open and kind == 'paragraph':
                attrs = ' class="item-meta"'
            elif kind == 'paragraph' and len(value) < 320 and re.search(r'未逐声试听|本期没有运行|以下是提案，未执行|这是理想条件|核心理解：|关键前提是|本期边界', value):
                attrs = ' class="reading-note"'
            body = '<code>'+html.escape(value)+'</code>' if kind == 'code' else inline(value)
            rendered.append(f'<{tag}{attrs}>{body}</{tag}>')
        elif kind == 'list':
            require(isinstance(b['items'],list) and b['items'], 'Empty list')
            tag = 'ol' if b.get('ordered',False) else 'ul'
            rendered.append(f'<{tag}>'+''.join('<li>'+inline(x)+'</li>' for x in b['items'])+f'</{tag}>')
            text.extend(b['items'])
        elif kind == 'image':
            src = clean(b['src']); alt = clean(b['alt'])
            require(re.fullmatch(r'assets/[a-zA-Z0-9_./-]+\.(png|jpg|jpeg|webp|gif)',src) and '..' not in Path(src).parts, 'Image must be a local raster asset')
            image_path = assets / src.removeprefix('assets/')
            require(image_path.is_file() and not image_path.is_symlink(), f'Missing image: {src}')
            data = image_path.read_bytes()
            valid_image = data.startswith(b'\x89PNG\r\n\x1a\n') or data.startswith(b'\xff\xd8\xff') or data.startswith((b'GIF87a', b'GIF89a')) or (data.startswith(b'RIFF') and data[8:12] == b'WEBP')
            require(valid_image, f'Invalid raster image: {src}')
            caption = inline(b['caption']) if b.get('caption') else ''
            rendered.append(f'<figure><a class="image-link" href="../../{html.escape(src)}" aria-label="查看原图：{html.escape(alt,quote=True)}"><img src="../../{html.escape(src)}" alt="{html.escape(alt,quote=True)}" loading="lazy"></a><figcaption>{caption}<span class="reading-aid">点击图片查看原图 ↗</span></figcaption></figure>')
            text.append(alt)
        elif kind == 'details':
            summary = clean(b['summary'])
            body, childtext = render_blocks(b['blocks'],assets,depth+1,path=path+(index,))
            rendered.append('<details><summary>'+inline(summary)+'</summary>'+body+'</details>')
            text.extend([summary,childtext])
        elif kind == 'table':
            headers, rows = b['headers'], b['rows']
            require(isinstance(headers,list) and headers and isinstance(rows,list), 'Invalid table')
            require(all(isinstance(r,list) and len(r)==len(headers) for r in rows), 'Table width mismatch')
            rendered.append('<div class="table-wrap" tabindex="0" role="region" aria-label="可横向滚动的表格"><table><thead><tr>'+''.join('<th scope="col">'+inline(x)+'</th>' for x in headers)+'</tr></thead><tbody>'+''.join('<tr>'+''.join('<td>'+inline(x)+'</td>' for x in row)+'</tr>' for row in rows)+'</tbody></table></div>')
            text.extend(headers + [x for row in rows for x in row])
        metadata_next = is_title
    if trend_open:
        rendered.append('</article>')
    return '\n'.join(rendered), '\n'.join(text)

def load_articles(root, public=False):
    records=[]; ids=set(); identities=set(); fingerprints=set()
    for file in sorted((root/'content/articles').glob('*.json')):
        a=json.loads(file.read_text())
        require(set(a)==TOP_KEYS, f'{file.name}: missing or unknown fields')
        require(re.fullmatch('[a-z0-9]+(?:-[a-z0-9]+)*',a['id']) and file.stem==a['id'], 'ID must match filename')
        require(a['id'] not in ids,'Duplicate ID'); ids.add(a['id'])
        require(type(a['revision']) is int and a['revision']>=1,'Invalid revision')
        require(type(a['public_reviewed']) is bool,'Invalid public review state')
        require(not public or a['public_reviewed'],f'{a["id"]}: public review required')
        require(re.fullmatch(r'\d{4}-\d{2}-\d{2}',a['date']) is not None,'Invalid date')
        date.fromisoformat(a['date'])
        require(a['channel'] in CHANNELS,'Unknown channel')
        for key in ['title','summary','series']: clean(a[key])
        require(isinstance(a['topics'],list) and a['topics'],'Missing topics')
        for topic in a['topics']: clean(topic)
        identity=(a['date'],a['channel'],a['series'],a['title'].strip())
        require(identity not in identities,'Duplicate article'); identities.add(identity)
        a['_body'],a['_text']=render_blocks(a['blocks'],root/'content/assets',channel=a['channel'],title=a['title'])
        fp=hashlib.sha256(json.dumps(a['blocks'],ensure_ascii=False,sort_keys=True).encode()).hexdigest()
        require(fp not in fingerprints,'Duplicate article body'); fingerprints.add(fp)
        require(isinstance(a['sources'],list) and a['sources'],'Sources are required')
        for s in a['sources']:
            require(set(s)=={'title','url'},'Invalid source fields'); clean(s['title']); url(s['url'])
        records.append(a)
    require(not public or records,'Refusing to publish an empty archive')
    return sorted(records,key=lambda a:(a['date'],a['id']),reverse=True)

def shell(title,body,prefix='./',catalog=None):
    e=html.escape
    coverage = (f'{catalog["start"]} — {catalog["end"]} · {catalog["articles_count"]} 篇归档' if catalog and catalog['articles_count'] else '阅读归档')
    return f'''<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><meta name="color-scheme" content="light"><meta name="description" content="Dots Trending 与每周探索的完整阅读归档"><title>{e(title)} · Dots Exploration</title><link rel="stylesheet" href="{prefix}style.css"></head><body><a class="skip" href="#main">跳到内容</a><header class="site-header"><a class="brand" href="{prefix}index.html"><span class="mark">D<span>•</span></span> Dots <small>Exploration</small></a><nav aria-label="主导航"><a href="{prefix}trending/index.html">每日 Trending</a><a href="{prefix}exploration/index.html">每周探索</a></nav></header>{body}<footer>Dots Exploration <span>持续发现，慢慢读懂。</span><p>{coverage} · 北京时间（UTC+8）<br>内容为归档当日快照；不代表今天重新核实。仅收录已有公开文章。</p></footer></body></html>'''

def listing(records,channel=None):
    selected=[a for a in records if not channel or a['channel']==channel]
    prefix='../' if channel else './'
    title=CHANNELS.get(channel,'让好奇心，有迹可循。')
    cards=[]
    for a in selected:
        e=html.escape
        cards.append(f'<article class="card" data-id="{a["id"]}"><div class="eyebrow"><time datetime="{a["date"]}">{a["date"]}</time> <span>{e(a["series"])}</span></div><h2><a href="{prefix}articles/{a["id"]}/index.html">{e(a["title"])}</a></h2><p>{e(a["summary"])}</p><div class="tags">'+''.join('<span>'+e(t)+'</span>' for t in a['topics'])+'</div></article>')
    options=''.join(f'<option value="{html.escape(s,quote=True)}">{html.escape(s)}</option>' for s in sorted({a['series'] for a in selected}))
    entrances='' if channel else '<div class="entrances"><a href="trending/index.html"><b>01 / 每日 Trending</b><span>追踪新动向，连接一手来源 ↗</span></a><a href="exploration/index.html"><b>02 / 每周探索</b><span>按系列深入阅读，留下思考 ↗</span></a></div>'
    empty='<div class="empty">本地框架预览 · 真实公开文章尚未导入，暂不发布。</div>' if not selected else ''
    return shell(title,f'''<main id="main"><section class="hero"><p class="eyebrow">DOTS / THE READING ARCHIVE</p><h1>{title}</h1><p class="lead">每天的新发现，每周的深探索。<br>把值得读的内容，留在一个安静的地方。</p>{entrances}</section><section aria-label="文章目录" class="archive"><div class="section-title"><h2>阅读归档</h2><p id="count" aria-live="polite">{len(selected)} 篇文章</p></div><form class="filters" role="search"><label>搜索主题与全文<input type="search" id="q" placeholder="标题、主题、知识点…" autocomplete="off"></label><label>栏目系列<select id="series"><option value="">全部系列</option>{options}</select></label><label>起始日期<input type="date" id="from"></label><label>结束日期<input type="date" id="to"></label><button type="reset">重置</button></form><p id="filter-error" role="status"></p><noscript><p>启用 JavaScript 可使用搜索与筛选；完整目录和文章仍可直接阅读。</p></noscript><div class="cards">{''.join(cards)}</div>{empty}<p id="no-results" hidden>没有匹配的文章。试试其他关键词或日期。</p></section></main><script src="{prefix}search-index.js" defer></script><script src="{prefix}app.js" defer></script>''',prefix,archive_catalog(records))

def walk_blocks(blocks):
    for block in blocks:
        yield block
        if block['type'] == 'details':
            yield from walk_blocks(block['blocks'])


def archive_catalog(records):
    entries = []
    assets = set()
    for a in records:
        blocks = list(walk_blocks(a['blocks']))
        images = [b['src'] for b in blocks if b['type'] == 'image']
        assets.update(images)
        entries.append({k:a[k] for k in ('id','date','channel','series','revision')} | {
            'images': images,
            'disclosures': sum(b['type']=='details' for b in blocks),
            'trending_items': sum(b['type']=='paragraph' and link_title(b['text']) for b in a['blocks']) if a['channel']=='trending' else 0,
        })
    dates = sorted(a['date'] for a in records)
    return {'start':dates[0] if dates else None, 'end':dates[-1] if dates else None,
            'articles_count':len(records), 'images_count':len(assets),
            'channels':{c:sum(a['channel']==c for a in records) for c in CHANNELS},
            'trending_items':sum(a['trending_items'] for a in entries), 'articles':entries}


def contents_nav(a):
    # Never index nested solution headings or disclosure contents in the opening TOC.
    headings = [(i,b['text']) for i,b in enumerate(a['blocks']) if b['type']=='heading'
                and not source_heading(b['text'], a['title'], a['channel']) and b.get('level',2)==2 and not re.search(r'答案|解答|提示', b['text'])]
    if len(headings) < 2:
        return ''
    links = ''.join(f'<li><a href="#section-{i}">{html.escape(label)}</a></li>' for i,label in headings)
    return '<nav class="contents" aria-label="本文目录"><span>本文目录</span><ol>'+links+'</ol></nav>'


def build(root=ROOT, output=None, public=False):
    records=load_articles(root,public)
    catalog=archive_catalog(records)
    output=output or root/'site'
    output.mkdir(parents=True,exist_ok=True)
    (output/'index.html').write_text(listing(records))
    for channel in CHANNELS:
        (output/channel).mkdir(exist_ok=True)
        (output/channel/'index.html').write_text(listing(records,channel))
    (output/'catalog.json').write_text(json.dumps(catalog,ensure_ascii=False,sort_keys=True,indent=2)+'\n')
    for a in records:
        folder=output/'articles'/a['id']; folder.mkdir(parents=True,exist_ok=True)
        source=''.join(f'<li><a href="{html.escape(s["url"],quote=True)}" rel="noreferrer">{html.escape(s["title"])}</a></li>' for s in a['sources'])
        toc=contents_nav(a)
        summary = '<p class="lead">'+html.escape(a['summary'])+'</p>' if a['channel']=='trending' else ''
        body=f'<main id="main" class="reading {a["channel"]}"><a class="back" href="../../{a["channel"]}/index.html">← {CHANNELS[a["channel"]]}</a><article><header class="article-header"><p class="eyebrow">{html.escape(a["series"])} / <time datetime="{a["date"]}">{a["date"]}</time> / 修订 {a["revision"]}</p><h1>{html.escape(a["title"])}</h1>{summary}</header><div class="reading-layout">{toc}<div class="prose"><div class="article-content">{a["_body"]}</div><section class="sources"><h2>来源与延伸阅读</h2><ol>{source}</ol></section></div></div></article><a class="back" href="#main">回到文章顶部 ↑</a></main>'
        (folder/'index.html').write_text(shell(a['title'],body,'../../',catalog))
    for name in ['style.css','app.js']: shutil.copyfile(root/'web'/name,output/name)
    # Only referenced assets enter the public build; staging leftovers cannot leak.
    for a in records:
        for src in re.findall(r'src="../../(assets/[^"<>]+)"',a['_body']):
            target=output/src; target.parent.mkdir(parents=True,exist_ok=True)
            shutil.copyfile(root/'content'/src,target)
    search=[{k:a[k] for k in ['id','date','channel','series','title','summary','topics']} | {'text':a['_text']} for a in records]
    (output/'search-index.js').write_text('window.DOTS_INDEX = '+json.dumps(search,ensure_ascii=False,sort_keys=True).replace('<','\\u003c')+';\n')
    (output/'.nojekyll').write_text('')
    manifest={str(p.relative_to(output)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(output.rglob('*')) if p.is_file() and p.name!='build-manifest.json'}
    (output/'build-manifest.json').write_text(json.dumps(manifest,sort_keys=True,indent=2)+'\n')
    return records

def main():
    parser=argparse.ArgumentParser(); parser.add_argument('--check',action='store_true'); parser.add_argument('--public',action='store_true'); args=parser.parse_args()
    with tempfile.TemporaryDirectory() as temp:
        out=Path(temp)/'site'; records=build(ROOT,out,args.public)
        if args.check:
            expected={str(p.relative_to(out)):p.read_bytes() for p in out.rglob('*') if p.is_file()}
            current={str(p.relative_to(ROOT/'site')):p.read_bytes() for p in (ROOT/'site').rglob('*') if p.is_file()}
            require(expected==current,'Generated site is stale: run python3 scripts/generate.py')
        else:
            if (ROOT/'site').exists(): shutil.rmtree(ROOT/'site')
            shutil.copytree(out,ROOT/'site')
    print(f'Validated {len(records)} articles; '+('public' if args.public else 'local')+' build '+('matches' if args.check else 'generated'))

if __name__=='__main__': main()

#!/usr/bin/env python3
"""Check generated local links, asset containment, and public source boundaries."""
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlsplit, unquote
from generate import ROOT, PRIVATE, require

class Links(HTMLParser):
    def __init__(self):
        super().__init__(); self.links=[]; self.ids=set()
    def handle_starttag(self,tag,attrs):
        attrs=dict(attrs)
        if 'id' in attrs: self.ids.add(attrs['id'])
        for attr in ('href','src'):
            if attr in attrs: self.links.append((tag,attr,attrs[attr]))
        require(not any(k.startswith('on') for k in attrs),'Inline handlers forbidden')
        if tag=='script': require('src' in attrs,'Inline scripts forbidden')

def verify(root=ROOT):
    site=(root/'site').resolve(); count=0
    for p in site.rglob('*'):
        require(not p.is_symlink(),'No symlinks in output')
        if p.suffix not in {'.html','.js','.css','.json'}: continue
        value=p.read_text()
        require(not PRIVATE.search(value),'Potential sensitive string in output')
        if p.suffix!='.html': continue
        parser=Links(); parser.feed(value)
        for tag,attr,link in parser.links:
            parts=urlsplit(link)
            if parts.scheme:
                require(parts.scheme=='https' and attr=='href' and tag=='a','External executable or image resource forbidden')
                continue
            require(not parts.netloc,'Protocol-relative resources forbidden')
            target=(p.parent/unquote(parts.path)).resolve() if parts.path else p.resolve()
            require(target.is_relative_to(site),'Link escapes site')
            require(target.is_file(),f'Broken local link: {p.relative_to(site)} -> {link}')
            if parts.fragment and target.suffix=='.html':
                target_parser=Links(); target_parser.feed(target.read_text())
                require(unquote(parts.fragment) in target_parser.ids,f'Broken fragment: {link}')
            count+=1
    print(f'Verified {count} local links and asset references')

if __name__=='__main__': verify()

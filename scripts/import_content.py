#!/usr/bin/env python3
"""Import an already reviewed public package with articles/ and assets/."""
import argparse
import json
import re
import shutil
import tempfile
from pathlib import Path
from generate import ROOT, load_articles, require


def import_package(package, root=ROOT):
    package = Path(package).resolve()
    require((package/'articles').is_dir(), 'Package must contain articles/')
    files = sorted((package/'articles').glob('*.json'))
    require(files, 'No article JSON files found')
    with tempfile.TemporaryDirectory(dir=root) as tmp:
        stage = Path(tmp)
        shutil.copytree(root/'content', stage/'content')
        for source in files:
            require(not source.is_symlink(), 'Symlinks are not allowed')
            new = json.loads(source.read_text())
            target = stage/'content/articles'/source.name
            if target.exists():
                old = json.loads(target.read_text())
                if new == old:
                    continue
                require(new.get('id') == old.get('id'), 'Cannot change a stable ID')
                require(new.get('revision') == old.get('revision')+1, 'Changed content requires exactly one revision increment')
                require(all(new.get(k) == old.get(k) for k in ('date','channel','series')), 'Date, channel and series are immutable identity fields')
            else:
                require(new.get('revision') == 1, 'New article must start at revision 1')
            shutil.copyfile(source,target)
        # Resolve image references only; never copy an entire unreviewed package.
        for path in (stage/'content/articles').glob('*.json'):
            value=json.loads(path.read_text())
            def images(blocks):
                for b in blocks:
                    if b.get('type')=='image': yield b['src']
                    if b.get('type')=='details': yield from images(b['blocks'])
            for src in images(value.get('blocks',[])):
                require(re.fullmatch(r'assets/[A-Za-z0-9_./-]+\.(png|jpg|jpeg|gif|webp)',src) and '..' not in Path(src).parts, 'Unsafe asset path')
                incoming=package/src; destination=stage/'content'/src
                if incoming.is_file():
                    require(not incoming.is_symlink() and package in incoming.resolve().parents,'Unsafe asset symlink')
                    if destination.exists():
                        require(destination.read_bytes()==incoming.read_bytes(),'Assets are immutable: use a new filename for revised images')
                    else:
                        destination.parent.mkdir(parents=True,exist_ok=True)
                        shutil.copyfile(incoming,destination)
        records = load_articles(stage, public=True)
        # Commit the validated source directory as one local replacement.
        backup=stage/'previous-content'
        (root/'content').rename(backup)
        try:
            (stage/'content').rename(root/'content')
        except BaseException:
            backup.rename(root/'content')
            raise
        return len(records)

if __name__=='__main__':
    parser=argparse.ArgumentParser(); parser.add_argument('package',type=Path); args=parser.parse_args()
    print(f'Imported package; {import_package(args.package)} validated articles total')

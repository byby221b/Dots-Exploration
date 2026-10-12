#!/usr/bin/env python3
"""Read-only gate for one reviewed, atomic commit before a normal main push."""
import argparse
import json
import re
import subprocess
import tempfile
from pathlib import Path

from generate import ROOT, build, load_articles, require, walk_blocks
from verify import verify

NOREPLY = 'byby221b@users.noreply.github.com'
REMOTES = {'https://github.com/byby221b/Dots-Exploration.git',
           'git@github.com:byby221b/Dots-Exploration.git'}
MAINTENANCE = re.compile(r'(?:README\.md|(?:scripts|tests)/[a-z_]+\.py|docs/[a-z0-9-]+\.md|web/(?:style\.css|app\.js))')
ASSET = re.compile(r'assets/[A-Za-z0-9_./-]+\.(?:png|jpg|jpeg|webp|gif)')


def git(root, *args):
    return subprocess.check_output(['git', *args], cwd=root, stderr=subprocess.PIPE).decode().strip()


def inventory(folder):
    result = {}
    for path in folder.rglob('*'):
        require(not path.is_symlink(), 'Symlinks are forbidden in release files')
        if path.is_file():
            result[path.relative_to(folder).as_posix()] = path.read_bytes()
    return result


def check_release(root, base, article_ids=(), assets=(), maintenance_paths=(), *, remotes=REMOTES):
    root = Path(root).resolve()
    require(re.fullmatch(r'[0-9a-f]{40}', base), 'Supply the exact reviewed main SHA')
    require(not git(root, 'status', '--porcelain=v1', '--untracked-files=all'),
            'Commit the complete reviewed change; worktree/index/untracked files must be clean')
    fetch_urls = git(root, 'remote', 'get-url', '--all', 'origin').splitlines()
    push_urls = git(root, 'remote', 'get-url', '--push', '--all', 'origin').splitlines()
    require(len(fetch_urls) == len(push_urls) == 1 and fetch_urls[0] in remotes and push_urls[0] in remotes,
            'Origin fetch and push must both target Dots-Exploration')
    head = git(root, 'rev-parse', 'HEAD')
    require(git(root, 'show', '-s', '--format=%P', head) == base,
            'Release must be exactly one commit directly on the reviewed main SHA')
    identities = git(root, 'show', '-s', '--format=%ae%x00%ce', head).split('\0')
    require(identities == [NOREPLY, NOREPLY],
            'Actual commit author and committer must both use the verified GitHub noreply')
    # Check the commit object, not merely current config or the working directory.
    tree_modes = git(root, 'ls-tree', '-r', head).splitlines()
    require(all(line.startswith(('100644 ', '100755 ')) for line in tree_modes),
            'Symlinks and submodules are forbidden in release trees')
    ids = set(article_ids)
    require(len(ids) == len(article_ids), 'Duplicate article IDs in release scope')
    require(all(re.fullmatch(r'[a-z0-9]+(?:-[a-z0-9]+)*', ident) for ident in ids), 'Invalid scoped article ID')
    asset_set = set(assets)
    require(len(asset_set) == len(assets) and all(ASSET.fullmatch(p) and '..' not in Path(p).parts for p in assets),
            'Invalid or duplicate scoped asset path')
    maintenance = set(maintenance_paths)
    require(len(maintenance) == len(maintenance_paths) and all(MAINTENANCE.fullmatch(p) for p in maintenance),
            'Maintenance scope accepts only explicit code/test/docs/style paths')
    require(not (maintenance and (ids or assets)), 'Keep maintenance and content releases separate')
    require(ids or maintenance, 'Declare the reviewed content or maintenance scope')
    changed = set(filter(None, git(root, 'diff', '--name-only', '--no-renames', '-z', base, head).split('\0')))
    expected = {'content/articles/' + ident + '.json' for ident in ids} | {'content/' + p for p in assets} | maintenance
    nongenerated = {p for p in changed if not p.startswith('site/')}
    require(nongenerated == expected, 'Changed source paths differ from the explicitly reviewed scope')
    require(not git(root, 'diff', '--name-only', '--diff-filter=D', base, head, '--', 'content'),
            'Daily publishing cannot delete canonical articles or assets')
    # Re-run the importer contract against the base, including exact revision steps.
    base_files = set(git(root, 'ls-tree', '-r', '--name-only', base).splitlines())
    for ident in ids:
        path = 'content/articles/' + ident + '.json'
        current = json.loads((root / path).read_text())
        if path in base_files:
            previous = json.loads(git(root, 'show', base + ':' + path))
            require({k:v for k,v in current.items() if k != 'revision'} !=
                    {k:v for k,v in previous.items() if k != 'revision'},
                    'Identical content must not create a new release')
            require(current['revision'] == previous['revision'] + 1, 'Changed article requires exactly one revision increment')
            require(all(current[k] == previous[k] for k in ('id', 'date', 'channel', 'series')), 'Stable article identity changed')
        else:
            require(current['revision'] == 1, 'New article must start at revision 1')
    for path in assets:
        require('content/' + path not in base_files, 'Existing image bytes are immutable; use a new filename')
    records = load_articles(root, public=True)
    referenced = {b['src'] for a in records for b in walk_blocks(a['blocks']) if b['type'] == 'image'}
    require(asset_set <= referenced, 'New assets must be referenced by reviewed articles')
    with tempfile.TemporaryDirectory() as temporary:
        generated = Path(temporary) / 'site'
        build(root, generated, public=True)
        require(inventory(generated) == inventory(root / 'site'), 'Generated output has drifted; rebuild and review before committing')
    verify(root)
    # Last network check; a subsequent ordinary push still rejects concurrent main updates.
    remote = git(root, 'ls-remote', '--refs', 'origin', 'refs/heads/main').split()
    require(remote == [base, 'refs/heads/main'], 'Remote main changed; stop and reconcile, never force push')
    return {'commit': head, 'base': base, 'author_committer_noreply': True,
            'articles': len(records), 'changed_paths': sorted(changed), 'ready_for_normal_push': True}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base', required=True, help='Exact main SHA recorded before this release')
    parser.add_argument('--article-id', action='append', default=[], help='Changed article ID; repeat for a reviewed batch')
    parser.add_argument('--asset', action='append', default=[], help='New assets/... path; repeat per image')
    parser.add_argument('--maintenance-path', action='append', default=[], help='Explicit changed code/test/docs path, separate from content')
    args = parser.parse_args()
    try:
        report = check_release(ROOT, args.base, args.article_id, args.asset, args.maintenance_path)
    except (ValueError, subprocess.CalledProcessError) as error:
        # Never echo Git identity, credentials, raw private input, or subprocess stderr.
        parser.exit(1, 'Publication blocked: ' + (str(error) if isinstance(error, ValueError) else 'Git check failed') + '\n')
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()

"""Publication regressions using isolated local Git repos; no network or credentials."""
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

from test_archive import setup
from generate import build
from prepublish import check_release, NOREPLY


class PrepublishTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / 'repo'
        self.root.mkdir()
        self.remote = Path(self.tmp.name) / 'remote.git'
        self.env = os.environ.copy()
        self.env.update(GIT_AUTHOR_NAME='Publication QA', GIT_COMMITTER_NAME='Publication QA',
                        GIT_AUTHOR_EMAIL=NOREPLY, GIT_COMMITTER_EMAIL=NOREPLY,
                        GIT_CONFIG_NOSYSTEM='1', GIT_CONFIG_GLOBAL=os.devnull)
        self.git('init', '-q')
        subprocess.run(['git', 'init', '-q', '--bare', str(self.remote)], env=self.env, check=True)
        self.git('remote', 'add', 'origin', str(self.remote))
        setup(self.root)
        build(self.root, public=True)
        self.commit('base')
        self.base = self.git('rev-parse', 'HEAD')
        self.git('push', '-q', 'origin', 'HEAD:refs/heads/main')
        self.path = self.root / 'content/articles/qa-article.json'
        article = json.loads(self.path.read_text())
        article.update(summary='Reviewed revision', revision=2)
        self.path.write_text(json.dumps(article))
        build(self.root, public=True)
        self.commit('release')

    def tearDown(self):
        self.tmp.cleanup()

    def git(self, *args):
        return subprocess.check_output(['git', *args], cwd=self.root, env=self.env, stderr=subprocess.PIPE).decode().strip()

    def commit(self, message):
        self.git('add', '.')
        self.git('commit', '-q', '-m', message)

    def check(self, **kwargs):
        return check_release(self.root, self.base, remotes={str(self.remote)}, **({'article_ids':['qa-article']} | kwargs))

    def test_valid_content_release(self):
        self.assertTrue(self.check()['ready_for_normal_push'])

    def test_rejects_actual_author_or_committer_even_with_correct_config(self):
        for field in ('GIT_AUTHOR_EMAIL', 'GIT_COMMITTER_EMAIL'):
            with self.subTest(field=field):
                self.env[field] = 'private' + '@example.test'
                self.git('commit', '-q', '--amend', '--no-edit', '--reset-author')
                self.env[field] = NOREPLY
                self.git('config', 'user.email', NOREPLY)
                with self.assertRaisesRegex(ValueError, 'Actual commit'): self.check()
                self.git('commit', '-q', '--amend', '--no-edit', '--reset-author')

    def test_rejects_dirty_staged_and_untracked(self):
        for stage in (False, True):
            self.path.write_text(self.path.read_text() + '\n')
            if stage: self.git('add', str(self.path))
            with self.assertRaisesRegex(ValueError, 'clean'): self.check()
            self.git('restore', '--staged', '--worktree', str(self.path))
        (self.root/'unreviewed.txt').write_text('private input stays outside repository')
        with self.assertRaisesRegex(ValueError, 'clean'): self.check()

    def test_rejects_wrong_scope_and_private_extra_file(self):
        with self.assertRaisesRegex(ValueError, 'scope'): self.check(article_ids=['other'])
        (self.root/'raw-message.txt').write_text('unreviewed input')
        self.git('add', '.');self.git('commit', '-q', '--amend', '--no-edit')
        with self.assertRaisesRegex(ValueError, 'scope'): self.check()

    def test_rejects_generated_drift(self):
        (self.root/'site/index.html').write_text('unexpected generated output')
        self.git('add', '.');self.git('commit', '-q', '--amend', '--no-edit')
        with self.assertRaisesRegex(ValueError, 'drifted'): self.check()

    def test_rejects_remote_change(self):
        self.git('push', '-q', 'origin', 'HEAD:refs/heads/main')
        with self.assertRaisesRegex(ValueError, 'Remote main changed'): self.check()

    def test_rejects_extra_commit_or_wrong_remote(self):
        self.git('remote', 'set-url', '--push', 'origin', '/not-the-reviewed-repository')
        with self.assertRaisesRegex(ValueError, 'Origin'): self.check()
        self.git('remote', 'set-url', '--push', 'origin', str(self.remote))
        self.git('commit', '-q', '--allow-empty', '-m', 'unreviewed extra commit')
        with self.assertRaisesRegex(ValueError, 'exactly one commit'): self.check()

    def test_rejects_additional_push_destination(self):
        self.git('config', '--add', 'remote.origin.pushurl', str(self.remote))
        self.git('config', '--add', 'remote.origin.pushurl', '/unreviewed-destination')
        with self.assertRaisesRegex(ValueError, 'Origin'): self.check()

    def test_rejects_unreferenced_asset(self):
        (self.root/'content/assets/orphan.png').write_bytes((self.root/'content/assets/qa.png').read_bytes())
        self.git('add', '.');self.git('commit', '-q', '--amend', '--no-edit')
        with self.assertRaisesRegex(ValueError, 'referenced'): self.check(assets=['assets/orphan.png'])

    def test_rejects_skipped_revision(self):
        a=json.loads(self.path.read_text());a['revision']=4;self.path.write_text(json.dumps(a))
        build(self.root, public=True);self.git('add', '.');self.git('commit', '-q', '--amend', '--no-edit')
        with self.assertRaisesRegex(ValueError, 'exactly one revision'): self.check()

    def test_rejects_revision_only_and_changed_existing_asset(self):
        a=json.loads(self.git('show',self.base+':content/articles/qa-article.json'))
        a['revision']=2;self.path.write_text(json.dumps(a))
        build(self.root, public=True);self.git('add', '.');self.git('commit', '-q', '--amend', '--no-edit')
        with self.assertRaisesRegex(ValueError, 'Identical content'): self.check()
        a['summary']='Reviewed change';self.path.write_text(json.dumps(a))
        image=self.root/'content/assets/qa.png';image.write_bytes(image.read_bytes()+b'changed')
        build(self.root, public=True);self.git('add', '.');self.git('commit', '-q', '--amend', '--no-edit')
        with self.assertRaisesRegex(ValueError, 'immutable'): self.check(assets=['assets/qa.png'])

    def test_maintenance_scope_is_explicit_and_separate(self):
        self.git('reset', '--hard', self.base)
        (self.root/'README.md').write_text('Reviewed maintenance')
        self.commit('maintenance')
        self.assertTrue(self.check(article_ids=[], maintenance_paths=['README.md'])['ready_for_normal_push'])
        with self.assertRaisesRegex(ValueError, 'separate'): self.check(maintenance_paths=['README.md'])
        with self.assertRaisesRegex(ValueError, 'Maintenance scope'): self.check(article_ids=[],maintenance_paths=['.github/workflows/daily.yml'])

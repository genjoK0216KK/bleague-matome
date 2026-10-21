"""公式ILの2成果を、後の工程が失敗した回でも保存する（10/22・独立QA差し戻し対応・未公開）。

1) save_il.py を一時的な git リポジトリ（公開先は bare リポジトリ）で動かし、失敗の組み合わせごとに
   公開されるファイルを確かめる。
2) update.yml の各ステップの実行条件（if）を GitHub Actions の規則どおりに評価し、失敗の組み合わせごとに
   どのステップが動き、ジョブが失敗のまま残るかを確かめる。
"""
import os
import re
import subprocess
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path

import yaml

from scripts import save_il

ROOT = Path(__file__).resolve().parents[1]
IL = ['injury.html', 'data/match_articles/injury.json']


def sh(cwd, *args):
    return subprocess.run(['git', *args], cwd=cwd, check=True, text=True, capture_output=True).stdout


@contextmanager
def chdir(path):
    old = os.getcwd(); os.chdir(path)
    try:
        yield
    finally:
        os.chdir(old)


class SaveIl(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        base = Path(self.temp.name)
        self.remote, self.repo = base / 'remote.git', base / 'work'
        sh(base, 'init', '-q', '--bare', '-b', 'main', str(self.remote))
        sh(base, 'clone', '-q', str(self.remote), str(self.repo))
        for k, v in (('user.name', 'bot'), ('user.email', 'bot@example.com')):
            sh(self.repo, 'config', k, v)
        (self.repo / 'data/match_articles').mkdir(parents=True)
        for name, text in (('injury.html', 'old il'), ('data/match_articles/injury.json', '{"status":"ok"}'),
                           ('index.html', 'old index'), ('news.html', 'old news'), ('articles.html', 'old list')):
            (self.repo / name).write_text(text)
        sh(self.repo, 'add', '-A'); sh(self.repo, 'commit', '-q', '-m', 'base'); sh(self.repo, 'push', '-q', 'origin', 'main')

    def remote_files(self):
        out = sh(self.repo, 'ls-remote', 'origin', 'refs/heads/main').split()[0]
        changed = sh(self.repo, 'diff', '--name-only', 'HEAD~1', out) if out else ''
        return sorted(changed.split())

    def published(self, path):
        return sh(self.remote, 'show', 'main:' + path)

    def run_save(self):
        with chdir(self.repo):
            return save_il.save()

    def test_later_step_failure_publishes_only_il(self):
        """ニュース成功→試合記事またはHTML生成が失敗：IL（成功分）だけ公開。途中の生成物は公開しない。"""
        (self.repo / 'injury.html').write_text('new il')
        (self.repo / 'data/match_articles/injury.json').write_text('{"status":"ok","new":1}')
        (self.repo / 'index.html').write_text('half built index')          # 失敗した工程の途中生成物
        (self.repo / 'new-untracked.html').write_text('partial')
        self.assertEqual(self.run_save(), 'saved')
        self.assertEqual(sh(self.remote, 'log', '-1', '--name-only', '--format=', 'main').split(), sorted(IL))
        self.assertEqual(self.published('injury.html'), 'new il')
        self.assertEqual(self.published('index.html'), 'old index')

    def test_il_failure_record_is_published_too(self):
        (self.repo / 'data/match_articles/injury.json').write_text('{"status":"failed","last_error":{"http_status":503}}')
        (self.repo / 'injury.html').write_text('未確認の表示')
        self.assertEqual(self.run_save(), 'saved')
        self.assertIn('"failed"', self.published('data/match_articles/injury.json'))

    def test_listing_refresh_failure_does_not_block_il(self):
        """ニュース失敗→記事一覧の補完が途中で失敗（一覧が途中まで書き換わった）でも IL は保存。"""
        (self.repo / 'articles.html').write_text('half refreshed list')
        (self.repo / 'injury.html').write_text('new il')
        self.assertEqual(self.run_save(), 'saved')
        self.assertEqual(self.published('articles.html'), 'old list')
        self.assertEqual(self.published('injury.html'), 'new il')

    def test_staged_other_files_are_not_committed(self):
        (self.repo / 'news.html').write_text('staged news'); sh(self.repo, 'add', 'news.html')
        (self.repo / 'injury.html').write_text('new il')
        self.run_save()
        self.assertEqual(self.published('news.html'), 'old news')

    def test_already_committed_by_normal_path_is_a_no_op(self):
        (self.repo / 'injury.html').write_text('new il'); (self.repo / 'index.html').write_text('new index')
        sh(self.repo, 'add', '-A'); sh(self.repo, 'commit', '-q', '-m', 'normal'); sh(self.repo, 'push', '-q', 'origin', 'main')
        head = sh(self.remote, 'rev-parse', 'main')
        self.assertEqual(self.run_save(), 'nothing')
        self.assertEqual(sh(self.remote, 'rev-parse', 'main'), head)

    def test_concurrent_push_is_rebased(self):
        other = Path(self.temp.name) / 'other'
        sh(self.temp.name, 'clone', '-q', str(self.remote), str(other))
        for k, v in (('user.name', 'x'), ('user.email', 'x@example.com')):
            sh(other, 'config', k, v)
        (other / 'news.html').write_text('newer news'); sh(other, 'commit', '-qam', 'other'); sh(other, 'push', '-q')
        (self.repo / 'injury.html').write_text('new il')
        self.run_save()
        self.assertEqual(self.published('news.html'), 'newer news')
        self.assertEqual(self.published('injury.html'), 'new il')


# ------------------------------------------------------- workflow conditions

def steps():
    wf = yaml.safe_load((ROOT / '.github/workflows/update.yml').read_text())
    return wf['jobs']['update']['steps']


def simulate(results, outputs=None):
    """results: step id/name -> 'success'|'failure'（実行された場合の結果）。
    GitHub の既定：if が無いステップは success() の時だけ動く。ジョブはどれかが失敗すると失敗。"""
    outputs = outputs or {}
    failed, ran, outcome = False, [], {}
    for st in steps():
        key = st.get('id') or st['name']
        cond = st.get('if', 'success()')
        expr = cond
        expr = re.sub(r"steps\.(\w+)\.outputs\.(\w+)", lambda m: repr(outputs.get(m.group(1), {}).get(m.group(2), '')), expr)
        expr = re.sub(r"steps\.(\w+)\.outcome", lambda m: repr(outcome.get(m.group(1), 'skipped')), expr)
        expr = (expr.replace('always()', 'True').replace('success()', str(not failed)).replace('failure()', str(failed))
                .replace('&&', ' and ').replace('||', ' or '))
        if not eval(expr):                                   # noqa: S307（自前の決まった式だけ）
            outcome[key] = 'skipped'
            continue
        result = results.get(key, 'success')
        outcome[key] = result
        ran.append(key)
        failed |= result == 'failure'
    return ran, failed


SAVE = '公式ILの結果を保存（後の工程が失敗した回も）'
CHECK = '公式ILの取得結果を確認'
NORMAL = '差分があればコミット'
FALLBACK = 'ニュース取得失敗時：公開済み記事を一覧に載せる（記事一覧のみ）'
FEATURES = '公式IL・23時に翌日プレビュー・3リーグ日付記事を更新'
BUILD = 'HTMLを生成'


class WorkflowConditions(unittest.TestCase):
    def test_each_failure_combination(self):
        cases = {
            'all ok':                ({}, True, False),
            'news fails':            ({'fetch': 'failure'}, True, True),
            'match features fail':   ({FEATURES: 'failure'}, True, True),
            'build fails':           ({BUILD: 'failure'}, True, True),
            'news fails + listing fallback fails': ({'fetch': 'failure', FALLBACK: 'failure'}, True, True),
            'normal commit fails':   ({NORMAL: 'failure'}, True, True),
        }
        for name, (results, save_runs, job_failed) in cases.items():
            with self.subTest(name):
                ran, failed = simulate(results, {'il': {'il_status': 'ok'}})
                self.assertEqual(SAVE in ran, save_runs)
                self.assertEqual(failed, job_failed)          # ニュース・試合・生成の失敗は失敗のまま
                self.assertNotIn(CHECK, ran)

    def test_fallback_and_normal_paths_are_unchanged(self):
        ran, _ = simulate({'fetch': 'failure'})
        self.assertIn(FALLBACK, ran); self.assertNotIn(FEATURES, ran); self.assertNotIn(NORMAL, ran)
        ran, _ = simulate({FEATURES: 'failure'})
        self.assertNotIn(FALLBACK, ran); self.assertNotIn(BUILD, ran); self.assertNotIn(NORMAL, ran)

    def test_il_failure_is_saved_and_reported(self):
        # 確認ステップ自身は必ず exit 1（run の内容を確認）
        self.assertIn('exit 1', next(s for s in steps() if s['name'] == CHECK)['run'])
        ran, failed = simulate({CHECK: 'failure'}, {'il': {'il_status': 'failed'}})
        self.assertIn(SAVE, ran); self.assertIn(CHECK, ran)
        self.assertTrue(failed)                               # IL 失敗は成功扱いにしない
        ran, failed = simulate({'fetch': 'failure', CHECK: 'failure'}, {'il': {'il_status': 'failed'}})
        self.assertIn(SAVE, ran); self.assertIn(CHECK, ran); self.assertTrue(failed)

    def test_save_step_is_last_but_check_and_stages_only_il(self):
        names = [s['name'] for s in steps()]
        self.assertEqual(names[-2:], [SAVE, CHECK])
        fallback = next(s for s in steps() if s['name'] == FALLBACK)['run']
        self.assertNotIn('injury', fallback)                  # 記事一覧の補完と IL の保存は独立
        self.assertEqual(save_il.FILES, IL)


if __name__ == '__main__':
    unittest.main()

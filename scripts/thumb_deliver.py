#!/usr/bin/env python3
"""Mac mini 側：生成済みサムネ（ready/<id>/）をサイトのリポジトリの専用ブランチ thumb-inbox へ渡す。

記事を作った時の画像生成（1記事1回）が終わった直後に実行する。新しい定期起動は作らない。
届いているかどうかは thumb-inbox ブランチそのものを、取り込まれたかどうかはサイトの台帳を見て判断するので、
前回の送信や取り込みの起動に失敗した分も、次に実行した時に自動的に送り直し・起動し直される。main には書かない。
サイト側（thumb-inbox への push で動く .github/workflows/thumbs.yml、および update.yml の取り込み工程＋
scripts/thumb_auto.py）が、いまの本文と同じ版の画像だけを採用する。

  python3 scripts/thumb_deliver.py --ready <outputs/basketball-thumbnail-automation/ready> \
      --state <work/basketball-thumbnail-automation/state.json> --repo <bleague-matome のローカル複製> [--dry-run]

- 渡すのは、記事ごとにいちばん新しく完成した ready_unpublished だけ（古い版は渡さない）。生成側の台帳の
  latest には頼らない（閲覧数だけの変化で保留になった job を指していても、完成済みの画像を引き継ぐ）。
- 同じ id で中身が違う画像は上書きしない（生成側の上書き禁止と同じ）。同じ中身なら何もしない＝再実行しても変更なし。
- 1回の実行で1コミット。push 先は thumb-inbox だけ（存在しなければ新しく作る）。
- push が他の送信と競合した時は、最新の thumb-inbox を取り直して最大3回やり直す。それでも失敗したら
  終了コード1で終わる（何も消さない。次の定期回で再送される）。
- 送れた時、または送ったのに取り込まれていないものがある時は、サイトの取り込み（.github/workflows/thumbs.yml）を
  既存の GitHub CLI（gh）の認証で起動する。起動できなくても送信は成功扱い（次に実行した時に起動し直す。
  通常更新 update.yml の取り込み工程でも拾われる）。新しい認証は作らない。
"""
import argparse
import hashlib
import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

BRANCH = 'thumb-inbox'
ATTEMPTS = 3
INGEST_WORKFLOW = 'thumbs.yml'


class DeliverError(RuntimeError):
    pass


def git(repo, *args, check=True):
    return subprocess.run(['git', '-C', str(repo), *args], check=check, text=True, capture_output=True)


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def candidates(ready, state=None):
    """記事ごとに「いちばん新しく完成した ready」（prepared_at が最大）だけを渡す。

    生成側の台帳（state.latest）は使わない（state は互換のために受け取るだけ）。閲覧数だけの変化で
    latest が保留（PV_ONLY_DUPLICATE）の job を指していても、その前に完成していた画像を作り直さずに
    引き継ぐため。同じ記事のより古い ready（後から作り直された版・検品で差し替えられた版）は選ばない。
    いちばん新しい ready が壊れていれば、古い版へは戻らずその記事を見送る。
    いまの本文に合うかどうかはサイト側（thumb_auto.check_bundle）が判定し、合わなければ既定の表示のまま。"""
    newest = {}
    for folder in sorted(Path(ready).iterdir()):
        manifest_path = folder / 'manifest.json'
        if not folder.is_dir() or not manifest_path.exists():
            continue
        m = json.loads(manifest_path.read_text())
        if m.get('status') != 'ready_unpublished' or not m.get('article_path') or not m.get('id'):
            continue
        prev = newest.get(m['article_path'])
        if prev is None or (m.get('prepared_at') or '') > (prev[1].get('prepared_at') or ''):
            newest[m['article_path']] = (folder, m, manifest_path)
    for folder, m, manifest_path in sorted(newest.values(), key=lambda x: x[1]['id']):
        image = folder / 'thumbnail.png'
        source = Path(m.get('source_file') or '')
        if not source.exists():
            source = folder / 'source.html'
        if not image.exists() or sha256(image) != m.get('image_sha256'):
            print(f'skip {folder.name}: 画像が manifest と一致しない（古い版へは戻らない）', file=sys.stderr)
            continue
        if not source.exists():
            print(f'skip {folder.name}: 固定原文 source.html が無い', file=sys.stderr)
            continue
        yield m['id'], {'manifest.json': manifest_path, 'thumbnail.png': image, 'source.html': source}


def awaiting_ingest(repo, remote='origin'):
    """thumb-inbox に届いているのに、サイトの台帳（main の data/thumbs/registry.json）にまだ無い id。
    送ったのに取り込みの起動に失敗した分を、次の呼び出しで起動し直すために使う。"""
    if git(repo, 'fetch', remote, BRANCH, check=False).returncode:
        return []
    ids = [Path(p).name for p in git(repo, 'ls-tree', '--name-only', 'FETCH_HEAD', 'inbox/', check=False).stdout.split()]
    if not ids or git(repo, 'fetch', remote, 'main', check=False).returncode:
        return ids
    shown = git(repo, 'show', 'FETCH_HEAD:data/thumbs/registry.json', check=False)
    try:
        seen = json.loads(shown.stdout).get('seen', {}) if shown.returncode == 0 else {}
    except ValueError:
        seen = {}
    return sorted(i for i in ids if i not in seen)


def _attempt(ready, repo, state, dry_run, remote):
    """1回分：最新の thumb-inbox に未着の画像を足して push する。戻り値 (added, conflicts, pushed)。"""
    exists = git(repo, 'fetch', remote, BRANCH, check=False).returncode == 0
    work = Path(tempfile.mkdtemp(prefix='thumb-inbox-'))
    # 初回（thumb-inbox がまだ無い）用の作業ブランチは毎回使い捨ての名前にする。push は HEAD を送るので名前は関係ない。
    # 固定名だと、初回の push に失敗した後の再試行で手元に残った同名ブランチとぶつかり、送り直せなくなる。
    scratch = BRANCH + '-work-' + work.name
    try:
        if exists:
            git(repo, 'worktree', 'add', '--detach', str(work), 'FETCH_HEAD')
        else:
            git(repo, 'worktree', 'add', '--detach', str(work))
            git(work, 'checkout', '--orphan', scratch)
            git(work, 'rm', '-rfq', '.', check=False)
            for p in work.iterdir():
                if p.name != '.git':
                    shutil.rmtree(p) if p.is_dir() else p.unlink()
        added, conflicts = [], []
        for mid, files in candidates(ready, state):
            target = work / 'inbox' / mid
            if target.exists():
                same = all((target / name).exists() and sha256(target / name) == sha256(src) for name, src in files.items())
                if not same:
                    conflicts.append(mid)
                continue
            target.mkdir(parents=True)
            for name, src in files.items():
                shutil.copyfile(src, target / name)
            added.append(mid)
        if not added or dry_run:
            return added, conflicts, False
        git(work, 'add', '--', 'inbox')
        git(work, 'commit', '-m', 'サムネ受け渡し: ' + ', '.join(added))
        push = git(work, 'push', remote, 'HEAD:refs/heads/' + BRANCH, check=False)
        if push.returncode:
            raise DeliverError(push.stderr.strip()[:300] or 'push failed')
        return added, conflicts, True
    finally:
        git(repo, 'worktree', 'remove', '--force', str(work), check=False)
        git(repo, 'branch', '-D', scratch, check=False)
        shutil.rmtree(work, ignore_errors=True)


def repo_slug(repo, remote='origin'):
    url = git(repo, 'remote', 'get-url', remote, check=False).stdout.strip()
    m = re.search(r'github\.com[:/]([^/]+/[^/]+?)(?:\.git)?$', url)
    return m.group(1) if m else None


def start_ingest(repo, remote='origin'):
    """サイト側の取り込みを起動する（ベストエフォート）。戻り値：起動できたか。"""
    slug = repo_slug(repo, remote)
    if not slug:
        print('取り込みの起動を省略（GitHub のリポジトリではない）', file=sys.stderr)
        return False
    try:
        out = subprocess.run(['gh', 'workflow', 'run', INGEST_WORKFLOW, '--repo', slug, '--ref', 'main'],
                             text=True, capture_output=True)
    except OSError as exc:
        print(f'取り込みを起動できません（gh が無い）。次の通常更新（update.yml）か次の送信で拾われます: {exc}', file=sys.stderr)
        return False
    if out.returncode:
        print('取り込みを起動できません。次の通常更新（update.yml）か次の送信で拾われます: ' + out.stderr.strip()[:200], file=sys.stderr)
        return False
    return True


def deliver(ready, repo, state=None, dry_run=False, remote='origin', dispatch=True):
    """未着の最新版を thumb-inbox へ送る。戻り値は今回追加した id の一覧。送れなければ DeliverError。"""
    repo = Path(repo)
    last = None
    for attempt in range(1, ATTEMPTS + 1):
        try:
            added, conflicts, pushed = _attempt(ready, repo, state, dry_run, remote)
        except DeliverError as exc:
            last = exc
            print(f'push に失敗（{attempt}/{ATTEMPTS}回目）。最新の thumb-inbox を取り直して再試行: {exc}', file=sys.stderr)
            continue
        if conflicts:
            print('上書きしない（同じ id で中身が違う）：' + ', '.join(conflicts), file=sys.stderr)
        # 今回送ったもの、または前に送ったのに取り込まれていないもの（起動の失敗など）があれば取り込みを起動する
        waiting = [] if dry_run or not dispatch else awaiting_ingest(repo, remote)
        started = start_ingest(repo, remote) if dispatch and not dry_run and (pushed or waiting) else False
        print(json.dumps({'added': added, 'conflicts': conflicts, 'pushed': pushed, 'dry_run': dry_run,
                          'attempt': attempt, 'awaiting_ingest': waiting, 'ingest_started': started},
                         ensure_ascii=False))
        return added
    raise DeliverError(f'{ATTEMPTS}回とも push できませんでした（次の定期回で再送されます）: {last}')


def main():
    parser = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    parser.add_argument('--ready', required=True)
    parser.add_argument('--repo', required=True)
    parser.add_argument('--state', help='互換のため受け取るだけ（使わない。記事ごとの最新の ready を自分で選ぶ）')
    parser.add_argument('--dry-run', action='store_true')
    parser.add_argument('--no-dispatch', action='store_true', help='送信後にサイトの取り込みを起動しない')
    args = parser.parse_args()
    try:
        deliver(args.ready, args.repo, args.state, args.dry_run, dispatch=not args.no_dispatch)
    except DeliverError as exc:
        print(f'::error::{exc}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())

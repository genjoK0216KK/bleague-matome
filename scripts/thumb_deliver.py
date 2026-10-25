#!/usr/bin/env python3
"""Mac mini 側：生成済みサムネ（ready/<id>/）をサイトのリポジトリの専用ブランチ thumb-inbox へ渡す。

ChatGPT の自動生成（thumbnail_queue.py ready）の後に実行する想定。main には書かない。
サイト側（update.yml の「自動生成サムネを取り込み」＋ scripts/thumb_auto.py）が、いまの本文と同じ版の画像だけを採用する。

  python3 scripts/thumb_deliver.py --ready <outputs/basketball-thumbnail-automation/ready> \
      --state <work/basketball-thumbnail-automation/state.json> --repo <bleague-matome のローカル複製> [--dry-run]

- 渡すのは state.json の latest（記事ごとの最新版）にある ready_unpublished だけ（古い版は渡さない）。
- 同じ id で中身が違う画像は上書きしない（生成側の上書き禁止と同じ）。同じ中身なら何もしない＝再実行しても変更なし。
- 1回の実行で1コミット。push 先は thumb-inbox だけ（存在しなければ新しく作る）。
"""
import argparse
import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

BRANCH = 'thumb-inbox'


def git(repo, *args, check=True):
    return subprocess.run(['git', '-C', str(repo), *args], check=check, text=True, capture_output=True)


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def candidates(ready, state):
    latest = set((json.loads(Path(state).read_text()).get('latest') or {}).values()) if state else None
    for folder in sorted(Path(ready).iterdir()):
        manifest_path = folder / 'manifest.json'
        if not manifest_path.exists():
            continue
        m = json.loads(manifest_path.read_text())
        if m.get('status') != 'ready_unpublished' or (latest is not None and m.get('id') not in latest):
            continue
        image = folder / 'thumbnail.png'
        source = Path(m.get('source_file') or '')
        if not image.exists() or sha256(image) != m.get('image_sha256'):
            print(f'skip {folder.name}: 画像が manifest と一致しない', file=sys.stderr)
            continue
        if not source.exists():
            print(f'skip {folder.name}: 固定原文 source.html が無い', file=sys.stderr)
            continue
        yield m['id'], {'manifest.json': manifest_path, 'thumbnail.png': image, 'source.html': source}


def deliver(ready, repo, state=None, dry_run=False, remote='origin'):
    repo = Path(repo)
    exists = git(repo, 'fetch', remote, BRANCH, check=False).returncode == 0
    work = Path(tempfile.mkdtemp(prefix='thumb-inbox-'))
    try:
        if exists:
            git(repo, 'worktree', 'add', '--detach', str(work), 'FETCH_HEAD')
        else:
            git(repo, 'worktree', 'add', '--detach', str(work))
            git(work, 'checkout', '--orphan', BRANCH)
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
        if conflicts:
            print('上書きしない（同じ id で中身が違う）：' + ', '.join(conflicts), file=sys.stderr)
        if not added or dry_run:
            print(json.dumps({'added': added, 'conflicts': conflicts, 'pushed': False, 'dry_run': dry_run}, ensure_ascii=False))
            return added
        git(work, 'add', '--', 'inbox')
        git(work, 'commit', '-m', 'サムネ受け渡し: ' + ', '.join(added))
        git(work, 'push', remote, 'HEAD:refs/heads/' + BRANCH)
        print(json.dumps({'added': added, 'conflicts': conflicts, 'pushed': True}, ensure_ascii=False))
        return added
    finally:
        git(repo, 'worktree', 'remove', '--force', str(work), check=False)
        shutil.rmtree(work, ignore_errors=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    parser.add_argument('--ready', required=True)
    parser.add_argument('--repo', required=True)
    parser.add_argument('--state', help='生成側の state.json（latest の版だけ渡す）')
    parser.add_argument('--dry-run', action='store_true')
    args = parser.parse_args()
    deliver(args.ready, args.repo, args.state, args.dry_run)
    return 0


if __name__ == '__main__':
    sys.exit(main())

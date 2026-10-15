#!/usr/bin/env python3
"""Publish one generated commit, preserving concurrent editorial news HTML."""
import os
import re
import subprocess
import sys

NEWS = re.compile(r'news(?:-[1-9][0-9]*)?\.html\Z')


def git(*args, check=True):
    return subprocess.run(['git', *args], check=check, text=True,
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                          env={**os.environ, 'GIT_EDITOR': 'true'})


def rebase_latest(remote='origin', branch='main'):
    git('fetch', remote, branch)
    result = git('rebase', 'FETCH_HEAD', check=False)
    if result.returncode == 0:
        return
    paths = git('diff', '--name-only', '--diff-filter=U', '-z').stdout.split('\0')
    paths = [p for p in paths if p]
    if not paths or any(not NEWS.fullmatch(p) for p in paths):
        git('rebase', '--abort', check=False)
        raise RuntimeError('Non-news conflict or rebase failure; update was not published')
    # During rebase --ours is the upstream version, not our generated commit.
    for path in paths:
        exists = git('cat-file', '-e', 'HEAD:' + path, check=False).returncode == 0
        if exists:
            git('checkout', '--ours', '--', path)
            git('add', '--', path)
        else:
            git('rm', '--force', '--', path)
    print('Preserved concurrently published news: ' + ', '.join(paths), flush=True)
    operation = '--skip' if git('diff', '--cached', '--quiet', check=False).returncode == 0 else '--continue'
    result = git('rebase', operation, check=False)
    if result.returncode:
        git('rebase', '--abort', check=False)
        raise RuntimeError('Rebase continuation failed; update was not published')


def publish(remote='origin', branch='main', attempts=3):
    for _ in range(attempts):
        rebase_latest(remote, branch)
        if git('push', remote, 'HEAD:refs/heads/' + branch, check=False).returncode == 0:
            return
    raise RuntimeError('Push failed after bounded retries; no force push attempted')


if __name__ == '__main__':
    try:
        publish()
    except (RuntimeError, subprocess.CalledProcessError) as exc:
        print('::error::' + (str(exc) if isinstance(exc, RuntimeError) else 'Git operation failed; update was not published'))
        sys.exit(1)

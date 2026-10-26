#!/usr/bin/env python3
"""バスケまとめ：サムネの作業役を今すぐ止める（MINI-8）。

1. 停止の印（STOP）を置く（受け口は以後、作業役を起こさない）。
2. worker.pid の記録（PID・PGID・開始時刻・コマンド・置き場所）が、今動いているプロセスと全部一致した時だけ、
   そのプロセスグループに TERM を送る。古い worker.pid の PID が別のプロセスに再利用されていたら、何もしない。
3. 待っても残っていたら、もう一度同じ確かめ方をしてから KILL する。
   （先頭のプロセスが既に終わり、同じグループの子だけが残っている時は、そのグループ番号はメンバーがいる間は
   ほかに再利用されないので、そのまま KILL してよい）
使い方：/usr/bin/python3 thumb_stop.py [待つ秒数（既定5）]
Python 3.9（macOS 標準）の標準ライブラリだけで動く。
"""
import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

HOME = Path(os.environ.get('BASUKE_THUMB_HOME', str(Path.home() / 'Library/Application Support/basuke-thumb-hook')))


def ps_field(pid, field):
    out = subprocess.run(['/bin/ps', '-p', str(pid), '-o', field + '='], capture_output=True, text=True, timeout=10)
    return out.stdout.strip() if out.returncode == 0 else ''


def members(pgid):
    """そのグループで生きている（ゾンビでない）プロセスの PID。"""
    out = subprocess.run(['/bin/ps', '-A', '-o', 'pid=,pgid=,stat='], capture_output=True, text=True, timeout=10)
    alive = []
    for line in out.stdout.splitlines():
        parts = line.split()
        if len(parts) >= 3 and parts[1] == str(pgid) and not parts[2].startswith('Z'):
            alive.append(int(parts[0]))
    return alive


def same(rec):
    """記録が、今動いているあの作業役そのものか（全部一致した時だけ True）。"""
    try:
        pid = int(rec['pid'])
        if pid <= 1 or int(rec['pgid']) != pid or rec.get('home') != str(HOME):
            return False
        if pid not in members(pid) or os.getpgid(pid) != pid:
            return False
        lstart, command = ps_field(pid, 'lstart'), ps_field(pid, 'command')
        return bool(lstart) and lstart == rec.get('lstart') and bool(command) and command == rec.get('command')
    except (KeyError, TypeError, ValueError, OSError, subprocess.TimeoutExpired):
        return False


def wait_gone(pgid, seconds):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        if not members(pgid):
            return True
        time.sleep(0.2)
    return not members(pgid)


def main(wait=5.0):
    HOME.mkdir(parents=True, exist_ok=True)
    (HOME / 'STOP').write_text(time.strftime('%Y-%m-%dT%H:%M:%S'))
    print('停止の印（STOP）を置きました')
    try:
        rec = json.loads((HOME / 'worker.pid').read_text(encoding='utf-8'))
    except (OSError, ValueError):
        rec = None
    if not isinstance(rec, dict) or not same(rec):
        print('動いている作業役はありません（worker.pid が無いか、別のプロセスを指しているので何も止めません）')
        return 0
    pid = int(rec['pid'])
    os.killpg(pid, signal.SIGTERM)
    if wait_gone(pid, wait):
        print('止まりました（作業役とその子プロセス）')
        return 0
    if pid in members(pid) and not same(rec):            # 追い打ちの前に、もう一度確かめる
        print('先頭のプロセスが別のものに変わったため、KILL しません。もう一度この手順を実行してください')
        return 1
    try:
        os.killpg(pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    if wait_gone(pid, wait):
        print('止まりました（KILL）')
        return 0
    print('まだ残っています：PID ' + ' '.join(map(str, members(pid))))
    return 1


if __name__ == '__main__':
    sys.exit(main(float(sys.argv[1]) if len(sys.argv) > 1 else 5.0))

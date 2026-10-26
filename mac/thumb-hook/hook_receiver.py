#!/usr/bin/env python3
"""バスケまとめ：記事ができたら Mac mini でその場でサムネを作るための受け口（MINI-8、本人 10/27 推奨案を選択）。

流れ：GitHub の Webhook（push）→ Tailscale Funnel → この受け口（127.0.0.1 だけで待ち受け）→ 作業役（thumb_worker.py）。

- 署名（X-Hub-Signature-256、ASCII の sha256=<16進64桁>）を、キーチェーンの合言葉で HMAC-SHA256 照合する。
  署名なし・形式違い・不一致は 401。回数の枠は署名の後で数える（署名の無い大量送信で正規の通知を締め出させない）。
- 読み取りは10秒で時間切れ、同時に処理する接続は8本まで（超えたら 503）、中身は 5MB まで。
- 届いた中身は「依頼の台帳を見に行く合図」としてだけ使う。記事本文や指示は一切読まない。作業役が GitHub から
  台帳と固定版の記事を自分で取りに行くので、合言葉が漏れても「main に既にある依頼を処理させる」以上はできない。
- 同じ通知（X-GitHub-Delivery が同じ）は1回だけ数える。作業役が動いている間は「もう一度見る」印を置くだけにする。
- main への push で data/thumbs/requests.json を変えたものは、すぐ作業役を起こす。変更一覧が無い・20件以上で
  省略されている push も「変えたかもしれない」として起こす。それ以外の main への push は、10分に1回まで
  「取りこぼしの回収」として起こす（定期の見回りを作らず、届いた通知を機会に回収する）。
- 受け口に置いた STOP（停止の印）がある間は、通知を受けても作業役を起こさない。
- 起動した時（Mac mini の再起動・ログイン時）にも1回だけ作業役を起こし、止まっていた間の依頼を回収する。
Python 3.9（macOS 標準）の標準ライブラリだけで動く。
"""
import fcntl
import hashlib
import hmac
import json
import os
import re
import subprocess
import sys
import threading
import time
from collections import OrderedDict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HOST = '127.0.0.1'
PORT = int(os.environ.get('BASUKE_THUMB_PORT', '8787'))
REPO_FULL_NAME = 'genjoK0216KK/bleague-matome'
REQUESTS_PATH = 'data/thumbs/requests.json'
KEYCHAIN_SERVICE = 'basuke-thumb-webhook'
PATHS = ('/', '/hooks/github', '/hooks/github/')      # Funnel の set-path の扱いに関わらず受ける
MAX_BODY = 5 * 1024 * 1024
READ_TIMEOUT = 10
MAX_CONNECTIONS = 8
WAKE_PER_MINUTE = 30                                  # 署名が正しい通知で作業役を起こす上限（超えても印は残す）
CATCHUP_EVERY = 600                                   # 台帳を変えない push での回収は10分に1回まで
SIGNATURE = re.compile(r'sha256=[0-9a-f]{64}\Z')
HOME = Path(os.environ.get('BASUKE_THUMB_HOME', str(Path.home() / 'Library/Application Support/basuke-thumb-hook')))
WORKER = Path(__file__).with_name('thumb_worker.py')


def log(msg):
    print(time.strftime('[%Y-%m-%d %H:%M:%S] ') + msg, flush=True)


def keychain_secret():
    out = subprocess.run(['/usr/bin/security', 'find-generic-password', '-s', KEYCHAIN_SERVICE, '-w'],
                         capture_output=True, text=True)
    return out.stdout.strip().encode() if out.returncode == 0 and out.stdout.strip() else None


def signature_ok(secret, body, header):
    if not secret or not isinstance(header, str) or not header.isascii() or not SIGNATURE.match(header):
        return False
    expected = 'sha256=' + hmac.new(secret, body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected.encode('ascii'), header.encode('ascii'))


def classify(payload):
    """'requests'（台帳を変えた／変えたかもしれない）・'other'（main への別の push）・'ignore'。型が違えば ValueError。"""
    if not isinstance(payload, dict):
        raise ValueError('payload is not an object')
    repo = payload.get('repository')
    if not isinstance(repo, dict) or repo.get('full_name') != REPO_FULL_NAME:
        return 'ignore'
    if payload.get('ref') != 'refs/heads/main' or payload.get('deleted') is True:
        return 'ignore'
    commits = payload.get('commits')
    if commits is None or commits == []:
        return 'requests'                                 # 変更一覧が無い：変えたかもしれない
    if not isinstance(commits, list):
        raise ValueError('commits is not a list')
    if len(commits) >= 20:
        return 'requests'                                 # GitHub は20件で打ち切る：変えたかもしれない
    for c in commits:
        if not isinstance(c, dict):
            raise ValueError('commit is not an object')
        for key in ('added', 'modified'):
            files = c.get(key) or []
            if not isinstance(files, list):
                raise ValueError('file list is not a list')
            if REQUESTS_PATH in files:
                return 'requests'
    return 'other'


def worker_running(home):
    try:
        with (Path(home) / 'lock').open('a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            fcntl.flock(lock, fcntl.LOCK_UN)
            return False
    except BlockingIOError:
        return True


def wake_worker(spawn=True, home=None, worker=None, python=None):
    """「もう一度見る」印を置く。作業役が動いていなければ起こす（動いていれば印だけで、その作業役が拾う）。"""
    home = Path(home or HOME)
    home.mkdir(parents=True, exist_ok=True)
    (home / 'dirty').write_text(time.strftime('%Y-%m-%dT%H:%M:%S'))
    if spawn and not worker_running(home):
        subprocess.Popen([python or sys.executable, str(worker or WORKER)], start_new_session=True,
                         stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return True
    return False


class Limiter:
    def __init__(self, per_minute):
        self.per_minute, self.stamps, self.lock = per_minute, [], threading.Lock()

    def allow(self):
        now = time.monotonic()
        with self.lock:
            self.stamps = [t for t in self.stamps if now - t < 60]
            if len(self.stamps) >= self.per_minute:
                return False
            self.stamps.append(now)
            return True


class Seen:
    """処理済みの通知ID（X-GitHub-Delivery）。最近の500件だけ覚える。"""

    def __init__(self, size=500):
        self.size, self.ids, self.lock = size, OrderedDict(), threading.Lock()

    def first_time(self, delivery):
        if not delivery:
            return True
        with self.lock:
            if delivery in self.ids:
                return False
            self.ids[delivery] = True
            while len(self.ids) > self.size:
                self.ids.popitem(last=False)
            return True


def make_handler(secret_provider=keychain_secret, waker=wake_worker, limiter=None, home=None, clock=time.monotonic):
    limiter = limiter or Limiter(WAKE_PER_MINUTE)
    seen = Seen()
    slots = threading.BoundedSemaphore(MAX_CONNECTIONS)
    home = Path(home or HOME)
    state = {'last_catchup': None}

    class Handler(BaseHTTPRequestHandler):
        server_version = 'basuke-thumb-hook'
        sys_version = ''
        timeout = READ_TIMEOUT

        def log_message(self, fmt, *args):      # 既定のアクセスログ（IP・パス）は出さない
            pass

        def reply(self, code, text):
            body = text.encode()
            self.send_response(code)
            self.send_header('Content-Type', 'text/plain; charset=utf-8')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            self.reply(404, 'not found')

        def do_POST(self):
            if not slots.acquire(blocking=False):
                return self.reply(503, 'busy')
            try:
                return self.handle_post()
            finally:
                slots.release()

        def handle_post(self):
            if self.path.split('?', 1)[0] not in PATHS:
                return self.reply(404, 'not found')
            try:
                length = int(self.headers.get('Content-Length') or 0)
            except ValueError:
                return self.reply(400, 'bad length')
            if length <= 0 or length > MAX_BODY:
                return self.reply(413, 'payload too large')
            body = self.rfile.read(length)
            if len(body) != length:
                return self.reply(400, 'short body')
            if not signature_ok(secret_provider(), body, self.headers.get('X-Hub-Signature-256')):
                log('拒否：署名なし・形式違い・不一致')
                return self.reply(401, 'bad signature')
            event = self.headers.get('X-GitHub-Event', '')
            if event == 'ping':
                log('GitHub から ping を受信（Webhook の登録を確認）')
                return self.reply(200, 'pong')
            if event != 'push':
                return self.reply(202, 'ignored event')
            if not seen.first_time(self.headers.get('X-GitHub-Delivery', '')):
                return self.reply(202, 'duplicate')
            try:
                kind = classify(json.loads(body.decode('utf-8')))
            except (ValueError, UnicodeDecodeError):
                return self.reply(400, 'bad payload')
            if kind == 'ignore':
                return self.reply(202, 'ignored push')
            if (home / 'STOP').exists():
                log('停止の印（STOP）があるため作業役を起こさない')
                return self.reply(202, 'paused')
            if kind == 'other':
                now = clock()
                if state['last_catchup'] is not None and now - state['last_catchup'] < CATCHUP_EVERY:
                    return self.reply(202, 'ignored push')
                state['last_catchup'] = now
                log('main への push を機会に、取りこぼしの回収で作業役を起こす')
            else:
                log('依頼台帳の更新を受信：作業役を起こす')
            waker(spawn=limiter.allow())                  # 上限を超えても印は置く（動いている作業役が拾う）
            return self.reply(202, 'accepted')

    return Handler


def main():
    if not keychain_secret():
        log('合言葉がキーチェーンに無い（サービス名 ' + KEYCHAIN_SERVICE + '）。全ての通知を拒否します')
    if not (HOME / 'STOP').exists():
        wake_worker()                                 # 起動・ログイン時に1回だけ、止まっていた間の依頼を回収
    server = ThreadingHTTPServer((HOST, PORT), make_handler())
    server.daemon_threads = True
    log(f'待ち受け開始 http://{HOST}:{PORT}（外からは Tailscale Funnel 経由のみ）')
    server.serve_forever()


if __name__ == '__main__':
    main()

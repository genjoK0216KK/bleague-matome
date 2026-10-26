#!/usr/bin/env python3
"""バスケまとめ：記事ができたら Mac mini でその場でサムネを作るための受け口（MINI-8、本人 10/27 推奨案を選択）。

流れ：GitHub の Webhook（push）→ Tailscale Funnel → この受け口（127.0.0.1 だけで待ち受け）→ 作業役（thumb_worker.py）。

- GitHub の署名（X-Hub-Signature-256、HMAC-SHA256）を合言葉で確かめる。署名なし・不一致は 401。
- 届いた中身は「依頼の台帳を見に行く合図」としてだけ使う。記事本文や指示は中身から一切読まない。
  作業役が GitHub から依頼台帳と固定版の記事を自分で取りに行くので、合言葉が漏れても
  「main に既にある依頼を処理させる」こと以上はできない。
- push のうち、main への push で data/thumbs/requests.json を変えたもの（または変更一覧が省略されたもの）だけ受け付ける。
- 受け付けたら「もう一度見る」印を置いて作業役を起こし、すぐ 202 を返す（生成は待たない）。
- 起動した時（Mac mini の再起動・復帰）にも1回だけ作業役を起こし、止まっていた間の依頼を回収する。
- 合言葉は macOS のキーチェーン（サービス名 basuke-thumb-webhook）から読む。画面・ログ・ファイルには出さない。
Python 3.9（macOS 標準）の標準ライブラリだけで動く。
"""
import hashlib
import hmac
import json
import os
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HOST = '127.0.0.1'
PORT = int(os.environ.get('BASUKE_THUMB_PORT', '8787'))
REPO_FULL_NAME = 'genjoK0216KK/bleague-matome'
REQUESTS_PATH = 'data/thumbs/requests.json'
KEYCHAIN_SERVICE = 'basuke-thumb-webhook'
PATHS = ('/', '/hooks/github', '/hooks/github/')      # Funnel の set-path の扱いに関わらず受ける
MAX_BODY = 5 * 1024 * 1024
RATE_LIMIT = 30                                       # 1分あたりの受付上限（超えたら 429）
HOME = Path(os.environ.get('BASUKE_THUMB_HOME', str(Path.home() / 'Library/Application Support/basuke-thumb-hook')))
WORKER = Path(__file__).with_name('thumb_worker.py')


def log(msg):
    print(time.strftime('[%Y-%m-%d %H:%M:%S] ') + msg, flush=True)


def keychain_secret():
    out = subprocess.run(['/usr/bin/security', 'find-generic-password', '-s', KEYCHAIN_SERVICE, '-w'],
                         capture_output=True, text=True)
    return out.stdout.strip().encode() if out.returncode == 0 and out.stdout.strip() else None


def signature_ok(secret, body, header):
    if not secret or not header or not header.startswith('sha256='):
        return False
    expected = 'sha256=' + hmac.new(secret, body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, header)


def touches_requests(payload):
    """main への push で依頼台帳を変えたか。変更一覧が無い・省略されている時は「変えたかもしれない」として受ける。"""
    if payload.get('repository', {}).get('full_name') != REPO_FULL_NAME:
        return False
    if payload.get('ref') != 'refs/heads/main' or payload.get('deleted'):
        return False
    commits = payload.get('commits')
    if not isinstance(commits, list) or not commits or len(commits) >= 20:   # GitHub は20件で打ち切る
        return True
    for c in commits:
        for key in ('added', 'modified'):
            if REQUESTS_PATH in (c.get(key) or []):
                return True
    return False


def wake_worker(home=None, worker=None, python=None):
    """「もう一度見る」印を置いて作業役を起こす。作業役は1つだけ動き、印が無くなるまで繰り返す。"""
    home = Path(home or HOME)
    home.mkdir(parents=True, exist_ok=True)
    (home / 'dirty').write_text(time.strftime('%Y-%m-%dT%H:%M:%S'))
    subprocess.Popen([python or sys.executable, str(worker or WORKER)], start_new_session=True,
                     stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


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


def make_handler(secret_provider=keychain_secret, waker=wake_worker, limiter=None):
    limiter = limiter or Limiter(RATE_LIMIT)

    class Handler(BaseHTTPRequestHandler):
        server_version = 'basuke-thumb-hook'
        sys_version = ''

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
            if self.path.split('?', 1)[0] not in PATHS:
                return self.reply(404, 'not found')
            if not limiter.allow():
                return self.reply(429, 'too many requests')
            try:
                length = int(self.headers.get('Content-Length') or 0)
            except ValueError:
                return self.reply(400, 'bad length')
            if length <= 0 or length > MAX_BODY:
                return self.reply(413, 'payload too large')
            body = self.rfile.read(length)
            if not signature_ok(secret_provider(), body, self.headers.get('X-Hub-Signature-256')):
                log('拒否：署名なし・不一致')
                return self.reply(401, 'bad signature')
            event = self.headers.get('X-GitHub-Event', '')
            if event == 'ping':
                log('GitHub から ping を受信（Webhook の登録を確認）')
                return self.reply(200, 'pong')
            if event != 'push':
                return self.reply(202, 'ignored event')
            try:
                payload = json.loads(body.decode('utf-8'))
            except (ValueError, UnicodeDecodeError):
                return self.reply(400, 'bad json')
            if not touches_requests(payload):
                return self.reply(202, 'ignored push')
            log('依頼台帳の更新を受信：作業役を起こす（' + str(payload.get('after', ''))[:12] + '）')
            waker()
            return self.reply(202, 'accepted')

    return Handler


def main():
    if not keychain_secret():
        log('合言葉がキーチェーンに無い（サービス名 ' + KEYCHAIN_SERVICE + '）。全ての通知を拒否します')
    wake_worker()                                     # 起動・復帰時に1回だけ、止まっていた間の依頼を回収
    server = ThreadingHTTPServer((HOST, PORT), make_handler())
    log(f'待ち受け開始 http://{HOST}:{PORT}（外からは Tailscale Funnel 経由のみ）')
    server.serve_forever()


if __name__ == '__main__':
    main()

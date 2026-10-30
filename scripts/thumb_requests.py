#!/usr/bin/env python3
"""記事を作った時に1回だけ、サムネの依頼を積む（MINI-8、本人 10/26「サムネは記事を作成する時のみ。巡回は必要ない」）。

記事を作るのは GitHub Actions（update.yml・results.yml など）で、どれも最後に build.py を通る。build.py の最後で
この record() を呼び、まだ依頼の台帳 data/thumbs/requests.json に無い記事だけを「作成イベント」として1件積む。

- 記事1本につき1回きり。作成イベントIDは記事のパスから決まるので、同じ記事の本文更新・取得時刻・閲覧数・
  画像の差し替え・再実行では、新しい依頼は増えない。
- 例外：毎日の記事（article-daily-*）は、記事ルーティンが本文を書き換えた時に作り直しを1件積む（本人 10/30「C」）。
  画像の文字（「19時更新時点」など）が古くなるため。1記事あたり REDO_MAX 回まで。閲覧数・広告だけの変化では
  積まない（stable_fingerprint で比べる）。試合の記事は数分おきに変わるので本文では作り直さず、見出しが変わった時
  （試合前の「ベスト5」が試合後に「試合結果」になる等）だけ作り直す。
- 依頼には、固定版の HTML（Git の blob SHA で GitHub から取り出せる）と、生成側と同じ定義の本文指紋を記録する。
  文章（TXT）は生成側が同じ HTML から作る。
- この台帳が main へ push されると、GitHub の Webhook が Tailscale Funnel 経由で Mac mini の受け口
  （mac/thumb-hook/hook_receiver.py）へ知らせ、作業役（thumb_worker.py）がその場で thumbnail_queue.py requests →
  codex exec → ready → 送信を行う（本人 10/27 選択）。定期巡回は使わない。
- data/thumbs/config.json の enabled が true の時だけ動く。
- 基準（baseline＝作らない記事）は、有効にする時に1回だけ init で確定させる（python scripts/thumb_requests.py --init）。
  enabled=true にするのと同じコミットで、記事を作る更新より前に実行する。台帳が無いうちは record() は何も積まない
  （有効化した直後の更新で作られた新しい記事を、基準に取り込んで取りこぼさないため）。
"""
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path

try:
    from . import thumb_auto
except ImportError:
    import thumb_auto

REQUESTS = 'data/thumbs/requests.json'
START = '20261025'                      # 生成側 thumbnail_queue.py の START と同じ（それより前の記事は対象外）
ARTICLE = re.compile(r'article-[A-Za-z0-9_-]*?(\d{8})\.html')
REDO = re.compile(r'article-daily-\d{8}\.html')
REDO_MAX = 3


def event_id(path, revision=0, stable=''):
    """作成イベントは記事のパスだけ、作り直し（revision 1〜）は本文の版も入れて決める。"""
    key = 'create\0' + path if not revision else f'update\0{path}\0{revision}\0{stable}'
    return hashlib.sha256(key.encode()).hexdigest()[:20]


def _title(raw):
    return thumb_auto._h1_text(raw.decode('utf-8', 'replace'))


def _entry(article, raw, kind, stamp, date, revision=0):
    stable = thumb_auto.stable_fingerprint(raw)
    entry = dict(event_id=event_id(article.name, revision, stable), article_path=article.name,
                 article_url=thumb_auto.SITE + article.name, target_date=date,
                 source_blob_sha=thumb_auto.blob_sha(raw),
                 editorial_fingerprint=thumb_auto.editorial_fingerprint(raw),
                 stable_fingerprint=stable, title=_title(raw), status=kind, recorded_at=stamp)
    if revision:
        entry['revision'] = revision
    return entry


def _articles(root):
    for article in sorted(Path(root).glob('article-*.html')):
        m = ARTICLE.fullmatch(article.name)
        if m and m[1] >= START:
            yield article, m[1]


def init(root, now=None):
    """有効化の時に1回だけ：その時点の既存記事をすべて基準（作らない）として台帳を作る。既にあれば何もしない。"""
    root = Path(root)
    target = root / REQUESTS
    if target.exists():
        return {'created': False, 'baseline': []}
    stamp = (now or datetime.now(timezone.utc)).isoformat()
    events = {a.name: _entry(a, a.read_bytes(), 'baseline', stamp, d) for a, d in _articles(root)}
    thumb_auto.save_json(target, {'version': 1, 'baseline_at': stamp, 'events': events})
    return {'created': True, 'baseline': sorted(events)}


def record(root, now=None):
    """新しく現れた記事の依頼と、毎日の記事の作り直しを積む。戻り値：{'enabled', 'initialized', 'baseline', 'requested'}。
    台帳が無い（init 前）なら何もしない。"""
    root = Path(root)
    result = {'enabled': thumb_auto.enabled(root), 'initialized': False, 'baseline': [], 'requested': []}
    if not result['enabled']:
        return result
    target = root / REQUESTS
    data = thumb_auto.load_json(target, None)
    if not isinstance(data, dict):
        return result
    result['initialized'] = True
    stamp = (now or datetime.now(timezone.utc)).isoformat()
    events = data.setdefault('events', {})
    changed = False
    for article, date in _articles(root):
        old = events.get(article.name)
        if old is None:
            events[article.name] = _entry(article, article.read_bytes(), 'requested', stamp, date)
            result['requested'].append(article.name)
            continue
        if old.get('status') != 'requested':
            continue
        raw = article.read_bytes()
        stable, title = thumb_auto.stable_fingerprint(raw), _title(raw)
        if not old.get('stable_fingerprint') or 'title' not in old:     # 作り直しを入れる前の依頼：いまの版を基準にするだけ
            old.update(stable_fingerprint=stable, title=title)
            changed = True
            continue
        rewritten = old['stable_fingerprint'] != stable if REDO.fullmatch(article.name) else old['title'] != title
        if rewritten and old.get('revision', 0) < REDO_MAX:
            events[article.name] = _entry(article, raw, 'requested', stamp, date, old.get('revision', 0) + 1)
            result['requested'].append(article.name)
    if result['requested'] or changed:
        thumb_auto.save_json(target, data)
    return result


if __name__ == '__main__':
    import sys
    root = Path(__file__).resolve().parent.parent
    print(json.dumps(init(root) if '--init' in sys.argv[1:] else record(root), ensure_ascii=False))

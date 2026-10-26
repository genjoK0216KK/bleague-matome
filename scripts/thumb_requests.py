#!/usr/bin/env python3
"""記事を作った時に1回だけ、サムネの依頼を積む（MINI-8、本人 10/26「サムネは記事を作成する時のみ。巡回は必要ない」）。

記事を作るのは GitHub Actions（update.yml・results.yml など）で、どれも最後に build.py を通る。build.py の最後で
この record() を呼び、まだ依頼の台帳 data/thumbs/requests.json に無い記事だけを「作成イベント」として1件積む。

- 記事1本につき1回きり。作成イベントIDは記事のパスから決まるので、同じ記事の本文更新・取得時刻・閲覧数・
  画像の差し替え・再実行では、新しい依頼は増えない。
- 依頼には、固定版の HTML（Git の blob SHA で GitHub から取り出せる）と、生成側と同じ定義の本文指紋を記録する。
  文章（TXT）は生成側が同じ HTML から作る。
- 依頼を読んで画像を作るのは Mac mini 側（thumbnail_queue.py requests）。サイトから Mac mini へ直接は知らせない
  （外から届く経路が無い）。Mac mini で既に動いている巡回が、新しい依頼がある時だけ1回処理する。
- data/thumbs/config.json の enabled が true の時だけ動く。有効にして最初の1回は、その時点の既存記事を
  すべて「基準（baseline＝作らない）」として登録し、過去記事の一斉生成を起こさない。
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


def event_id(path):
    return hashlib.sha256(('create\0' + path).encode()).hexdigest()[:20]


def record(root, now=None):
    """新しく現れた記事だけ依頼を積む。戻り値：{'enabled', 'baseline', 'requested'}。"""
    root = Path(root)
    result = {'enabled': thumb_auto.enabled(root), 'baseline': [], 'requested': []}
    if not result['enabled']:
        return result
    stamp = (now or datetime.now(timezone.utc)).isoformat()
    target = root / REQUESTS
    data = thumb_auto.load_json(target, None)
    first = not isinstance(data, dict)
    if first:
        data = {'version': 1, 'baseline_at': stamp, 'events': {}}
    events = data.setdefault('events', {})
    for article in sorted(root.glob('article-*.html')):
        m = ARTICLE.fullmatch(article.name)
        if not m or m[1] < START or article.name in events:
            continue
        raw = article.read_bytes()
        kind = 'baseline' if first else 'requested'
        events[article.name] = dict(
            event_id=event_id(article.name), article_path=article.name,
            article_url=thumb_auto.SITE + article.name, target_date=m[1],
            source_blob_sha=thumb_auto.blob_sha(raw),
            editorial_fingerprint=thumb_auto.editorial_fingerprint(raw),
            status=kind, recorded_at=stamp)
        result[kind].append(article.name)
    if result['baseline'] or result['requested']:
        thumb_auto.save_json(target, data)
    return result


if __name__ == '__main__':
    print(json.dumps(record(Path(__file__).resolve().parent.parent), ensure_ascii=False))

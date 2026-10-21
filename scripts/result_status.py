"""Per-date state of the official RESULT fetch (separate from EFF TOP3 state).

States shown to readers:
  - 試合前            : the game has not started at the time of the last official check
  - 公式記録未確定    : started (or ended) but GameEndedFlg AND RecordFixedFlg are not both true
  - 取得失敗          : the latest attempt could not read the official site; the page keeps the
                        last verified data and shows when it was last read successfully

Two different times are kept per date and never mixed:
  last_checked_at : the last time the official site was actually read successfully for the date
                    (every successful read, also when nothing changed; never advanced when no
                    network read happened, e.g. already final or deferred)
  content_as_of   : when the official data shown on the page was retrieved (advances only when
                    the page is written from a new read)
Failures keep both times and record when failing started. Identical repeated failures do not
rewrite the file.
Only public facts are stored: date, URL, HTTP status, exception type, times.
"""
import json
import re
from datetime import datetime, timedelta
from html import escape
from pathlib import Path

PATH = 'data/match_articles/result-status.json'
KEEP_DAYS = 7
JST_FORMAT = '%Y-%m-%d %H:%M JST'


def load(root):
    try:
        data = json.loads((Path(root) / PATH).read_text())
    except (OSError, ValueError):
        return {}
    return data.get('dates', {}) if isinstance(data, dict) else {}


def _save(root, dates, now):
    keep = (now.date() - timedelta(days=KEEP_DAYS)).isoformat()
    dates = {d: v for d, v in sorted(dates.items()) if d >= keep}
    path = Path(root) / PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({'dates': dates}, ensure_ascii=False, indent=1) + '\n', encoding='utf-8')


def stamp(now):
    return now.strftime(JST_FORMAT)


def record_success(root, date, now, changed):
    """A successful official read of `date` at `now` (call only after a real network read).

    changed=True: the page was written from this read, so the shown content is as of `now`.
    Returns True when the reader-facing state changed (a failure notice must be removed)."""
    dates = load(root)
    entry = dates.get(date) or {}
    content = stamp(now) if changed else (entry.get('content_as_of') or last_retrieval(root, date))
    new = {'state': 'ok', 'last_checked_at': stamp(now), 'content_as_of': content}
    if new != entry:
        dates[date] = new
        _save(root, dates, now)
    return entry.get('state') == 'fetch_failed'


def record_failure(root, date, now, error):
    """Mark a date unreadable. Keeps the first failure time and both success times."""
    dates = load(root)
    entry = dates.get(date) or {}
    public = {k: error.get(k) for k in ('category', 'type', 'http_status', 'url')}
    if entry.get('state') == 'fetch_failed' and entry.get('error') == public:
        return False
    content = entry.get('content_as_of') or last_retrieval(root, date)
    dates[date] = {'state': 'fetch_failed',
                   'failing_since': entry.get('failing_since') if entry.get('state') == 'fetch_failed' else stamp(now),
                   'last_checked_at': entry.get('last_checked_at') or content,
                   'content_as_of': content,
                   'error': public}
    _save(root, dates, now)
    return True


def last_retrieval(root, date):
    """Fallback for the last successful read: the article's own '資料取得 … JST' line."""
    try:
        text = (Path(root) / ('article-games-' + date.replace('-', '') + '.html')).read_text(encoding='utf-8')
    except OSError:
        return None
    found = re.findall(r'資料取得 [0-9: -]+?〜(\d{4}-\d{2}-\d{2} \d{2}:\d{2}) JST', text)
    return found[-1] + ' JST' if found else None


def failed(root, date):
    entry = load(root).get(date)
    return entry if entry and entry.get('state') == 'fetch_failed' else None


def times_text(entry):
    """'最後に確認できた時刻' and '表示内容の取得時刻' (merged when equal)."""
    checked, content = entry.get('last_checked_at'), entry.get('content_as_of')
    if checked and content and checked != content:
        return ('最後に公式サイトを確認できたのは ' + escape(checked) + '、表示中の内容は '
                + escape(content) + ' に取得した公式記録です（その後の確認でも変化なし）。')
    if checked or content:
        return '表示中の内容は ' + escape(checked or content) + ' 時点の公式記録です。'
    return '表示中の内容は前回確認できた公式記録です。'


def notice_html(entry):
    """Reader-facing warning. No error text from the remote site is shown."""
    since = escape(entry.get('failing_since') or '時刻不明')
    return ('<div class="note fetch-failed" id="result-fetch-status" role="status">'
            '<strong>公式サイトから最新の結果を取得できていません</strong>（' + since + ' から）。'
            + times_text(entry) + '試合前・未確定の表示は最新の状態と異なる場合があります。確定した結果は各試合の公式ページでご確認ください。</div>')


def apply_notice(root, date):
    """Add, update or remove the fetch warning in the saved dated article(s) without
    re-rendering anything else. Returns True when a file changed."""
    from bs4 import BeautifulSoup
    entry = failed(root, date)
    changed = False
    stem = date.replace('-', '')
    for name in ('article-games-' + stem + '.html', 'article-results-one-next-' + stem + '.html'):
        path = Path(root) / name
        if not path.exists():
            continue
        before = path.read_text(encoding='utf-8')
        soup = BeautifulSoup(before, 'html.parser')
        old = soup.select_one('#result-fetch-status')
        if old is not None:
            old.decompose()
        if entry:
            anchor = soup.select_one('#daily-results') or soup.select_one('article')
            if anchor is None:
                continue
            node = BeautifulSoup(notice_html(entry), 'html.parser').div
            if anchor.name == 'article':
                anchor.insert(0, node)
            else:
                anchor.insert_before(node)
        after = str(soup)
        if old is None and not entry:
            continue  # nothing to add or remove: keep the original bytes
        if after != before:
            path.write_text(after, encoding='utf-8')
            changed = True
    return changed


def game_state(game, now, verified_final):
    """Reader label for a non-final game: 試合前 / 公式記録未確定. Never guesses a result."""
    if verified_final(game):
        return '終了'
    if game.get('status') == 'cancelled':
        return '中止'
    if game.get('status') == 'postponed':
        return '延期'
    starts = game.get('starts_at')
    if not starts:
        return '時刻未確認'
    start = datetime.fromisoformat(starts)
    clock = start.astimezone(now.tzinfo).strftime('%H:%M')
    if game.get('status') == 'scheduled' and now < start:
        return clock + ' 試合前'
    return clock + ' 開始・公式記録未確定'

"""Per-date state of the official RESULT fetch (separate from EFF TOP3 state).

States shown to readers:
  - 試合前            : the game has not started at the time of the last official check
  - 公式記録未確定    : started (or ended) but GameEndedFlg AND RecordFixedFlg are not both true
  - 取得失敗          : the latest attempt could not read the official site; the page keeps the
                        last verified data and shows when it was last read successfully

The file only changes on a state transition (ok -> failed, failed -> ok, new data written),
so repeated identical failures every 15 minutes do not create commits.
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
    """Mark a date readable. Writes only when data changed or a failure is cleared."""
    dates = load(root)
    entry = dates.get(date)
    if not changed and (entry is None or entry.get('state') == 'ok'):
        return False
    dates[date] = {'state': 'ok', 'last_success_at': stamp(now)}
    _save(root, dates, now)
    return True


def record_failure(root, date, now, error):
    """Mark a date unreadable. Keeps the first failure time and the last success time."""
    dates = load(root)
    entry = dates.get(date) or {}
    public = {k: error.get(k) for k in ('type', 'http_status', 'url')}
    if entry.get('state') == 'fetch_failed' and entry.get('error') == public:
        return False
    dates[date] = {'state': 'fetch_failed',
                   'failing_since': entry.get('failing_since') if entry.get('state') == 'fetch_failed' else stamp(now),
                   'last_success_at': entry.get('last_success_at') or last_retrieval(root, date),
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


def notice_html(entry):
    """Reader-facing warning. No error text from the remote site is shown."""
    since = escape(entry.get('failing_since') or '時刻不明')
    last = entry.get('last_success_at')
    shown = ('表示中の内容は ' + escape(last) + ' 時点の公式記録です。') if last else '表示中の内容は前回確認できた公式記録です。'
    return ('<div class="note fetch-failed" id="result-fetch-status" role="status">'
            '<strong>公式サイトから最新の結果を取得できていません</strong>（' + since + ' から）。'
            + shown + '試合前・未確定の表示は最新の状態と異なる場合があります。確定した結果は各試合の公式ページでご確認ください。</div>')


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

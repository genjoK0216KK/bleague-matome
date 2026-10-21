"""Compact, source-backed entrances to dated games."""
import json
from pathlib import Path
from datetime import datetime, timedelta
from html import escape
try:
    from . import preview_data, official_data, next_preview, result_status
except ImportError:
    import preview_data, official_data, next_preview, result_status


def summaries(root, now=None):
    now = now or datetime.now(preview_data.JST)
    rows = []
    for path in Path(root, 'data/match_articles').glob('article-games-*.json'):
        row = json.loads(path.read_text())
        release = datetime.fromisoformat(row['date']).replace(tzinfo=preview_data.JST)-timedelta(hours=1)
        if now >= release:
            fetch = result_status.failed(root, row['date'])
            if fetch:
                row = dict(row, fetch_status=fetch)
            rows.append(row)
    return sorted(rows, key=lambda r:r['date'], reverse=True)


def match_row(game, date, now=None, fetch_failed=False):
    now = now or datetime.now(preview_data.JST)
    if preview_data.is_verified_final(game):
        value = f"{game['home_score']} – {game['away_score']}"
        state = '終了'
    else:
        value = '—'
        state = result_status.game_state(game, now, preview_data.is_verified_final)
        if fetch_failed and game.get('status') not in ('cancelled', 'postponed'):
            state += '・取得失敗'
    return ('<a class="match-row" href="article-games-'+date.replace('-','')+'.html">'
            '<span>'+escape(game.get('home') or '未確認')+'</span><strong>'+escape(value)+'</strong>'
            '<span>'+escape(game.get('away') or '未確認')+'</span><small>'+escape(state)+'</small></a>')


def fetch_note(row):
    fetch = row.get('fetch_status')
    if not fetch:
        return ''
    return ('<p class="note fetch-failed">公式サイトから最新の結果を取得できていません（'
            + escape(fetch.get('failing_since') or '時刻不明') + ' から）。' + result_status.times_text(fetch) + '</p>')


def day_body(row, limit=None, now=None):
    body = fetch_note(row)
    failed = bool(row.get('fetch_status'))
    empty = []
    for league, settings in official_data.LEAGUES.items():
        games = [g for g in row['games'] if g['competition']==league]
        if limit and not games:
            empty.append(settings[3]+('：試合なし' if row.get('schedule_complete',{}).get(league) else '：日程未確認'))
            continue
        body += '<h3 class="league-heading">'+escape(settings[3])+(' <small>全'+str(len(games))+'試合</small>' if limit and len(games)>limit else '')+'</h3>'
        body += ''.join(match_row(g,row['date'],now,failed) for g in games[:limit])
        if not games:
            body += '<p class="empty-games">'+('試合なし' if row.get('schedule_complete',{}).get(league) else '日程未確認')+'</p>'
    if empty:
        body += '<p class="empty-games">'+' ／ '.join(empty)+'</p>'
    return body


def results(root, now=None):
    rows = summaries(root, now)
    if not rows:
        return '<p>試合情報は確認中です。</p>'
    default = next((r['date'] for r in rows if any(preview_data.is_verified_final(g) for g in r['games'])), rows[0]['date'])
    body = '<section class="date-browser" data-default="day-'+default+'"><nav class="date-chips" aria-label="試合日">'
    body += ''.join('<a href="#day-'+r['date']+'">'+r['date'][5:].replace('-','/')+'</a>' for r in rows)
    body += '</nav>'
    for row in rows:
        body += '<section class="date-panel" id="day-'+row['date']+'"><h2>'+row['date']+' の試合</h2>'+day_body(row,now=now)+'<a class="day-detail" href="article-games-'+row['date'].replace('-','')+'.html">この日の結果・選手ランキング ›</a></section>'
    return body+'</section><script src="game-browser.js" defer></script>'


def home(root, now=None):
    now = now or datetime.now(preview_data.JST)
    rows = summaries(root, now)
    today = next((r for r in rows if r['date']==now.date().isoformat()), None)
    preview=next_preview.load(root,now)
    body='<section class="home-preview preview-heading"'+(' data-preview-valid-until="'+next_preview.valid_until(preview).isoformat()+'"' if preview else '')+'><p class="phase-label">試合前 ／ 今季平均 EFF</p><h2>'+next_preview.TITLE+'</h2>'
    if preview:
        body+='<p class="fixture-date">'+('確認できた次の開催日' if preview.get('errors') else '次の開催日')+' <strong>'+preview['date']+'</strong></p>'
        body+='<p>'+escape(' ／ '.join(official_data.LEAGUES[k][3] for k in official_data.LEAGUES if any(g['competition']==k for g in preview['games'])))+'</p>'
    else: body+='<p>次の開催日・登録選手を確認中</p>'
    body+='<a class="primary-action" href="next-games.html">ベスト5・サブ5を見る →</a></section>'
    return body+'<script src="next-preview.js" defer></script>'+home_games(root, now, rows)


PENDING_DAYS = 3  # same window as the results refresh (update_results.LOOKBACK_DAYS)


def pending_past(rows, now):
    """Past dates whose results are not all official yet stay visible after midnight."""
    today = now.date()
    out = ''
    for row in rows:
        day = datetime.fromisoformat(row['date']).date()
        if not (0 < (today - day).days <= PENDING_DAYS):
            continue
        waiting = [g for g in row['games'] if not preview_data.is_verified_final(g)
                   and g.get('status') not in ('cancelled', 'postponed')]
        if not waiting:
            continue
        label = row['date'][5:].replace('-', '/')
        state = '公式サイトから取得できていません' if row.get('fetch_status') else '公式記録の確定待ちです'
        out += ('<p class="pending-past">' + label + ' の ' + str(len(waiting)) + ' 試合は' + state + '。'
                '<a class="day-detail" href="article-games-' + row['date'].replace('-', '') + '.html">'
                + label + ' の試合を見る ›</a></p>')
    return out


def home_games(root, now=None, rows=None):
    """トップの「今日の試合・直近の結果」（補助導線）。"""
    now = now or datetime.now(preview_data.JST)
    rows = summaries(root, now) if rows is None else rows
    today = next((r for r in rows if r['date']==now.date().isoformat()), None)
    body=''
    has_results = today and any(preview_data.is_verified_final(g) for g in today['games'])
    phase = '試合結果 ／ 当日の EFF' if has_results else ('試合予定 ／ 開始時刻' if today and today['games'] else '試合日程 ／ 確認状況')
    body+='<section class="home-games" id="games"><p class="phase-label result-label">'+phase+'</p><h2>今日の試合 <small>'+now.strftime('%m/%d')+'</small></h2>'
    if today and today['games'] and (Path(root)/('article-games-'+today['date'].replace('-','')+'.html')).exists():
        href='article-games-'+today['date'].replace('-','')+'.html'
        body += '<nav class="quick-actions" aria-label="今日の試合の見方"><a href="'+href+'#daily-results">全'+str(len(today['games']))+'試合を見る →</a>'
        if any(v.get('positions') for v in today.get('game_day_rankings',{}).get('leagues',{}).values()):
            body+='<a href="'+href+'#game-eff">当日のEFF・TOP3 →</a>'
        body+='</nav>'
    body += day_body(today,2,now) if today else '<p>今日の試合情報は確認中です。</p>'
    body += pending_past(rows, now)
    recent = next((r for r in rows if r['date']<=now.date().isoformat() and any(preview_data.is_verified_final(g) for g in r['games'])),None)
    if recent:
        body += '<h3>直近の結果 <small>'+recent['date'][5:]+'</small></h3>'
        if any(v.get('positions') for v in recent.get('game_day_rankings',{}).get('leagues',{}).values()):body+='<a class="day-detail" href="article-games-'+recent['date'].replace('-','')+'.html#game-eff">この日のEFF・TOP3 →</a>'
        body += ''.join(match_row(g,recent['date'],now) for g in [g for g in recent['games'] if preview_data.is_verified_final(g)][:2])
    return body+'<a class="day-detail" href="cat-kekka.html">すべての試合・日付を選ぶ ›</a></section>'

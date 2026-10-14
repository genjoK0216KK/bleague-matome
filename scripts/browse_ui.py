"""Compact, source-backed entrances to dated games."""
import json
from pathlib import Path
from datetime import datetime, timedelta
from html import escape
from . import preview_data, official_data


def summaries(root, now=None):
    now = now or datetime.now(preview_data.JST)
    rows = []
    for path in Path(root, 'data/match_articles').glob('article-games-*.json'):
        row = json.loads(path.read_text())
        release = datetime.fromisoformat(row['date']).replace(tzinfo=preview_data.JST)-timedelta(hours=1)
        if now >= release:
            rows.append(row)
    return sorted(rows, key=lambda r:r['date'], reverse=True)


def match_row(game, date):
    if preview_data.is_verified_final(game):
        value = f"{game['home_score']} – {game['away_score']}"
        state = '終了'
    else:
        value = '—'
        state = {'cancelled':'中止','postponed':'延期'}.get(game.get('status'),'予定・結果未確認')
        if game.get('starts_at') and game.get('status') not in ('cancelled','postponed'):
            state = datetime.fromisoformat(game['starts_at']).astimezone(preview_data.JST).strftime('%H:%M') + ' ' + state
    return ('<a class="match-row" href="article-games-'+date.replace('-','')+'.html">'
            '<span>'+escape(game.get('home') or '未確認')+'</span><strong>'+escape(value)+'</strong>'
            '<span>'+escape(game.get('away') or '未確認')+'</span><small>'+escape(state)+'</small></a>')


def day_body(row, limit=None):
    body = ''
    empty = []
    for league, settings in official_data.LEAGUES.items():
        games = [g for g in row['games'] if g['competition']==league]
        if limit and not games:
            empty.append(settings[3]+('：試合なし' if row.get('schedule_complete',{}).get(league) else '：日程未確認'))
            continue
        body += '<h3 class="league-heading">'+escape(settings[3])+(' <small>全'+str(len(games))+'試合</small>' if limit and len(games)>limit else '')+'</h3>'
        body += ''.join(match_row(g,row['date']) for g in games[:limit])
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
        body += '<section class="date-panel" id="day-'+row['date']+'"><h2>'+row['date']+' の試合</h2>'+day_body(row)+'<a class="day-detail" href="article-games-'+row['date'].replace('-','')+'.html">この日の結果・選手ランキング ›</a></section>'
    return body+'</section><script src="game-browser.js" defer></script>'


def home(root, now=None):
    now = now or datetime.now(preview_data.JST)
    rows = summaries(root, now)
    today = next((r for r in rows if r['date']==now.date().isoformat()), None)
    body = '<section class="home-games"><h2>今日の試合 <small>'+now.strftime('%m/%d')+'</small></h2>'
    if today:
        href='article-games-'+today['date'].replace('-','')+'.html'
        body += '<nav class="quick-actions" aria-label="今日の試合の見方"><a class="primary-action" href="'+href+'#daily-lineups">ベスト5・平均EFF <span aria-hidden="true">↗</span></a><a href="'+href+'#daily-results">全'+str(len(today['games']))+'試合を見る <span aria-hidden="true">→</span></a></nav>'
    body += day_body(today,2) if today else '<p>今日の試合情報は確認中です。</p>'
    recent = next((r for r in rows if r['date']<=now.date().isoformat() and any(preview_data.is_verified_final(g) for g in r['games'])),None)
    if recent:
        body += '<h3>直近の結果 <small>'+recent['date'][5:]+'</small></h3>'
        body += ''.join(match_row(g,recent['date']) for g in [g for g in recent['games'] if preview_data.is_verified_final(g)][:2])
    return body+'<a class="day-detail" href="cat-kekka.html">すべての試合・日付を選ぶ ›</a></section>'

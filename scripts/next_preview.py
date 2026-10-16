"""A dated, pregame selection independent of tomorrow and editorial posting."""
import json
from datetime import datetime, timedelta
from pathlib import Path
try:
    from . import official_data as official, preview_data as data, daily_lineups, day_articles, match_articles as articles, stats
except ImportError:
    import official_data as official, preview_data as data, daily_lineups, day_articles, match_articles as articles, stats

TITLE = '出場予定選手（登録選手）のベスト5'

def upcoming(games, now):
    return sorted((g for g in games if g.get('status') == 'scheduled' and not g.get('ended') and g.get('starts_at')
                   and datetime.fromisoformat(g['starts_at']) > now), key=lambda g:(g['starts_at'],g['game_id']))

def choose(games, now):
    games = upcoming(games, now)
    date = min((data.jst_date(g['starts_at']) for g in games), default=None)
    return date, [g for g in games if data.jst_date(g['starts_at']) == date]

def collect(client, root, year, now):
    games=[];errors=[];complete={}
    for league in official.LEAGUES:
        try:
            found=official.fetch_next_games(client,year,league,now)
            games.extend(found);complete[league]=True
        except (ValueError,official.requests.RequestException) as exc:
            complete[league]=False;errors.append(official.LEAGUES[league][3]+': '+str(exc))
    date, selected=choose(games,now)
    state=dict(date=date,games=selected,schedule_complete=complete,errors=errors,retrieved_at=now.isoformat(),search_days=35,
               offline=bool(getattr(client,'offline',False)),other_dates={k:min((data.jst_date(g['starts_at']) for g in games if g['competition']==k),default=None) for k in official.LEAGUES},lineups={})
    if selected:
        state['lineups']=daily_lineups.collect(client,root,state)
        state['player_errors']=[official.LEAGUES[k][3]+': '+v['error'] for k,v in state['lineups'].items() if v.get('error')]
    return state

def valid_until(state):
    limits=[datetime.fromisoformat(g['starts_at']) for g in state.get('games',[]) if g.get('starts_at')]
    for stamp in [state.get('retrieved_at')]+[v.get('retrieved_at') for v in state.get('lineups',{}).values()]:
        if stamp:limits.append(datetime.fromisoformat(stamp)+timedelta(hours=36))
    return min(limits) if limits else datetime.min.replace(tzinfo=data.JST)

def load(root, now):
    path=Path(root)/'data/match_articles/next-preview.json'
    if not path.exists():return None
    state=json.loads(path.read_text())
    # Never advertise a selection whose population has changed after tipoff.
    if not state.get('games') or len(upcoming(state['games'],now))!=len(state['games']):return None
    if now >= valid_until(state):return None
    return state

def render(state, now):
    body='<div class="breadcrumb"><a href="index.html">ホーム</a> ／ 次の試合</div><header class="preview-heading"><p class="phase-label">試合前 ／ 今季平均 EFF</p><h1>'+TITLE+'</h1>'
    if state.get('date'):
        body+='<p class="fixture-date">'+('確認できた次の開催日' if state['errors'] else '次の開催日')+' <strong>'+state['date']+'</strong>（日本時間）</p>'
    body+='<p class="note">登録選手から選出しています。試合当日のエントリー・出場を確約するものではありません。</p></header>'
    if not state.get('games'):
        body+='<p class="empty-games">'+('次の日程を確認中です。' if state['errors'] else '35日以内に確認できる次の日程はありません。日程未発表の場合もあります。')+'</p>'
    else:
        body+=day_articles.lineup_html(state, heading=False)
        body+='<section class="next-fixtures"><h2>対象の試合</h2>'
        for league in official.LEAGUES:
            games=[g for g in state['games'] if g['competition']==league]
            if not games:continue
            body+='<h3>'+official.LEAGUES[league][3]+'</h3><ul>'
            for g in games:
                body+='<li>'+datetime.fromisoformat(g['starts_at']).astimezone(data.JST).strftime('%H:%M')+' '+articles.link(g['source'],g['home']+' vs '+g['away'])+'</li>'
            body+='</ul>'
        body+='</section>'
    body+='<p><a href="cat-kekka.html">試合結果・当日の EFFを見る →</a></p><details class="match-notes"><summary>出典・選出ルール・注記</summary><p>登録は当日のエントリー・出場確定を意味しません。対象試合の現在登録選手を、取得時点の公式今季平均EFFで選出しています。</p><p>公式IL登録中・平均未確認の選手は除外。PG→SG→SF→PF→Cの順でベスト5、残りからサブ5を選びます。同一選手は1枠、同値は選手ID順です。</p>'
    for league,result in state.get('lineups',{}).items():
        if result.get('retrieved_at'):body+='<p>'+official.LEAGUES[league][3]+' 選手資料取得：'+datetime.fromisoformat(result['retrieved_at']).astimezone(data.JST).strftime('%Y-%m-%d %H:%M JST')+'</p>'
        for team in result.get('teams',[]):
            for _,p in team:
                if p and p.get('il_removed_date'):body+='<p>'+articles.esc(p['name'])+'：'+articles.link(p['il_source'],'IL抹消 '+p['il_removed_date'])+'・現在登録を確認、出場未確認</p>'
        for source in result.get('sources',[]):body+='<p>'+articles.link(source,articles.source_label(source))+'</p>'
    for league,date in state.get('other_dates',{}).items():
        body+='<p>'+official.LEAGUES[league][3]+'：'+(date+' が次の開催日' if date else ('日程未確認' if not state['schedule_complete'].get(league) else '35日以内の次日程なし・未発表を含む'))+'</p>'
    if state.get('errors'):body+='<p>一部リーグの日程を確認できていません。対象日より近い試合がある可能性があります。</p>'
    body+='<p>日程確認：'+now.strftime('%Y-%m-%d %H:%M JST')+'。検索範囲は35日先まで。</p><p>'+articles.link('injury.html','IL・解除再登録情報')+'</p>'
    body+=' ／ '.join(articles.link(official.BASE+'/schedule/?tab='+str(v[0]),v[3]+'公式日程') for v in official.LEAGUES.values())+'</details>'
    if state.get('offline'):body='<p class="note">保存データによるローカル検証版です。</p>'+body
    html=stats.page(TITLE,'次の開催日の登録選手を今季平均EFFで比較','next-games.html',body).replace('<article class="article">','<article class="article match-article next-preview"'+(' data-preview-valid-until="'+valid_until(state).isoformat()+'"' if state.get('games') else '')+'>')
    html=html.replace('</body>','<script src="next-preview.js" defer></script></body>')
    if state.get('offline'):html=html.replace('</head>','<meta name="robots" content="noindex,nofollow"></head>')
    return html

def write(root,state,now):
    path=Path(root)/'data/match_articles/next-preview.json';path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(state,ensure_ascii=False,indent=2,default=str))
    (Path(root)/'next-games.html').write_text(render(state,now))

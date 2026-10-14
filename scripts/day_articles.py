"""One dated article for all three leagues, with schedules, results and average EFF."""
import json
from datetime import datetime
from pathlib import Path
try:
    from . import official_data as official, preview_data as data, match_articles as articles, daily_lineups
except ImportError:
    import official_data as official
    import preview_data as data
    import match_articles as articles
    import daily_lineups


def filename(date):
    return 'article-games-' + date.replace('-', '') + '.html'


def collect(client, year, date):
    games, complete, sources, errors = [], {}, [], []
    for league in official.LEAGUES:
        try:
            found, done, url, problems = official.fetch_day(client, year, league, date)
            games.extend(found); complete[league] = done; sources.append(url); errors.extend(problems)
        except (ValueError, official.requests.RequestException) as exc:
            complete[league] = False; errors.append(str(exc))
    summary = data.daily_results(games, date=date, season=f'{year}-{str(year+1)[-2:]}', competitions=official.LEAGUES, schedule_complete=complete)
    summary.update(schedule_complete=complete, sources=sources, errors=errors)
    return summary


def label(summary):
    return '試合結果・予定' if any(data.is_verified_final(g) for g in summary['games']) else '試合予定'


def lineup_html(summary):
    if not summary.get('lineups'):
        return ''
    body = '<section class="daily-lineups"><h2>この日のベスト5・サブ5</h2><p class="candidate-label">今季平均EFF（取得時点）・出場未確認</p>'
    for league, result in summary['lineups'].items():
        body += '<h3>' + official.LEAGUES[league][3] + '</h3>'
        if result.get('error'):
            body += '<p class="note">選手データ確認中：'+articles.esc(result['error'])+'</p>'
            continue
        for title, team in zip(('ベスト5','サブ5'),result['teams']):
            body += '<h4>'+title+'</h4><div class="tablewrap"><table><tr><th>位置</th><th>選手・所属</th><th>平均EFF</th><th>試合数</th></tr>'
            for position, player in team:
                if player is None:
                    body += '<tr><td>'+position+'</td><td colspan="3">確認済み候補なし</td></tr>'
                else:
                    body += '<tr><td>'+position+'</td><td><strong>'+articles.esc(player['name'])+'</strong><br><small>'+articles.esc(player['team'])+'</small></td><td>'+articles.esc(player['average'])+'</td><td>'+str(player['games'])+'</td></tr>'
            body += '</table></div>'
    return body+'</section>'


def render(summary, preview_root, preview_names, updated):
    date=summary['date'];name=filename(date)
    finished=any(data.is_verified_final(g) for g in summary['games'])
    title=date[5:].replace('-','/')+(' 試合結果・ベスト5' if finished else ' 試合予定・ベスト5')
    body='<section class="daily-results"><h2>'+('試合結果' if finished else '試合予定')+'</h2>'
    sources=list(summary['sources'])
    empty=[]
    for league,settings in official.LEAGUES.items():
        games=[g for g in summary['games'] if g['competition']==league]
        if not summary['schedule_complete'].get(league):
            body+='<p class="note schedule-warning">'+settings[3]+'：日程・結果を確認中</p>'
        elif not games:
            empty.append(settings[3])
        if not games:continue
        body+='<h3 id="league-'+league.lower()+'">'+settings[3]+'</h3>'
        for g in games:
            sources.append(g['source'])
            if data.is_verified_final(g):
                status=f"{g['home_score']} – {g['away_score']}"
                state='終了'
            elif g['status'] in ('cancelled','postponed'):
                status='—';state='中止' if g['status']=='cancelled' else '延期'
            else:
                status='—'
                state=(datetime.fromisoformat(g['starts_at']).astimezone(data.JST).strftime('%H:%M') if g.get('starts_at') else '時刻未確認')+' 予定・結果未確定'
            body+='<a class="daily-score" id="game-'+articles.esc(g['game_id'])+'" href="'+articles.esc(g['source'])+'"><span>'+articles.esc(g['home'])+'</span><strong>'+articles.esc(status)+'</strong><span>'+articles.esc(g['away'])+'</span><small>'+state+'</small></a>'
    body+='</section>'+lineup_html(summary)
    body+='<details class="match-notes"><summary>出典・選出ルール・注記</summary>'
    body+='<p>当日の対戦チームの現在登録選手から、取得時点の今季平均EFFで選びます。当日の試合だけの評価や、試合前時点の記録ではありません。</p>'
    body+='<p>PG→SG→SF→PF→Cの順に上位を割り当て、残りからサブ5を選出します。同じ選手は1枠、同じ平均値は選手ID順です。</p>'
    body+='<p>リーグ間は比較しません。公式IL登録中・平均未確認の選手は除外します。出場確定を示す選出ではありません。</p>'
    body+='<p>EFFは公式の1試合当たり平均です。通算合計からの再計算はしません。所属・ILも資料取得時点の情報です。</p>'
    if empty:body+='<p>この日試合なし：'+articles.esc('・'.join(empty))+'</p>'
    for league,result in summary.get('lineups',{}).items():
        sources.extend(result.get('sources',[]))
        if result.get('retrieved_at'):
            stamp=datetime.fromisoformat(result['retrieved_at']).astimezone(data.JST).strftime('%Y-%m-%d %H:%M JST')
            body+='<p>'+official.LEAGUES[league][3]+' 選手・平均資料取得：'+stamp+'</p>'
        for team in result.get('teams',[]):
            for _,player in team:
                if player and player.get('il_removed_date'):
                    body+='<p>'+articles.esc(player['name'])+'：'+articles.link(player['il_source'],'IL抹消 '+player['il_removed_date'])+'・出場未確認</p>'
    for g in summary['games']:
        preview='article-preview-'+g['game_id']+'.html'
        if preview in preview_names and (Path(preview_root)/preview).exists():
            soup=official.BeautifulSoup((Path(preview_root)/preview).read_text(),'html.parser')
            rank=soup.select_one('.match-rankings')
            if rank:
                sources.extend(a['href'] for a in soup.select('.source a[href]'))
                body+='<details class="day-rankings"><summary>'+articles.esc(g['home']+' vs '+g['away'])+' ポジション別平均</summary>'+str(rank)+''.join(str(n) for n in soup.select('.preview-warning'))+'<a href="'+preview+'">個別プレビュー</a></details>'
    body+='</details><p><a href="cat-kekka.html">日付別の試合結果</a> ／ <a href="injury.html">IL一覧</a></p>'
    category='kekka' if finished else 'data'
    html=articles.page(title,date,category,body,name,sources,updated)
    html=html.replace('<span>'+date.replace('-','.')+'</span>','<span>試合日 '+date.replace('-','.')+'</span>',1)
    import re
    html=re.sub(r'<img class="eyecatch"[^>]*>\s*','',html,count=1)
    return name,html


def sync_alias(root, date, html):
    legacy = root / ('article-results-one-next-' + date.replace('-', '') + '.html')
    if not legacy.exists():
        return
    soup = official.BeautifulSoup(html, 'html.parser')
    for node in soup.select('link[rel="canonical"], meta[name="article-alias"]'):
        node.decompose()
    soup.head.append(soup.new_tag('link', attrs={'rel':'canonical','href':'https://basuke-matome.jp/' + filename(date)}))
    soup.head.append(soup.new_tag('meta', attrs={'name':'article-alias','content':filename(date)}))
    legacy.write_text(str(soup), encoding='utf-8')


def write(client, root, summary, previews, updated):
    root = Path(root)
    state_path = root / 'data/match_articles' / filename(summary['date']).replace('.html','.json')
    if state_path.exists():
        prior = json.loads(state_path.read_text())
        old = {g['game_id'] for g in prior['games']}; new = {g['game_id'] for g in summary['games']}
        if old-new and not all(summary['schedule_complete'].values()):
            existing = root / filename(summary['date'])
            if existing.exists():
                soup = official.BeautifulSoup(existing.read_text(), 'html.parser')
                if not soup.select_one('#day-fetch-warning'):
                    warning = soup.new_tag('div', attrs={'class':'note', 'id':'day-fetch-warning'})
                    warning.string = '最新の取得が未完了のため、前回確認済みの試合情報を保持しています。公式日程をご確認ください。'
                    soup.select_one('article').insert(0, warning)
                    existing.write_text(str(soup), encoding='utf-8')
                sync_alias(root, summary['date'], str(soup))
            return None  # retain known games rather than silently losing a failed league
    summary['lineups'] = daily_lineups.collect(client, root, summary)
    name, html = render(summary, root, previews, updated)
    annotated = articles.readable_match(articles.annotate_provenance(html,client))
    (root/name).write_text(annotated,encoding='utf-8')
    articles.write_thumbnail(root,name,label(summary),'3リーグの試合情報',summary['date'])
    state_path.parent.mkdir(parents=True,exist_ok=True)
    state_path.write_text(json.dumps(summary,ensure_ascii=False,indent=2,default=str),encoding='utf-8')
    sync_alias(root, summary['date'], annotated)
    return name

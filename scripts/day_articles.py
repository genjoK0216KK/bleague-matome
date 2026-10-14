"""One dated article for all three leagues, with schedules, results and average EFF."""
import json
from datetime import datetime
from pathlib import Path
try:
    from . import official_data as official, preview_data as data, match_articles as articles, daily_lineups, game_day_rankings
except ImportError:
    import official_data as official
    import preview_data as data
    import match_articles as articles
    import daily_lineups
    import game_day_rankings


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


def lineup_html(summary, heading=True):
    if not summary.get('lineups'):
        return ''
    body = '<section class="daily-lineups preview-selection" id="daily-lineups">'
    if heading: body += '<p class="phase-label">試合前 ／ 今季平均 EFF</p><h2>出場予定選手（登録選手）のベスト5</h2><p class="fixture-date">対象日：'+articles.esc(summary['date'])+'</p>'
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


def game_eff_html(summary):
    leagues=summary.get('game_day_rankings',{}).get('leagues',{})
    if not leagues:return ''
    body='<section class="game-eff" id="game-eff"><p class="phase-label result-label">試合結果 ／ 当日の EFF</p><h2>当日のEFF・ポジション別TOP3</h2><p class="candidate-label">実際に出場した選手・公式試合スタッツ</p>'
    for league,result in leagues.items():
        body+='<h3>'+official.LEAGUES[league][3]+'</h3>'
        if result.get('error'):
            body+='<p class="game-eff-pending">'+articles.esc(result['error'])+'。確定後に掲載します。</p>'
            continue
        for position,rows in result['positions'].items():
            body+='<h4>'+position+'</h4>'
            if not rows:
                body+='<p>対象の出場選手なし</p>';continue
            body+='<div class="tablewrap" tabindex="0" aria-label="'+position+' 当日EFF順位表"><table><thead><tr><th scope="col">位</th><th scope="col">選手・所属</th><th scope="col">得点</th><th scope="col">REB</th><th scope="col">AST</th><th scope="col">EFF</th></tr></thead><tbody>'
            for player in rows:
                body+='<tr><td>'+str(player['rank'])+'</td><td><strong>'+articles.esc(player['name'])+'</strong><small>'+articles.esc(player['team']+'・'+'/'.join(player['positions']))+'</small></td>'
                body+=''.join('<td>'+str(player[k])+'</td>' for k in ('pts','reb','ast','eff'))+'</tr>'
            body+='</tbody></table></div>'
    return body+'</section>'


def render(summary, preview_root, preview_names, updated):
    date=summary['date'];name=filename(date)
    finished=any(data.is_verified_final(g) for g in summary['games'])
    title=date[5:].replace('-','/')+(' 試合結果・当日のEFF' if finished else ' 出場予定選手（登録選手）のベスト5' if summary['games'] else ' 試合なし' if all(summary.get('schedule_complete',{}).get(k) for k in official.LEAGUES) else ' 日程未確認')
    if finished: summary=dict(summary,lineups={})
    body='<nav class="article-jumps" aria-label="記事内の移動"><a href="#daily-results">試合</a>'
    if summary.get('game_day_rankings',{}).get('leagues'):body+='<a href="#game-eff">当日TOP3</a>'
    if summary.get('lineups'):body+='<a href="#daily-lineups">今季平均</a>'
    body+='</nav>'
    body+='<section class="daily-results" id="daily-results"><h2>'+('試合結果' if finished else '試合予定')+'</h2>'
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
    if empty:body+='<p class="empty-games">この日試合なし：'+articles.esc('・'.join(empty))+'</p>'
    body+='</section>'+game_eff_html(summary)+lineup_html(summary)
    body+='<details class="match-notes"><summary>出典・選出ルール・注記</summary>'
    if summary.get('game_day_rankings',{}).get('leagues'):
        body+='<p>当日TOP3は全試合の公式記録確定後、出場時間がある選手の公式EFFでリーグ別・ポジション別に選出します。今季平均や予想とは別集計です。</p>'
        body+='<p>公式登録の兼任ポジションは各部門の対象です。同率は同順位、同率内は選手IDの昇順で最大3人を表示します。ポジションは資料取得時点の公式登録で、当日の起用位置を断定しません。未取得値は0に置き換えません。</p>'
        body+='<p>EFF＝得点＋REB＋AST＋ST＋BS＋被ファウル－TO－被ブロック－ファウル－外した2P・3P・FT。順位には公式配信EFFを使用し、内訳からの再計算で置き換えません。<a href="https://www.bleague.jp/glossary/">公式用語集</a></p>'
        for result in summary['game_day_rankings']['leagues'].values():
            sources.extend(result.get('sources',[]))
            if result.get('position_retrieved_at'):body+='<p>当日TOP3のポジション資料取得：'+datetime.fromisoformat(result['position_retrieved_at']).astimezone(data.JST).strftime('%Y-%m-%d %H:%M JST')+'</p>'
            if result.get('formula_differences'):
                body+='<p>公式EFFと内訳算式の差を確認した記録：'+articles.esc('、'.join(p['name']+'（公式'+str(p['eff'])+'／内訳'+str(p['formula_value'])+'）' for p in result['formula_differences']))+'。公式配信値を優先しています。</p>'
    if summary.get('lineups'):
        body+='<p>今季平均ベスト5・サブ5は、当日の対戦チームの現在登録選手から、取得時点の今季平均EFFで選びます。当日の試合だけの評価や、試合前時点の記録ではありません。</p>'
    if summary.get('lineups'):
        body+='<p>PG→SG→SF→PF→Cの順に上位を割り当て、残りからサブ5を選出します。同じ選手は1枠、同じ平均値は選手ID順です。</p>'
    if summary.get('lineups'):
        body+='<p>リーグ間は比較しません。公式IL登録中・平均未確認の選手は除外します。出場確定を示す選出ではありません。</p>'
    if summary.get('lineups'):
        body+='<p>今季平均の表では、公式の1試合当たり平均EFFを使用します。通算合計からの再計算はしません。所属・ILも資料取得時点の情報です。</p>'
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


def write(client, root, summary, previews, updated, refresh_players=True):
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
    if refresh_players:
        summary['lineups'] = daily_lineups.collect(client, root, summary)
    elif state_path.exists():
        summary['lineups'] = json.loads(state_path.read_text()).get('lineups',{})
    else:
        summary['lineups'] = {}
    summary['game_day_rankings'] = game_day_rankings.collect(client if refresh_players else None, root, summary)
    name, html = render(summary, root, previews, updated)
    annotated = articles.readable_match(articles.annotate_provenance(html,client))
    (root/name).write_text(annotated,encoding='utf-8')
    articles.write_thumbnail(root,name,label(summary),'3リーグの試合情報',summary['date'])
    state_path.parent.mkdir(parents=True,exist_ok=True)
    state_path.write_text(json.dumps(summary,ensure_ascii=False,indent=2,default=str),encoding='utf-8')
    sync_alias(root, summary['date'], annotated)
    return name

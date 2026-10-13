"""One dated article for all three leagues, with schedules, results and average EFF."""
import json
from datetime import datetime
from pathlib import Path
try:
    from . import official_data as official, preview_data as data, match_articles as articles
except ImportError:
    import official_data as official
    import preview_data as data
    import match_articles as articles


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


def render(summary, preview_root, preview_names, updated):
    date = summary['date']; name = filename(date)
    title = date + ' 試合一覧・結果｜B.PREMIER・B.ONE・B.NEXT'
    body = '<p class="lead">この日の試合を3リーグに分けて掲載します。日付・開始時刻は日本時間です。試合前のポジション別ランキングは公式の今季平均EFF（1試合当たり）です。</p>'
    body += '<p><a href="next-games.html">日付別の試合一覧へ</a> ／ <a href="injury.html">IL・抹消情報を確認</a></p>'
    sources = list(summary['sources'])
    for league, settings in official.LEAGUES.items():
        body += '<section class="league-games" id="league-' + league.lower() + '"><h2>' + settings[3] + '</h2>'
        games = [g for g in summary['games'] if g['competition'] == league]
        if not summary['schedule_complete'].get(league):
            body += '<div class="note">日程・結果の取得が未完了です。試合なしとは断定できません。</div>'
        elif not games:
            body += '<p>この日の試合はありません。</p>'
        for g in games:
            sources.append(g['source'])
            body += '<section class="day-game" id="game-' + articles.esc(g['game_id']) + '"><h3>' + articles.esc(g['home'] + ' vs ' + g['away']) + '</h3>'
            if data.is_verified_final(g):
                status = f"{g['home_score']}－{g['away_score']}（公式記録確定）"
            elif g['status'] in ('cancelled','postponed'):
                status = '中止' if g['status']=='cancelled' else '延期'
            else:
                start = datetime.fromisoformat(g['starts_at']).astimezone(data.JST).strftime('%H:%M') if g.get('starts_at') else '開始時刻未確認'
                status = start + (' 予定・結果未確定' if g.get('status') == 'scheduled' else '・結果未確定')
            body += '<p class="game-status">' + articles.esc(status) + ' ／ ' + articles.link(g['source'],'公式試合詳細') + '</p>'
            preview = 'article-preview-' + g['game_id'] + '.html'
            if preview in preview_names and (Path(preview_root)/preview).exists():
                soup = official.BeautifulSoup((Path(preview_root)/preview).read_text(), 'html.parser')
                rank = soup.select_one('.match-rankings')
                if rank:
                    for h in rank.select('h2'): h.name = 'h4'
                    extra = ''.join(str(node) for node in soup.select('.preview-warning'))
                    return_heading = soup.find('h2', string='IL明け・登録情報')
                    if return_heading and return_heading.find_next_sibling('ul'):
                        extra += '<h4>IL明け・登録情報</h4>' + str(return_heading.find_next_sibling('ul'))
                    preview_sources = [a['href'] for a in soup.select('.source a[href]')]
                    source_note = '<p class="source">' + '<br>'.join(articles.link(url, articles.source_label(url)) for url in dict.fromkeys(preview_sources)) + '</p>'
                    body += '<details class="day-rankings"><summary>ポジション別・今季平均EFFを見る</summary><p>両チーム内の上位3人。同点で3人目に並ぶ選手も掲載します。出場試合数を併記し、出場未確認は確定出場を意味しません。</p>' + extra + str(rank) + source_note + '<p><a href="' + preview + '">個別プレビュー・全出典</a></p></details>'
            elif not data.is_verified_final(g) and g['status'] not in ('cancelled','postponed'):
                body += '<p class="note">平均EFFのプレビューは未取得です。</p>'
            body += '</section>'
        body += '</section>'
    html = articles.page(title, date, 'kekka', body, name, sources, updated)
    return name, html


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
    name, html = render(summary, root, previews, updated)
    annotated = articles.annotate_provenance(html,client)
    (root/name).write_text(annotated,encoding='utf-8')
    articles.write_thumbnail(root,name,'試合一覧','3リーグの試合一覧',summary['date'])
    state_path.parent.mkdir(parents=True,exist_ok=True)
    state_path.write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
    sync_alias(root, summary['date'], annotated)
    return name

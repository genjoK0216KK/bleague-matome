#!/usr/bin/env python3
"""Explicit local generation. No push, schedule changes, or implicit repository writes.

Example: python scripts/match_articles.py --date 2026-10-13 --season-year 2026
 --preview-game 506464 --output-root /tmp/site-preview --capture-dir /tmp/official-capture
Output is a separate directory; copy it over an isolated site clone and run build.py
for article-index/sitemap checks. Re-fetch on every online run to reflect corrections.
"""
import argparse
import json
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse, parse_qs

try:
    from . import official_data as official, preview_data as data, stats, thumbgen
except ImportError:
    import official_data as official
    import preview_data as data
    import stats
    import thumbgen

AVAILABILITY_LABELS = {'unknown': '出場未確認', 'unannounced': 'エントリー未発表',
                       'entry_confirmed': 'エントリー確認済（出場保証ではありません）',
                       'expected': '公式の出場見込み', 'out': '公式欠場・IL登録', 'suspended': '公式出場停止'}
EXCLUSIONS = {'out': '公式欠場・IL・停止', 'no_appearance': '今季未出場（公式G=0）',
              'total_unverified': '通算記録未確認', 'scope_mismatch': '集計範囲不一致',
              'position_unknown': '登録ポジション未確認', 'position_unverified': 'ポジション出典未確認',
              'total_invalid': '通算記録未確認'}
esc = stats.esc


def link(url, label):
    return f'<a href="{esc(url)}" target="_blank" rel="noopener nofollow">{esc(label)}</a>'


def source_label(url):
    parsed = urlparse(url)
    query = parse_qs(parsed.query)
    if parsed.path == '/stats/':
        return '公式スタッツ（今季合計・EFF）'
    if parsed.path == '/schedule/':
        label = {'1': 'B.PREMIER', '2': 'B.ONE', '3': 'B.NEXT'}.get(query.get('tab', [''])[0], '')
        return label + ' 公式日程・結果'
    if parsed.path == '/game_detail/':
        return '公式試合詳細'
    if parsed.path == '/club_detail/':
        return '公式クラブ登録選手一覧'
    if parsed.path == '/news/injury.html':
        return '公式インジュアリーリスト'
    if parsed.path == '/glossary/':
        return '公式用語集・EFF定義'
    return 'B.LEAGUE公式発表'


def page(title, date, category, body, filename, sources, updated):
    label = '試合結果' if category == 'kekka' else '順位・日程'
    source_html = '<br>'.join(link(url, source_label(url)) for url in dict.fromkeys(sources))
    content = f'''<div class="breadcrumb"><a href="index.html">ホーム</a> ／ <a href="cat-{category}.html">{label}</a></div>
<h1>{esc(title)}</h1><div class="pmeta"><span class="tag {category}">{label}</span><span>{esc(date.replace('-', '.'))}</span><span>最終データ取得 {esc(updated)}</span></div>
<img class="eyecatch" src="{filename.replace("article-", "thumb-").replace(".html", ".svg")}" alt="{esc(title)}">
{body}
<p class="source">出典：B.LEAGUE公式<br>{source_html}</p>
<div class="note">公式記録・発表は訂正される場合があります。出場は保証されません。最新情報は公式サイトをご確認ください。</div>'''
    return stats.page(title, title, filename, content).replace('<article class="article">', '<article class="article match-article">')


def render_preview(game, players, *, updated, extra_sources=(), warnings=()):
    rankings = data.position_rankings(players, season=game['season'], competition=game['competition'], metric='EFF')
    title = f"{game['home']} vs {game['away']} 次戦プレビュー｜ポジション別・今季通算EFF"
    filename = f"article-preview-{game['game_id']}.html"
    date = data.jst_date(game['starts_at'])
    start = datetime.fromisoformat(game['starts_at']).astimezone(data.JST).strftime('%Y年%m月%d日 %H:%M JST')
    body = f'<p class="lead">{esc(start)}予定。{esc(official.LEAGUES[game["competition"]][3])} {esc(game["season"])} レギュラーシーズンの公式通算EFFで、両チームの現在登録選手を比較します。</p>'
    body += '<div class="note">現在の登録は当日のエントリー・出場確定を意味しません。出場情報を確認できない選手は「出場未確認」と表示します。各ポジション上位3人を表示します。同点で3人目に並ぶ選手も掲載します。複数ポジションは各表へ掲載し、同値は同順位とします。</div>'
    for warning in warnings:
        body += f'<p class="note">{esc(warning)}</p>'
    body += '<p><a href="injury.html">現在のIL・抹消／再登録情報を見る</a></p>'
    returned = [p for p in players if p.get('il_removed_date') and p.get('availability') != 'out']
    if returned:
        body += '<h2>IL明け・登録情報</h2><ul>'
        for p in returned:
            body += '<li>' + esc(p['name']) + '（' + esc(p['team']) + '）：' + esc(p['availability_detail']) + '。' + link(p['il_source'], '公式IL') + ' ／ ' + link(p['position_source'], '公式登録一覧') + '</li>'
        body += '</ul>'
    for position, rows in rankings['positions'].items():
        if len(rows) > 3:
            cutoff = rows[2]['total']
            rows = [p for p in rows if p['total'] >= cutoff]
        body += f'<h2>{position}｜今季通算EFF</h2>'
        if not rows:
            body += '<p>比較できる公式通算記録がありません。</p>'
            continue
        body += '<p class="table-hint">表は横にスクロールできます。出場状況もご確認ください。</p>'
        body += '<div class="tablewrap"><table><tr><th>順位</th><th>選手（所属）</th><th>通算EFF</th><th>出場試合数</th><th>出場状況</th></tr>'
        for p in rows:
            availability = AVAILABILITY_LABELS[p['availability']]
            if p.get('il_removed_date'):
                availability = 'IL抹消 ' + p['il_removed_date'] + '・' + availability
            if p.get('availability_source'):
                availability = link(p['availability_source'], availability)
            body += (f'<tr><td>{p["rank"]}</td><td>{esc(p["name"])}（{esc(p["team"])}）</td>'
                     f'<td>{esc(p["total"])}</td><td>{esc(p.get("games", "未確認"))}</td><td>{availability}</td></tr>')
        body += '</table></div>'
    if rankings['excluded']:
        body += '<h2>欠場情報・ランキング対象外</h2><ul>'
        for p in rankings['excluded']:
            body += f'<li>{esc(p["name"])}（{esc(p["team"])}）：{esc(EXCLUSIONS[p["exclusion_reason"]])}。{esc(p.get("availability_detail", ""))}</li>'
        body += '</ul>'
    body += '<p>通算EFFは公式の合計列を使用し、平均EFF×試合数では計算しません。移籍選手は同一リーグの公式TOTALが確認できた場合に採用し、所属別記録と二重加算しません。</p>'
    sources = [game['source'], official.BASE + '/glossary/'] + list(extra_sources)
    sources += [p[k] for p in players for k in ('position_source', 'stats_source', 'availability_source') if p.get(k)]
    return filename, page(title, date, 'data', body, filename, sources, updated)


def verified_recent_returns(players, confirmations, as_of):
    """Yearless history is not a recent return without separately dated evidence."""
    for p in players:
        if not p.get('il_removed_date'):
            continue
        note = confirmations.get(p['player_id'], {})
        try:
            removed = datetime.fromisoformat(note['removed_date']).date()
            literal = f'{removed.month}月{removed.day}日'
            verified = (note.get('team_id') == p.get('team_id')
                        and p['il_removed_date'] == literal
                        and 0 <= (as_of.astimezone(data.JST).date() - removed).days <= 30
                        and note.get('source', '').startswith('https://'))
        except (KeyError, ValueError):
            verified = False
        if verified:
            p['il_removed_date'] = removed.isoformat()
            p['il_source'] = note['source']
            p['availability_detail'] = '公式にIL抹消（' + removed.isoformat() + '）。現在の公式登録一覧に掲載。次戦の出場は未確認'
        else:
            for key in ('il_removed_date', 'il_source', 'availability_detail'):
                p.pop(key, None)


def render_results(summary, *, season, updated, schedule_sources):
    date = summary['date']
    filename = summary['article_key'] + '.html'
    title = f'{date} B.ONE・B.NEXT 試合結果まとめ'
    if summary['status'] == 'pending':
        title += '（途中版）'
    body = '<p class="lead">B.ONE・B.NEXTの当日結果を1記事にまとめます。日付は日本時間、対象は' + esc(season) + 'レギュラーシーズンです。</p>'
    if summary['status'] == 'pending':
        body += '<div class="note">途中版：未確定の試合または取得できていない記録があります。最終結果として扱わず、次回取得時に同じ記事を更新します。</div>'
    for league in ('B1', 'BN'):
        body += '<h2>' + official.LEAGUES[league][3] + '</h2>'
        rows = [g for g in summary['games'] if g['competition'] == league]
        if not rows:
            body += '<p>' + ('この日の試合はありません。' if summary['schedule_complete'].get(league) else '日程を確認できていません。') + '</p>'
            continue
        body += '<div class="tablewrap"><table><tr><th>対戦</th><th>スコア</th><th>記録状態</th></tr>'
        for g in rows:
            status = g.get('status', 'unconfirmed')
            labels = {'cancelled': '中止', 'postponed': '延期', 'final': '確定', 'unconfirmed': '未確定', 'scheduled': '未開催'}
            if status == 'final' and not data.is_verified_final(g):
                status = 'unconfirmed'
            score = f'{g["home_score"]}－{g["away_score"]}' if data.is_verified_final(g) else '—'
            body += f'<tr><td>{link(g["source"], g["home"] + " vs " + g["away"])}</td><td>{esc(score)}</td><td>{labels.get(status, "未確認")}</td></tr>'
        body += '</table></div>'
    if summary['individual_candidates']:
        body += '<h2>特筆事項</h2><ul>'
        for g in summary['individual_candidates']:
            body += f'<li><a href="article-result-highlight-{esc(g["game_id"])}.html">{esc(g["notable_reason"])}</a>（{link(g["notable_source"], "公式出典")}）</li>'
        body += '</ul>'
    sources = list(schedule_sources) + [g['source'] for g in summary['games']]
    return filename, page(title, date, 'kekka', body, filename, sources, updated)


def render_notable(game, *, date, updated):
    if not data.is_verified_final(game):
        raise official.DataError('Individual result requires verified final scores')
    name = f"article-result-highlight-{game['game_id']}.html"
    title = f"{game['home']} vs {game['away']}｜{game['notable_reason']}"
    body = (f'<p class="lead">{esc(game["notable_reason"])}</p>'
            f'<h2>公式の試合結果</h2><p>{esc(game["home"])} {game["home_score"]}－{game["away_score"]} {esc(game["away"])}</p>'
            f'<p><a href="article-results-one-next-{date.replace("-", "")}.html">この日のB.ONE・B.NEXT全結果</a></p>')
    return name, page(title, date, 'kekka', body, name, [game['source'], game['notable_source']], updated)


def write_thumbnail(output, filename, label, teams, date):
    svg = thumbgen.render(dict(type='news', label=label, team=teams, headline='試合結果まとめ' if label == '試合結果' else '今季通算EFF', sub=date, facts=[]))
    (output / filename.replace('article-', 'thumb-').replace('.html', '.svg')).write_text(svg, encoding='utf-8')


def annotate_provenance(html, client):
    """Article-specific retrieval times; offline captures never masquerade as live."""
    soup = official.BeautifulSoup(html, 'html.parser')
    times = {item['url']: item['retrieved_at'] for item in client.sources}
    relevant = []
    for anchor in soup.select('.source a[href]'):
        timestamp = times.get(anchor['href'])
        if timestamp:
            moment = datetime.fromisoformat(timestamp).astimezone(data.JST)
            relevant.append(moment)
            anchor.insert_after('（取得 ' + moment.strftime('%Y-%m-%d %H:%M JST') + '）')
        else:
            anchor.insert_after('（取得時刻未記録）')
    metadata = soup.select_one('.pmeta')
    if metadata:
        spans = metadata.find_all('span', recursive=False)
        if relevant and spans:
            spans[-1].string = ('資料取得 ' + min(relevant).strftime('%Y-%m-%d %H:%M')
                               + '〜' + max(relevant).strftime('%Y-%m-%d %H:%M JST'))
        elif spans:
            spans[-1].string = '資料の取得時刻未確認'
    if client.offline:
        article = soup.select_one('article')
        note = soup.new_tag('div', attrs={'class': 'note'})
        note.string = '保存した公式データを使用したローカル検証版です。現在の試合・出場状況を示すものではありません。'
        article.insert(0, note)
        robots = soup.new_tag('meta', attrs={'name': 'robots', 'content': 'noindex,nofollow'})
        soup.head.append(robots)
    return str(soup)


def source_time(client, fallback):
    times = [s['retrieved_at'] for s in client.sources]
    return datetime.fromisoformat(max(times)).astimezone(data.JST).strftime('%Y-%m-%d %H:%M JST') if times else fallback


def generate(client, *, year, date, preview_keys, output, editorial=None, as_of=None):
    as_of = as_of or datetime.now(data.JST)
    if as_of.tzinfo is None:
        raise official.DataError('Timezone-aware as_of required')
    output = Path(output)
    # Standalone generator can only write to an explicit directory, never default to ROOT.
    output.mkdir(parents=True, exist_ok=True)
    season = f'{year}-{str(year+1)[-2:]}'
    updated = datetime.now(data.JST).strftime('%Y-%m-%d %H:%M JST')
    games, complete, sources, errors = [], {}, [], []
    for league in ('B1', 'BN'):
        try:
            found, done, url, problems = official.fetch_day(client, year, league, date)
            games.extend(found); complete[league] = done; sources.append(url); errors.extend(problems)
        except (ValueError, official.requests.RequestException) as exc:
            complete[league] = False; errors.append(f'{league}: {exc}')
    for game in games:
        note = (editorial or {}).get(game['game_id'])
        if note:
            if not note.get('reason') or not note.get('source', '').startswith('https://www.bleague.jp/'):
                raise official.DataError('Notable games require an editorial reason and official evidence URL')
            # Editorial file is explicit local input; fetching verifies source availability,
            # while the editor remains responsible for the semantic fact check.
            client.get(note['source'])
            game.update(notable_reason=note['reason'], notable_source=note['source'])
    summary = data.daily_results(games, date=date, season=season, competitions=('B1', 'BN'), schedule_complete=complete)
    summary['schedule_complete'] = complete
    artifacts, removed = [], []
    state_path = output / (summary['article_key'] + '.json')
    prior = json.loads(state_path.read_text()) if state_path.exists() else None
    if prior and (prior.get('date') != date or prior.get('article_key') != summary['article_key']):
        raise official.DataError('Saved result state identity mismatch')
    current_highlights = {g['game_id'] for g in summary['individual_candidates']}
    prior_highlights = set(prior.get('managed_highlights', [g['game_id'] for g in prior.get('individual_candidates', [])])) if prior else set()
    summary['managed_highlights'] = sorted(current_highlights if all(complete.values()) else prior_highlights | current_highlights)
    # Remove only this generator's previously recorded artifacts, and only after
    # the full official schedule was retrieved. Empty editorial means withdrawn.
    if all(complete.values()) and prior:
        stale = [f'article-result-highlight-{key}.html' for key in sorted(prior_highlights - current_highlights)]
        if summary['status'] == 'no_games':
            stale.append(summary['article_key'] + '.html')
        for filename in stale:
            for item in (filename, filename.replace('article-', 'thumb-').replace('.html', '.svg')):
                path = output / item
                if path.exists():
                    path.unlink(); removed.append(item)
        if summary['status'] == 'no_games':
            state_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding='utf-8')
    if summary['games'] or summary['status'] == 'pending':
        name, html = render_results(summary, season=season, updated=source_time(client, updated), schedule_sources=sources)
        # If a transient network failure loses previously known games, preserve the old
        # article instead of replacing verified results with an empty/incomplete subset.
        old_ids = {g['game_id'] for g in prior['games']} if prior else set()
        new_ids = {g['game_id'] for g in summary['games']}
        if old_ids - new_ids and not all(complete.values()):
            errors.append('Results preserved: incomplete fetch lost known games')
        else:
            (output / name).write_text(annotate_provenance(html, client), encoding='utf-8')
            state_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding='utf-8')
            write_thumbnail(output, name, '試合結果', 'B.ONE・B.NEXT', date)
            artifacts.append(name)
    for game in summary['individual_candidates']:
        name, html = render_notable(game, date=date, updated=updated)
        (output / name).write_text(annotate_provenance(html, client), encoding='utf-8')
        write_thumbnail(output, name, '試合結果', game['home'] + ' vs ' + game['away'], date)
        artifacts.append(name)
    confirmation_path = Path(__file__).resolve().parent.parent / 'data' / 'il-return-confirmations.json'
    return_confirmations = json.loads(confirmation_path.read_text()) if confirmation_path.exists() else {}
    totals_cache = {}
    for key in preview_keys:
        try:
            game = official.parse_game(client.get(f'{official.BASE}/game_detail/?ScheduleKey={key}'), key, year)
            if (game['ended'] or game['status'] in ('cancelled', 'postponed')
                    or datetime.fromisoformat(game['starts_at']) <= as_of):
                raise official.DataError('Cannot label a started/ended/cancelled game as next-game preview')
            league = game['competition']
            warnings = []
            if league not in totals_cache:
                totals_cache[league] = official.fetch_totals(client, year, league)
            totals = totals_cache[league]
            players = []
            for side in ('home', 'away'):
                players.extend(official.fetch_roster(client, game[side + '_id'], game[side], year, league))
            try:
                records = official.injury_records(client.get(official.BASE + '/news/injury.html'))
                active = [r for r in records if r['active']]
                removed_il_records = [r for r in records if not r['active']][:5]
                official.apply_injuries(client, players, active, game, removed_il_records)
            except (ValueError, official.requests.RequestException) as exc:
                warnings.append('公式IL情報の照合が未完了です。出場状況は個別の公式発表をご確認ください。')
                errors.append(str(exc))
            verified_recent_returns(players, return_confirmations, as_of)
            for p in players:
                total = totals.get(p['player_id'], {})
                p.update(metric='EFF', aggregation='total', total=total.get('total'),
                         games=total.get('games'), stats_source=total.get('stats_source'),
                         coverage_complete=bool(total))
            name, html = render_preview(game, players, updated=source_time(client, updated), warnings=warnings,
                                        extra_sources=[official.stats_url(year, league), official.BASE + '/news/injury.html'])
            (output / name).write_text(annotate_provenance(html, client), encoding='utf-8')
            write_thumbnail(output, name, '次戦プレビュー', game['home'] + ' vs ' + game['away'], data.jst_date(game['starts_at']))
            artifacts.append(name)
        except (ValueError, official.requests.RequestException) as exc:
            errors.append(f'Preview {key}: {exc}')
    report = {'artifacts': artifacts, 'removed': removed, 'errors': errors, 'results_status': summary['status'],
              'schedule_complete': complete, 'sources': client.sources, 'offline': client.offline}
    (output / 'generation-report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--date', required=True)
    parser.add_argument('--as-of', help='Timezone-aware historical cutoff; only allowed with --offline')
    parser.add_argument('--season-year', type=int, required=True)
    parser.add_argument('--preview-game', action='append', default=[])
    parser.add_argument('--next-league', choices=list(official.LEAGUES), action='append', default=[], help='Discover every game on the next scheduled date within 35 days')
    parser.add_argument('--output-root', required=True)
    parser.add_argument('--capture-dir')
    parser.add_argument('--offline', action='store_true')
    parser.add_argument('--editorial-json', help='Verified notable reasons keyed by ScheduleKey; never generated from score margins alone')
    args = parser.parse_args()
    client = official.Client(args.capture_dir, args.offline)
    if args.as_of and not args.offline:
        parser.error('--as-of is only allowed for offline reproduction')
    cutoff = datetime.fromisoformat(args.as_of) if args.as_of else datetime.now(data.JST)
    if cutoff.tzinfo is None:
        parser.error('--as-of requires a timezone')
    preview_keys = list(args.preview_game)
    for league in args.next_league:
        preview_keys.extend(g['game_id'] for g in official.fetch_next_games(client, args.season_year, league, cutoff))
    result = generate(client, year=args.season_year,
                      date=args.date, preview_keys=list(dict.fromkeys(preview_keys)), output=args.output_root, as_of=cutoff,
                      editorial=json.loads(Path(args.editorial_json).read_text()) if args.editorial_json else None)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 1 if result['errors'] else 0


if __name__ == '__main__':
    raise SystemExit(main())

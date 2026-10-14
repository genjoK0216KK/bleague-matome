#!/usr/bin/env python3
"""Bounded scheduled integration. Cron is unchanged; publish only managed outputs."""
import argparse
import json
import re
import shutil
import tempfile
from datetime import datetime, timedelta
from pathlib import Path
try:
    from . import official_data as official, preview_data as data, match_articles as articles, injury_page, stats, day_articles
except ImportError:
    import official_data as official
    import preview_data as data
    import match_articles as articles
    import injury_page
    import stats
    import day_articles

ROOT = Path(__file__).resolve().parent.parent
MANAGED = re.compile(r'(?:article-(?:results-one-next-\d{8}|result-highlight-\d+|preview-\d+)\.html|thumb-(?:results-one-next-\d{8}|result-highlight-\d+|preview-\d+)\.svg)$')


def promote(stage, root, report):
    for name in report['artifacts']:
        for item in (name, name.replace('article-', 'thumb-').replace('.html', '.svg')):
            if not MANAGED.fullmatch(item):
                raise official.DataError('Unmanaged artifact refused')
            shutil.copy2(stage / item, root / item)
    for item in report['removed']:
        if not MANAGED.fullmatch(item):
            raise official.DataError('Unmanaged removal refused')
        path = root / item
        if path.exists():
            path.unlink()


def render_next(now, tomorrow, day_states, games, errors):
    date = tomorrow.isoformat()
    body = '<div class="breadcrumb"><a href="index.html">ホーム</a> ／ 次戦</div><h1>明日の試合・次の開催日</h1><p>更新：' + now.strftime('%Y-%m-%d %H:%M JST') + '</p>'
    body += '<h2>' + date + '（日本時間・更新時点の翌日）の試合</h2>'
    for league, state in day_states.items():
        label = official.LEAGUES[league][3]
        if state is None:
            body += '<p>' + label + '：日程未確認</p>'
        elif not state:
            body += '<p>' + label + '：この日の試合はありません。</p>'
        else:
            body += '<h3>' + label + ' ' + str(len(state)) + '試合</h3><ul>'
            for game in state:
                start = datetime.fromisoformat(game['starts_at']).astimezone(data.JST).strftime('%H:%M') if game.get('starts_at') else '時刻未確認'
                body += '<li>' + articles.esc(start) + ' ' + articles.link(game['source'], game['home'] + ' vs ' + game['away']) + '</li>'
            body += '</ul>'
    dates = sorted({data.jst_date(g['starts_at']) for g in games} | {now.date().isoformat(), (now-timedelta(days=1)).date().isoformat()} | ({date} if now.hour >= 23 else set()))
    body += '<h2>日付別の試合一覧・結果</h2><ul>'
    for target_date in dates:
        body += '<li><a href="' + day_articles.filename(target_date) + '">' + target_date + ' 試合情報</a></li>'
    body += '</ul>'
    if errors:
        body += '<div class="note">一部の公式情報を取得できませんでした。日程・出場状況は公式ページをご確認ください。</div>'
    body += '<p class="source">' + ' ／ '.join(articles.link(official.BASE + '/schedule/?tab=' + str(official.LEAGUES[k][0]), official.LEAGUES[k][3] + '公式日程') for k in official.LEAGUES) + '</p>'
    return stats.page('明日の試合・次の開催日', 'JSTの明日の日程と次戦プレビュー', 'next-games.html', body)


def releasable_games(now, next_games, day_states):
    now = now.astimezone(data.JST)
    def on_date(g, date):
        return (g.get('status') not in ('cancelled','postponed') and bool(g.get('starts_at'))
                and data.jst_date(g['starts_at']) == date)
    eligible = [g for g in next_games if on_date(g, now.date().isoformat())]
    if now.hour >= 23:
        tomorrow = (now + timedelta(days=1)).date().isoformat()
        eligible += [g for state in day_states.values() for g in (state or [])
                     if on_date(g, tomorrow)]
    return list({g['game_id']:g for g in eligible}.values())


def run(root, client, year, now):
    now = now.astimezone(data.JST)
    root = Path(root); root.mkdir(parents=True, exist_ok=True)
    state_dir = root / 'data' / 'match_articles'; state_dir.mkdir(parents=True, exist_ok=True)
    errors = []
    il_error = injury_page.generate(client, root, state_dir / 'injury.json', now)
    if il_error:
        errors.append('IL: ' + il_error)
    editorial_path = root / 'data' / 'match-editorial.json'
    editorial = json.loads(editorial_path.read_text()) if editorial_path.exists() else {}
    tomorrow = (now + timedelta(days=1)).date()
    published = []
    with tempfile.TemporaryDirectory(prefix='bleague-match-') as temp:
        stage = Path(temp)
        for path in state_dir.glob('article-results-one-next-*.json'):
            shutil.copy2(path, stage / path.name)
        for path in root.iterdir():
            if path.is_file() and MANAGED.fullmatch(path.name):
                shutil.copy2(path, stage / path.name)

        def generate_and_promote(date, keys):
            try:
                report = articles.generate(client, year=year, date=date, preview_keys=keys, output=stage, editorial=editorial, as_of=now)
                promote(stage, root, report)
                errors.extend(report['errors']); published.extend(report['artifacts'])
                for key, bundle in report.get('player_data', {}).items():
                    (state_dir / ('players-'+key+'.json')).write_text(json.dumps(bundle, ensure_ascii=False, indent=2, default=str), encoding='utf-8')
                for path in stage.glob('article-results-one-next-*.json'):
                    shutil.copy2(path, state_dir / path.name)
            except (ValueError, official.requests.RequestException) as exc:
                errors.append(str(exc))

        # Secure current and prior-day results before expensive roster/profile work.
        for offset in (0, 1):
            generate_and_promote((now - timedelta(days=offset)).date().isoformat(), [])
        yesterday_summary = day_articles.collect(client,year,(now-timedelta(days=1)).date().isoformat())
        day_articles.daily_lineups.collect(client,root,yesterday_summary)
        day_states = {}
        for league in official.LEAGUES:
            try:
                games, complete, _, problems = official.fetch_day(client, year, league, tomorrow.isoformat())
                day_states[league] = games if complete else None
                errors.extend(problems)
            except (ValueError, official.requests.RequestException) as exc:
                errors.append(str(exc)); day_states[league] = None
        next_games = []
        order = sorted(official.LEAGUES, key=lambda league: not bool(day_states.get(league)))
        for league in order:
            try:
                next_games.extend(official.fetch_next_games(client, year, league, now))
            except (ValueError, official.requests.RequestException) as exc:
                errors.append('Next ' + league + ': ' + str(exc))
        # Tomorrow becomes public at the existing 23:00 JST run; fixed date keys prevent duplicates.
        next_games = releasable_games(now, next_games, day_states)
        generate_and_promote(now.date().isoformat(), [g['game_id'] for g in next_games])
        # Link only previews successfully generated in this run, not stale prior files.
        available = [g for g in next_games if f"article-preview-{g['game_id']}.html" in published]
        # One canonical article per actual date, with all three league sections.
        dates = sorted({now.date().isoformat(), (now-timedelta(days=1)).date().isoformat(), *( [tomorrow.isoformat()] if now.hour >= 23 else [])}
                       | {data.jst_date(g['starts_at']) for g in next_games})
        for target_date in dates:
            summary = day_articles.collect(client, year, target_date)
            errors.extend(summary['errors'])
            written = day_articles.write(client, root, summary, published, now.strftime('%Y-%m-%d %H:%M JST'))
            if written:
                published.append(written)
            else:
                errors.append('Dated article retained after incomplete fetch: ' + target_date)
        html = render_next(now, tomorrow, day_states, next_games, errors)
        if client.offline:
            html = html.replace('</head>', '<meta name="robots" content="noindex,nofollow"></head>').replace('<h1>', '<p class="note">保存データによるローカル検証版です。</p><h1>', 1)
        (root / 'next-games.html').write_text(html, encoding='utf-8')
    return {'errors': errors, 'artifacts': published, 'requests': client.request_count, 'sources': client.sources}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--season-year', type=int, required=True)
    parser.add_argument('--root', default=str(ROOT))
    parser.add_argument('--capture-dir')
    args = parser.parse_args()
    result = run(args.root, official.Client(args.capture_dir, max_requests=160, time_budget=480), args.season_year, datetime.now(data.JST))
    print(json.dumps(result, ensure_ascii=False, indent=2))
    # Failures are visible in Actions; successfully refreshed IL/results may still build.
    if result['errors']:
        print('::warning::Some official match data unavailable; check report above')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

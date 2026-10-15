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
    from . import official_data as official, preview_data as data, match_articles as articles, injury_page, stats, day_articles, next_preview, schedule_calendar
except ImportError:
    import official_data as official
    import preview_data as data
    import match_articles as articles
    import injury_page
    import stats
    import day_articles
    import next_preview
    import schedule_calendar

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
        preview = next_preview.collect(client, root, year, now)
        errors.extend(preview['errors']); errors.extend(preview.get('player_errors',[]))
        # Dated results remain distinct from the next-fixture preview.
        for target_date in sorted({now.date().isoformat(), (now-timedelta(days=1)).date().isoformat()}):
            summary = day_articles.collect(client, year, target_date)
            errors.extend(summary['errors'])
            written = day_articles.write(client, root, summary, [], now.strftime('%Y-%m-%d %H:%M JST'))
            if written: published.append(written)
            else: errors.append('Dated article retained after incomplete fetch: ' + target_date)
        next_preview.write(root, preview, now)
    return {'errors': errors, 'artifacts': published, 'requests': client.request_count, 'sources': client.sources}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--season-year', type=int, required=True)
    parser.add_argument('--root', default=str(ROOT))
    parser.add_argument('--capture-dir')
    args = parser.parse_args()
    result = run(args.root, official.Client(args.capture_dir, max_requests=160, time_budget=480), args.season_year, datetime.now(data.JST))
    # Calendar has its own bounded budget after existing results/EFF are secure.
    calendar_client = official.Client(args.capture_dir, max_requests=100, time_budget=300)
    calendar_report = schedule_calendar.update(calendar_client, args.root, args.season_year, datetime.now(data.JST))
    result['errors'].extend(calendar_report['errors'])
    result['requests'] += calendar_client.request_count
    result['sources'].extend(calendar_client.sources)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    # Failures are visible in Actions; successfully refreshed IL/results may still build.
    if result['errors']:
        print('::warning::Some official match data unavailable; check report above')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

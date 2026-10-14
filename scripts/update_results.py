#!/usr/bin/env python3
"""Refresh today's verified results only; no roster, news, GA4, or posting calls."""
import argparse
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path
try:
    from . import day_articles, official_data as official, preview_data as data
except ImportError:
    import day_articles
    import official_data as official
    import preview_data as data

ROOT = Path(__file__).resolve().parent.parent


def complete(summary):
    return all(summary.get('schedule_complete', {}).get(k) is True for k in official.LEAGUES)


def settled(summary):
    return bool(summary.get('games')) and complete(summary) and all(
        data.is_verified_final(g) or (g.get('status') in ('cancelled', 'postponed') and g.get('source'))
        for g in summary['games'])


def semantic(summary):
    """Only article inputs; retrieval timestamps alone never trigger publication."""
    keys = ('game_id', 'season', 'competition', 'starts_at', 'official_date', 'status',
            'ended', 'fixed', 'home', 'away', 'home_full', 'away_full', 'home_id',
            'away_id', 'home_score', 'away_score', 'source', 'players')
    return {'date': summary.get('date'), 'schedule_complete': summary.get('schedule_complete'),
            'games': sorted(({k: g.get(k) for k in keys} for g in summary.get('games', [])),
                            key=lambda g: g['game_id'])}


def run(root, client, year, now):
    root = Path(root)
    now = now.astimezone(data.JST)
    date = now.date().isoformat()
    path = root / 'data/match_articles' / day_articles.filename(date).replace('.html', '.json')
    prior = json.loads(path.read_text()) if path.exists() else None
    if prior and prior.get('date') != date:
        raise ValueError('Saved result date mismatch')
    if prior and settled(prior) and (root / day_articles.filename(date)).exists():
        return {'changed': False, 'reason': 'already_final', 'requests': client.request_count}
    summary = day_articles.collect(client, year, date)
    if summary.get('errors') or not complete(summary):
        raise ValueError('Official results incomplete; previous data retained')
    old = {g['game_id']: g for g in (prior or {}).get('games', [])}
    new = {g['game_id']: g for g in summary['games']}
    if old.keys() - new.keys():
        raise ValueError('Known games missing; previous data retained')
    if any(data.is_verified_final(g) and not data.is_verified_final(new[key]) for key, g in old.items()):
        raise ValueError('Verified result regressed; previous data retained')
    if not summary['games']:
        return {'changed': False, 'reason': 'no_games', 'requests': client.request_count}
    if prior and semantic(prior) == semantic(summary) and (root / day_articles.filename(date)).exists():
        return {'changed': False, 'reason': 'unchanged', 'requests': client.request_count}
    previews = [p.name for p in root.glob('article-preview-*.html')]
    written = day_articles.write(client, root, summary, previews,
                                 now.strftime('%Y-%m-%d %H:%M JST'), refresh_players=False)
    if not written:
        raise ValueError('Result rendering failed; build skipped')
    return {'changed': True, 'article': written, 'requests': client.request_count}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--season-year', required=True, type=int)
    parser.add_argument('--root', default=str(ROOT))
    args = parser.parse_args()
    try:
        report = run(args.root, official.Client(max_requests=70, time_budget=180), args.season_year,
                     datetime.now(data.JST))
        print(json.dumps(report, ensure_ascii=False))
        if report['changed']:
            subprocess.run([sys.executable, str(Path(args.root) / 'scripts/build.py')],
                           cwd=args.root, check=True)
        return 0
    except (ValueError, OSError, official.requests.RequestException, subprocess.CalledProcessError):
        print('::error::Result refresh failed; existing published data retained')
        return 1


if __name__ == '__main__':
    raise SystemExit(main())

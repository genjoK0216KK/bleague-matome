#!/usr/bin/env python3
"""Refresh results and roll over expired next-fixture previews; no news, GA4, or posting calls."""
import argparse
import json
import os
import subprocess
import sys
import traceback
from datetime import datetime, timedelta
from pathlib import Path
try:
    from . import day_articles, official_data as official, preview_data as data, refresh_next_preview, result_status
except ImportError:
    import result_status
    import day_articles
    import official_data as official
    import preview_data as data
    import refresh_next_preview

ROOT = Path(__file__).resolve().parent.parent


def complete(summary):
    return all(summary.get('schedule_complete', {}).get(k) is True for k in official.LEAGUES)


def settled(summary):
    """A date with games that needs no further official reads (results AND EFF TOP3)."""
    return bool(summary.get('games')) and done(summary)


def semantic(summary):
    """Only article inputs; retrieval timestamps alone never trigger publication."""
    keys = ('game_id', 'season', 'competition', 'starts_at', 'official_date', 'status',
            'ended', 'fixed', 'home', 'away', 'home_full', 'away_full', 'home_id',
            'away_id', 'home_score', 'away_score', 'source', 'players')
    return {'date': summary.get('date'), 'schedule_complete': summary.get('schedule_complete'),
            'games': sorted(({k: g.get(k) for k in keys} for g in summary.get('games', [])),
                            key=lambda g: g['game_id'])}


LOOKBACK_DAYS = 3  # past JST dates re-checked each run; older dates are never retried
# run_date reasons that come from a successful official read (already_final / deferred do not read).
READ_REASONS = ('unchanged', 'rankings_still_pending')


def rankings_complete(summary):
    """True when every league with a played/unplayed (not cancelled/postponed) game has its TOP3."""
    leagues = summary.get('game_day_rankings', {}).get('leagues', {})
    for league in official.LEAGUES:
        live = [g for g in summary.get('games', []) if g.get('competition') == league
                and g.get('status') not in ('cancelled', 'postponed')]
        if live and (league not in leagues or 'error' in leagues[league]):
            return False
    return True


def done(summary):
    """Nothing left to recover for this date: schedule complete, every game final or
    officially cancelled/postponed, and EFF/position TOP3 built. A day without games is done."""
    return complete(summary) and all(
        data.is_verified_final(g) or (g.get('status') in ('cancelled', 'postponed') and g.get('source'))
        for g in summary.get('games', [])) and rankings_complete(summary)


def estimate(summary):
    """Upper bound of official requests to re-check one saved date (schedule pages,
    game pages, both club rosters per game)."""
    return len(official.LEAGUES) + 3 * len(summary.get('games', []))


def league_semantic(summary, league):
    return [g for g in semantic(summary)['games'] if g.get('competition') == league]


def run_date(root, client, year, now, date=None):
    """Refresh one JST date (default: today). Raises ValueError and keeps saved data on any doubt."""
    root = Path(root)
    now = now.astimezone(data.JST)
    date = date or now.date().isoformat()
    path = root / 'data/match_articles' / day_articles.filename(date).replace('.html', '.json')
    prior = json.loads(path.read_text()) if path.exists() else None
    if prior and prior.get('date') != date:
        raise ValueError('Saved result date mismatch')
    article = root / day_articles.filename(date)
    if prior and done(prior) and article.exists():
        return {'date': date, 'changed': False, 'reason': 'already_final', 'requests': client.request_count}
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
        return {'date': date, 'changed': False, 'reason': 'no_games', 'requests': client.request_count}
    # Leagues whose games did not change keep an already-built TOP3 if a retry fails.
    stable = [lg for lg in official.LEAGUES if prior and league_semantic(prior, lg) == league_semantic(summary, lg)]
    prior_rankings = (prior or {}).get('game_day_rankings', {}).get('leagues', {})
    if prior and semantic(prior) == semantic(summary) and article.exists():
        all_final = all(data.is_verified_final(g) for g in summary['games']
                        if g.get('status') not in ('cancelled', 'postponed'))
        if rankings_complete(prior) or not all_final:  # TOP3 cannot exist before every result is final
            return {'date': date, 'changed': False, 'reason': 'unchanged', 'requests': client.request_count}
        trial = day_articles.game_day_rankings.collect(client, root, summary)
        merged = day_articles.merge_rankings(trial, prior_rankings, stable)
        if merged['leagues'] == prior_rankings:
            return {'date': date, 'changed': False, 'reason': 'rankings_still_pending', 'requests': client.request_count}
    previews = [p.name for p in root.glob('article-preview-*.html')]
    written = day_articles.write(client, root, summary, previews,
                                 now.strftime('%Y-%m-%d %H:%M JST'), refresh_players=False,
                                 rankings_client=client, prior_rankings=prior_rankings, stable_leagues=stable)
    if not written:
        raise ValueError('Result rendering failed; build skipped')
    return {'date': date, 'changed': True, 'article': written, 'requests': client.request_count}


def pending_dates(root, now):
    """Today plus saved past JST dates (newest first, at most LOOKBACK_DAYS back) that are not done."""
    root = Path(root)
    today = now.astimezone(data.JST).date()
    dates = [today.isoformat()]
    for back in range(1, LOOKBACK_DAYS + 1):
        day = (today - timedelta(days=back)).isoformat()
        path = root / 'data/match_articles' / day_articles.filename(day).replace('.html', '.json')
        if not path.exists():
            continue
        try:
            saved = json.loads(path.read_text())
        except (ValueError, OSError):
            dates.append(day)  # unreadable: run() reports it for this date only
            continue
        if not (done(saved) and (root / day_articles.filename(day)).exists()):
            dates.append(day)
    return dates


# Which recorded problem explains a failed date best: a real observation beats "not requested".
CATEGORY_ORDER = ('http', 'network', 'parse', 'other', 'budget', 'stopped')


def primary(problems):
    """The first problem of the most informative category; {} when nothing was recorded."""
    for category in CATEGORY_ORDER:
        for item in problems:
            if item.get('category') == category:
                return item
    return problems[0] if problems else {}


def run(root, client, year, now):
    """Today and recent unfinished JST dates. Each date is independent: a failure keeps that
    date's saved data and does not stop the others. If nothing changed and some date failed,
    the first failure is raised (exit 1, no build) as before."""
    reports, errors, first = [], [], None
    today = now.astimezone(data.JST).date().isoformat()
    limit = getattr(client, 'max_requests', None)
    status_changed = False   # reader-facing state changed (rebuild needed)
    status_path = Path(root) / result_status.PATH
    status_before = status_path.read_bytes() if status_path.exists() else None
    for date in pending_dates(root, now):
        path = Path(root) / 'data/match_articles' / day_articles.filename(date).replace('.html', '.json')
        seen = len(getattr(client, 'failures', []))
        try:
            if date != today and limit is not None and client.request_count + estimate(json.loads(path.read_text())) > limit:
                reports.append({'date': date, 'changed': False, 'reason': 'deferred_budget', 'requests': client.request_count})
                continue
            report = run_date(root, client, year, now, date)
            reports.append(report)
            # Result fetch state only; EFF TOP3 still pending is not a fetch failure.
            # Only reasons that come from a real official read advance last_checked_at.
            if report['changed'] or report.get('reason') in READ_REASONS:
                status_changed |= result_status.record_success(root, date, now, report['changed'])
        except (ValueError, OSError, official.requests.RequestException) as exc:
            fetches = list(getattr(client, 'failures', [])[seen:])
            detail = primary(fetches)
            error = {'date': date, 'error': str(exc), 'category': detail.get('category') or 'unknown',
                     'type': detail.get('type') or type(exc).__name__,
                     'http_status': detail.get('http_status'), 'url': detail.get('url'), 'fetch_failures': fetches}
            errors.append(error); first = first or exc
            if (Path(root) / day_articles.filename(date)).exists():
                status_changed |= result_status.record_failure(root, date, now, error)
        status_changed |= result_status.apply_notice(root, date)
    changed = any(r['changed'] for r in reports)
    status_file_changed = (status_path.read_bytes() if status_path.exists() else None) != status_before
    if errors and not changed:
        first.result_errors = errors
        first.status_changed = status_changed
        first.status_file_changed = status_file_changed
        raise first
    head = next((r for r in reports if r['date'] == today), reports[0] if reports else {})
    return dict(head, changed=changed, dates=reports, errors=errors, requests=client.request_count,
                status_changed=status_changed, status_file_changed=status_file_changed)


def log_errors(errors, limit=12):
    """Annotations with public facts only. Every recorded problem is listed (as annotations, so
    they stay readable even when the full job log cannot be downloaded)."""
    for e in errors:
        print('::warning::Result refresh failed date=' + e['date'] + ' category=' + str(e.get('category'))
              + ' type=' + str(e.get('type')) + ' http=' + str(e.get('http_status')) + ' url=' + str(e.get('url'))
              + ' reason=' + e['error'][:200] + '; saved data retained')
        problems = e.get('fetch_failures', [])
        for f in problems[:limit]:
            print('::warning::  date=' + e['date'] + ' problem category=' + str(f.get('category'))
                  + ' http=' + str(f.get('http_status')) + ' type=' + str(f.get('type'))
                  + ' attempts=' + str(f.get('attempts')) + ' url=' + str(f.get('url'))
                  + ((' message=' + f['message']) if f.get('message') else ''))
        if len(problems) > limit:
            print('::warning::  date=' + e['date'] + ' ' + str(len(problems) - limit) + ' more problems not listed')


def mark_status_saved():
    """Tell the workflow that a failure notice was written and the site rebuilt, so it may be saved."""
    target = os.environ.get('GITHUB_OUTPUT')
    if target:
        with open(target, 'a') as handle:
            handle.write('status_saved=1\n')


def build(root):
    subprocess.run([sys.executable, str(Path(root) / 'scripts/build.py')], cwd=root, check=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--season-year', required=True, type=int)
    parser.add_argument('--root', default=str(ROOT))
    args = parser.parse_args()
    client = official.Client(max_requests=70, time_budget=180)
    try:
        try:
            report = run(args.root, client, args.season_year, datetime.now(data.JST))
        except (ValueError, OSError, official.requests.RequestException) as exc:
            errors = getattr(exc, 'result_errors', [{'date': '-', 'error': str(exc), 'type': type(exc).__name__}])
            log_errors(errors)
            if getattr(exc, 'status_changed', False):
                build(args.root)      # show the failure notice; results themselves are unchanged
            if getattr(exc, 'status_changed', False) or getattr(exc, 'status_file_changed', False):
                mark_status_saved()
            print('::error::Result refresh failed; existing published data retained')
            return 1
        try:
            preview = refresh_next_preview.refresh(args.root, args.season_year, datetime.now(data.JST))
        except (ValueError, OSError, official.requests.RequestException) as exc:
            # Results are already secured; a preview problem must not discard them.
            print('::warning::Next-fixture refresh failed type=' + type(exc).__name__ + ' reason=' + str(exc)[:200])
            preview = {'changed': False, 'errors': [str(exc)]}
        report['preview'] = preview
        report['changed'] = report['changed'] or preview['changed']
        if preview.get('errors'):
            print('::warning::Next-fixture refresh unavailable; previous snapshot retained')
        log_errors(report.get('errors', []))
        print(json.dumps(report, ensure_ascii=False, default=str))
        if report['changed'] or report.get('status_changed'):
            build(args.root)
            return 0  # some date was updated; failed dates are retried by the next run
        # Only last_checked_at moved: saved by the workflow (exit 0), no HTML rebuild needed.
        if report.get('errors'):
            if report.get('status_file_changed'):
                mark_status_saved()
            print('::error::Result refresh failed; existing published data retained')
            return 1
        return 0
    except (ValueError, OSError, official.requests.RequestException, subprocess.CalledProcessError) as exc:
        print('::error::Result refresh failed type=' + type(exc).__name__ + ' reason=' + str(exc)[:300])
        traceback.print_exc()
        return 1


if __name__ == '__main__':
    raise SystemExit(main())

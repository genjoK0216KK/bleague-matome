"""League-scoped daily candidate selections from verified per-game roster snapshots."""
import json
from datetime import datetime, timedelta
from pathlib import Path
try:
    from . import preview_data as data, official_data as official
except ImportError:
    import preview_data as data
    import official_data as official


def select(players, season, league):
    ranked = data.position_rankings(players, season=season, competition=league, metric='EFF')
    used, teams = set(), []
    for _ in range(2):
        team = []
        for position in data.POSITIONS:
            candidate = next((p for p in ranked['positions'][position] if p['player_id'] not in used), None)
            if candidate:
                used.add(candidate['player_id'])
            team.append((position, candidate))
        teams.append(team)
    return teams


def collect(client, root, summary):
    now = datetime.now(data.JST)
    result = {}
    for league in official.LEAGUES:
        games = [g for g in summary['games'] if g['competition'] == league and g['status'] not in ('cancelled','postponed')]
        if not games:
            continue
        try:
            if not summary['schedule_complete'].get(league):
                raise ValueError('日程取得が未完了')
            bundles = []
            for game in games:
                path = Path(root)/'data/match_articles'/('players-'+game['game_id']+'.json')
                if not path.exists():
                    raise ValueError('全対戦チームの選手データが未取得')
                bundle = json.loads(path.read_text())
                if bundle['game']['game_id'] != game['game_id'] or bundle['game']['competition'] != league or data.jst_date(bundle['game']['starts_at']) != summary['date']:
                    raise ValueError('選手データの試合日・大会が不一致')
                if now-datetime.fromisoformat(bundle['retrieved_at']) > timedelta(hours=36):
                    raise ValueError('選手データが36時間を超過')
                bundles.append(bundle)
            records = official.injury_records(client.get(official.BASE+'/news/injury.html'))
            players, times = {}, []
            for bundle in bundles:
                roster = bundle['players']
                for p in roster:
                    # Re-evaluate current IL; old registration/removal never overrides current evidence.
                    for key in ('availability_source','availability_detail','il_removed_date','il_source'):
                        p.pop(key,None)
                    p['availability']='unknown'
                official.apply_injuries(client, roster, [r for r in records if r['active']], bundle['game'], [r for r in records if not r['active']][:5])
                try:
                    from .match_articles import verified_recent_returns
                except ImportError:
                    from match_articles import verified_recent_returns
                confirmation_path = Path(__file__).resolve().parent.parent/'data/il-return-confirmations.json'
                confirmations = json.loads(confirmation_path.read_text()) if confirmation_path.exists() else {}
                verified_recent_returns(roster, confirmations, now)
                for p in roster:
                    if p['player_id'] in players and players[p['player_id']] != p:
                        raise ValueError('同一選手の記録が不一致')
                    players[p['player_id']] = p
                times.append(bundle['retrieved_at'])
            result[league] = {'teams': select(list(players.values()),games[0]['season'],league), 'retrieved_at':min(times), 'sources':sorted({p[k] for p in players.values() for k in ('position_source','stats_source','il_source') if p.get(k)} | {official.BASE+'/news/injury.html'})}
        except (ValueError, official.requests.RequestException) as exc:
            result[league] = {'error': str(exc)}
    return result

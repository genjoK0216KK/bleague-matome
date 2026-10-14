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


def player_bundle(client, root, game, date, now):
    """Backfill exact-game rosters even after tipoff; never relabel another day."""
    path = Path(root)/'data/match_articles'/('players-'+game['game_id']+'.json')
    if path.exists():
        bundle = json.loads(path.read_text())
        saved = bundle['game']
        identity = all(saved.get(k) == game.get(k) for k in ('game_id','competition','season','home_id','away_id'))
        fresh = timedelta(0) <= now-datetime.fromisoformat(bundle['retrieved_at']) <= timedelta(hours=36)
        roster_complete = {p.get('team_id') for p in bundle['players']} == {game.get('home_id'),game.get('away_id')} and all(p.get('competition')==game['competition'] and p.get('season')==game['season'] and p.get('aggregation')=='average' for p in bundle['players'])
        if identity and roster_complete and data.jst_date(saved['starts_at']) == date and fresh:
            return bundle
    if client is None or not hasattr(client,'get'):
        raise ValueError('全対戦チームの選手データが未取得')
    year = int(game['season'][:4])
    verified = official.parse_game(client.get(game['source']),game['game_id'],year)
    if (data.jst_date(verified['starts_at']) != date or
            any(verified.get(k) != game.get(k) for k in ('competition','season','home_id','away_id'))):
        raise ValueError('公式試合の日時・リーグ・対戦チームが不一致')
    averages = official.fetch_averages(client,year,game['competition'])
    players = []
    for side in ('home','away'):
        players.extend(official.fetch_roster(client,game[side+'_id'],game[side],year,game['competition']))
    for p in players:
        stat = averages.get(p['player_id'],{})
        p.update(metric='EFF',aggregation='average',average=stat.get('average'),games=stat.get('games'),
                 stats_source=stat.get('stats_source'),coverage_complete=bool(stat))
    urls={p[k] for p in players for k in ('position_source','stats_source') if p.get(k)}
    times=[s['retrieved_at'] for s in client.sources if s['url'] in urls]
    if not times:
        raise ValueError('選手資料の取得時刻が未確認')
    bundle={'game':verified,'players':players,'retrieved_at':min(times)}
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(bundle,ensure_ascii=False,indent=2,default=str),encoding='utf-8')
    return bundle


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
                bundles.append(player_bundle(client,root,game,summary['date'],now))
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

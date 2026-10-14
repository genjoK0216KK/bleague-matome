"""Position leaders from verified game-total boxscores, never season averages."""
import json
import re
from datetime import datetime, timedelta
from pathlib import Path
try:
    from . import official_data as official, preview_data as data
except ImportError:
    import official_data as official
    import preview_data as data

POSITIONS = ('PG', 'SG', 'SF', 'PF', 'C')
FIELDS = {'pts':'Point', 'reb':'RB_TOT', 'ast':'AS', 'eff':'EFF'}
FORMULA_ADD = ('Point','RB_TOT','AS','ST','BS','FOULON','PT2M','PT3M','FTM')
FORMULA_SUB = ('TO','BSON','FOUL','PT2A','PT3A','FTA')


def integer(value):
    if isinstance(value, bool) or not re.fullmatch(r'-?\d+', str(value)):
        raise ValueError('公式スタッツの数値が未取得')
    return int(value)


def seconds(value):
    if value in ('DNP', 'DNP-CD', '00:00'):
        return 0
    m = re.fullmatch(r'(\d+):([0-5]\d)', str(value))
    if not m:
        raise ValueError('出場時間が未確認')
    return int(m[1])*60+int(m[2])


def roster(client, root, game, now):
    path=Path(root)/'data/match_articles'/('players-'+game['game_id']+'.json')
    if path.exists():
        bundle=json.loads(path.read_text());saved=bundle.get('game',{})
        if (all(saved.get(k)==game.get(k) for k in ('game_id','season','competition','home_id','away_id'))
                and timedelta(0)<=now-datetime.fromisoformat(bundle['retrieved_at'])<=timedelta(hours=36)):
            rows=bundle.get('players',[])
            if {p.get('team_id') for p in rows}=={game['home_id'],game['away_id']}:
                return rows,bundle['retrieved_at']
    if client is None or not hasattr(client,'get'):
        raise ValueError('公式ポジション資料が未取得または期限超過')
    rows=[]
    for side in ('home','away'):
        rows.extend(official.fetch_roster(client,game[side+'_id'],game[side],int(game['season'][:4]),game['competition']))
    urls={r['position_source'] for r in rows}
    stamps=[r['retrieved_at'] for r in client.sources if r['url'] in urls]
    if not stamps:raise ValueError('ポジション取得時刻が未確認')
    return rows,min(stamps)


def player_rows(game, positions, date):
    if not data.is_verified_final(game) or data.jst_date(game['starts_at'])!=date:
        raise ValueError('当日の公式記録確定待ち')
    lookup={(p['player_id'],p['team_id']):p for p in positions
            if p.get('season')==game['season'] and p.get('competition')==game['competition']}
    result=[];seen=set();teams={game['home_id']:game['home'],game['away_id']:game['away']}
    for raw in game.get('players',[]):
        if integer(raw.get('Category'))!=1 or integer(raw.get('PeriodCategory'))!=18:continue
        if not seconds(raw.get('PlayTime')):continue
        pid=str(raw.get('PlayerID') or '');tid=str(raw.get('TeamID') or '')
        if str(raw.get('ScheduleKey'))!=game['game_id'] or tid not in teams or not pid:
            raise ValueError('選手・試合・所属の公式IDが不一致')
        if pid in seen:raise ValueError('同一試合の選手記録が重複')
        seen.add(pid);p=lookup.get((pid,tid));pos=p.get('positions',[]) if p else []
        if not pos or any(x not in POSITIONS for x in pos):raise ValueError('出場選手の公式ポジションが未確認')
        values={k:integer(raw.get(v)) for k,v in FIELDS.items()}
        formula_value=None
        if all(raw.get(k) is not None for k in FORMULA_ADD+FORMULA_SUB):
            calculated=sum(integer(raw[k]) for k in FORMULA_ADD)-sum(integer(raw[k]) for k in FORMULA_SUB)
            formula_value=calculated
        if not raw.get('PlayerNameJ'):raise ValueError('公式選手名が未確認')
        result.append(dict(player_id=pid,team_id=tid,name=raw['PlayerNameJ'],team=teams[tid],positions=list(dict.fromkeys(pos)),
                           source=game['source'],position_source=p['position_source'],game_id=game['game_id'],formula_value=formula_value,**values))
    if not result or {p['team_id'] for p in result}!=set(teams):raise ValueError('両チームの出場記録が未取得')
    return result


def select(players):
    result={}
    for pos in POSITIONS:
        rows=sorted((p for p in players if pos in p['positions']),key=lambda p:(-p['eff'],int(p['player_id'])))
        top=[];rank=0;last=None
        for index,p in enumerate(rows[:3],1):
            if p['eff']!=last:rank=index
            top.append(dict(p,rank=rank));last=p['eff']
        result[pos]=top
    return result


def collect(client, root, summary, now=None):
    now=now or datetime.now(data.JST);result={}
    for league in official.LEAGUES:
        games=[g for g in summary['games'] if g['competition']==league and g.get('status') not in ('cancelled','postponed')]
        if not games:continue
        try:
            if not summary['schedule_complete'].get(league):raise ValueError('日程取得が未完了')
            if not all(data.is_verified_final(g) for g in games):raise ValueError('全試合の公式記録確定待ち')
            players=[];stamps=[]
            for game in games:
                positions,stamp=roster(client,root,game,now)
                players.extend(player_rows(game,positions,summary['date']));stamps.append(stamp)
            if len({p['player_id'] for p in players})!=len(players):raise ValueError('同一選手の当日複数試合は未対応')
            result[league]={'positions':select(players),'eligible_players':len(players),'position_retrieved_at':min(stamps),
                            'formula_differences':[{'player_id':p['player_id'],'name':p['name'],'eff':p['eff'],'formula_value':p['formula_value'],'source':p['source']} for p in players if p['formula_value'] is not None and p['formula_value']!=p['eff']],
                            'sources':sorted({p[k] for p in players for k in ('source','position_source')})}
        except (ValueError,KeyError,official.requests.RequestException) as exc:
            result[league]={'error':str(exc)}
    return {'date':summary['date'],'metric':'EFF','aggregation':'game_total','leagues':result}

#!/usr/bin/env python3
"""チーム分析記事の数字を作る（本人 2026-11-08「こういうちゃんとした記事を毎日一本、チームも変えながら」）。

B.LEAGUE 公式の試合データ（公式サイトの試合ページが使っている公開 JSON）から、B.PREMIER 全26チームの
直近5試合を集計し、1チーム分の数字と26チーム中の順位を JSON に書き出す。記事の文章は Mac mini の記事ジョブ
（~/Claude/Scheduled/bleague-daily）の Claude がこの JSON だけを根拠に書く。

- 試合データは試合ごとに必要な部分だけを小さくしてキャッシュに保存する（同じ試合は2度取りに行かない）。
- 取りに行く試合は data/schedule-calendar.json に載っている B.PREMIER の試合（今日まで）だけ。終わっていない試合は保存しない。
- 記事にする数字はすべて `numbers` に入れる。記事の小数（108.4、30.7% など）は check_numbers で JSON にあるかを確かめる。
- チームの選び方（choose_team）：14日以内に書いたチームは外し、次の試合が近い・検索数が多い（data/keywords.json）・
  連勝連敗中のチームを優先する。
標準ライブラリだけで動く。

使い方：
  python3 scripts/team_report.py --cache DIR --out report.json [--team 宇都宮ブレックス] [--date 2026-11-08]
  python3 scripts/team_report.py --cache DIR --out report.json --scan 506379 506600   # キャッシュを一から作る時
  python3 scripts/team_report.py --check article-analysis-xxx-20261108.html --report report.json
"""
import argparse
import datetime as dt
import gzip
import json
import re
import sys
import time
import urllib.error
import urllib.request
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FEED = 'https://b-league.s3.amazonaws.com/web_json/v2_genius_contexts/'
UA = {'User-Agent': 'BleagueMatomeBot/1.0 (+https://basuke-matome.jp/about.html)'}
JST = dt.timezone(dt.timedelta(hours=9))
LAST_N = 5
GAP_DAYS = 14
PAUSE = 0.3
PREMIER = '521'           # ConventionKey of B.PREMIER リーグ戦 (2026-27)

SLUG = {
    'レバンガ北海道': 'hokkaido', '仙台89ERS': 'sendai', '秋田ノーザンハピネッツ': 'akita', '茨城ロボッツ': 'ibaraki',
    '宇都宮ブレックス': 'brex', '群馬クレインサンダーズ': 'gunma', 'アルティーリ千葉': 'altiri', '千葉ジェッツ': 'chibajets',
    'アルバルク東京': 'alvark', '東京サンロッカーズ': 'sunrockers', '川崎ブレイブサンダース': 'kawasaki',
    '横浜ビー・コルセアーズ': 'yokohama', '富山グラウジーズ': 'toyama', '信州ブレイブウォリアーズ': 'shinshu',
    '三遠ネオフェニックス': 'sanen', 'シーホース三河': 'mikawa', '名古屋ダイヤモンドドルフィンズ': 'nagoya',
    '滋賀レイクス': 'shiga', '京都ハンナリーズ': 'kyoto', '大阪エヴェッサ': 'osaka', '神戸ストークス': 'kobe',
    '島根スサノオマジック': 'shimane', '広島ドラゴンフライズ': 'hiroshima', '佐賀バルーナーズ': 'saga',
    '長崎ヴェルカ': 'nagasaki', '琉球ゴールデンキングス': 'ryukyu',
}
# 小さいほど良い指標（順位は良い方から1位）
LOWER_BETTER = {'opp_ppg', 'drtg', 'opp_efg', 'tov_pct', 'opp_orb_pct', 'opp_ft_rate', 'opp_p3_pct', 'opp_p2_pct',
                'opp_fta_g', 'opp_paint_pts_g', 'opp_second_pts_g', 'opp_fastbreak_pts_g', 'opp_pts_off_to_g',
                'to_g', 'opp_paint_fg_pct'}
LABELS = {
    'ppg': '平均得点', 'opp_ppg': '平均失点', 'pace': '1試合の攻撃回数', 'ortg': '100回の攻撃あたりの得点',
    'drtg': '100回の攻撃あたりの失点', 'net': '100回あたりの差し引き', 'efg': 'eFG%（3Pを1.5倍で数えた成功率）',
    'opp_efg': '相手のeFG%', 'tov_pct': 'ターンオーバーで終わった攻撃の割合', 'opp_tov_pct': '相手のターンオーバー割合',
    'orb_pct': 'オフェンスリバウンド獲得率', 'opp_orb_pct': '相手のオフェンスリバウンド獲得率',
    'ft_rate': 'フリースローをもらう割合（FTA÷FGA）', 'opp_ft_rate': '相手にフリースローを与える割合',
    'p3_pct': '3P成功率', 'opp_p3_pct': '相手の3P成功率', 'p3_rate': 'シュートに占める3Pの割合',
    'p2_pct': '2P成功率', 'opp_p2_pct': '相手の2P成功率', 'ft_pct': 'フリースロー成功率',
    'fta_g': '1試合のフリースロー試投', 'opp_fta_g': '相手の1試合のフリースロー試投',
    'paint_pts_g': 'ペイント内の得点', 'opp_paint_pts_g': '相手のペイント内の得点',
    'second_pts_g': 'セカンドチャンスの得点', 'opp_second_pts_g': '相手のセカンドチャンスの得点',
    'fastbreak_pts_g': '速攻の得点', 'opp_fastbreak_pts_g': '相手の速攻の得点',
    'pts_off_to_g': 'ターンオーバーからの得点', 'opp_pts_off_to_g': '相手のターンオーバーからの得点',
    'to_g': '1試合のターンオーバー', 'opp_to_g': '相手の1試合のターンオーバー', 'blk_g': '1試合のブロック',
    'ast_g': '1試合のアシスト', 'paint_fg_pct': 'ペイント内のシュート成功率', 'opp_paint_fg_pct': '相手のペイント内のシュート成功率',
}
PERCENT = {'efg', 'opp_efg', 'tov_pct', 'opp_tov_pct', 'orb_pct', 'opp_orb_pct', 'p3_pct', 'opp_p3_pct', 'p3_rate',
           'p2_pct', 'opp_p2_pct', 'ft_pct', 'paint_fg_pct', 'opp_paint_fg_pct'}
SUMMARY = {'fgm': 'PTM', 'fga': 'PTA', 'p2m': 'PT2M', 'p2a': 'PT2A', 'p3m': 'PT3M', 'p3a': 'PT3A', 'ftm': 'FTM',
           'fta': 'FTA', 'orb': 'RB_OFF', 'drb': 'RB_DEF', 'ast': 'AS', 'to': 'TO', 'stl': 'ST', 'blk': 'BS',
           'foul': 'FOUL', 'paint': 'PT2IN', 'pot': 'PTPFT', 'second': 'PT2ND', 'fastbreak': 'PTFB'}
PLAYER = {'pts': 'Point', 'orb': 'RB_OFF', 'reb': 'RB_TOT', 'ast': 'AS', 'to': 'TO', 'stl': 'ST', 'blk': 'BS',
          'p2m': 'PT2M', 'p2a': 'PT2A', 'p3m': 'PT3M', 'p3a': 'PT3A', 'ftm': 'FTM', 'fta': 'FTA', 'eff': 'EFF'}


# ---------- 取得とキャッシュ ----------

def _get(url):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=30) as res:
        body = res.read()
    return gzip.decompress(body) if body[:2] == b'\x1f\x8b' else body


def compact(ctx):
    """試合1つ分の公式 JSON から、集計に使う部分だけを残す（保存サイズを小さくする）。"""
    g = ctx['Game']
    stamp = int(re.search(r'\d+', str(g['GameDateTime'])).group())
    stamp = stamp // 1000 if stamp > 10 ** 11 else stamp
    teams = {'home': g['HomeTeamNameJ'], 'away': g['AwayTeamNameJ']}
    summaries = {}
    for s in ctx.get('Summaries') or []:
        pc = str(s['PeriodCategory'])
        summaries[pc] = {side: {k: (s.get(('Home' if side == 'home' else 'Away') + 'Team' + v) or 0)
                                for k, v in SUMMARY.items()} for side in ('home', 'away')}
    players = {}
    for side, field in (('home', 'HomeBoxscores'), ('away', 'AwayBoxscores')):
        rows = []
        for r in ctx.get(field) or []:
            if r.get('PeriodCategory') != 18 or not r.get('PlayerID'):
                continue
            rows.append({'name': r['PlayerNameJ'], 'no': r.get('PlayerNo'), 'time': r.get('PlayTime') or '',
                         'start': bool(r.get('StartingFlg')), **{k: (r.get(v) or 0) for k, v in PLAYER.items()}})
        players[side] = rows
    paint = {'home': [0, 0], 'away': [0, 0]}
    for p in ctx.get('PlayByPlays') or []:
        t = p.get('PlayText') or ''
        if '2Pシュート' in t and 'インサイドペイント' in t:
            side = 'home' if p.get('TeamNameJ') == teams['home'] else 'away' if p.get('TeamNameJ') == teams['away'] else None
            if side:
                paint[side][1] += 1
                paint[side][0] += '○' in t
    return {
        'key': str(g['ScheduleKey']), 'convention': str(g.get('ConventionKey')),
        'date': dt.datetime.fromtimestamp(stamp, JST).date().isoformat(),
        'home': teams['home'], 'away': teams['away'],
        'home_score': g.get('HomeTeamScore'), 'away_score': g.get('AwayTeamScore'),
        'quarters': {'home': [g.get(f'HomeTeamScore0{i}') for i in range(1, 5)],
                     'away': [g.get(f'AwayTeamScore0{i}') for i in range(1, 5)]},
        'max_period': g.get('MaxPeriod'), 'summaries': summaries, 'players': players, 'paint_shots': paint,
        'url': f'https://www.bleague.jp/game_detail/?ScheduleKey={g["ScheduleKey"]}&tab=2',
    }


def calendar_keys(calendar, today):
    keys = []
    for month in calendar.get('months', []):
        for day, games in ((month.get('leagues') or {}).get('BP') or {}).get('days', {}).items():
            if day > today:
                continue
            for game in games:
                if game.get('status') not in ('cancelled', 'postponed') and re.fullmatch(r'\d{6}', str(game.get('game_id'))):
                    keys.append(str(game['game_id']))
    return sorted(set(keys))


def collect(cache, keys, fetch=_get, pause=PAUSE, log=print):
    """キャッシュに無い試合だけを取りに行く。終わっていない試合・B.PREMIER 以外は保存しない。"""
    cache = Path(cache)
    cache.mkdir(parents=True, exist_ok=True)
    added = 0
    for key in keys:
        path = cache / f'{key}.json'
        if path.exists():
            continue
        try:
            latest = int(json.loads(fetch(FEED + f'{key}/latestid')))
            time.sleep(pause)
            ctx = json.loads(fetch(FEED + f'{key}/{latest}.json'))
            time.sleep(pause)
        except urllib.error.HTTPError as exc:
            if exc.code != 403:                    # 403 はまだ始まっていない試合（データが無い）
                log(f'取得できず {key}: HTTP {exc.code}')
            continue
        except (urllib.error.URLError, ValueError, OSError) as exc:
            log(f'取得できず {key}: {type(exc).__name__}')
            continue
        game = ctx.get('Game') or {}
        if not game.get('GameEndedFlg'):
            continue
        item = compact(ctx)
        if item['convention'] != PREMIER:
            continue
        path.write_text(json.dumps(item, ensure_ascii=False), encoding='utf-8')
        added += 1
    return added


def load_games(cache, upto):
    games = []
    for path in Path(cache).glob('*.json'):
        g = json.loads(path.read_text(encoding='utf-8'))
        if g['date'] <= upto and g.get('convention') == PREMIER:
            games.append(g)
    return sorted(games, key=lambda g: (g['date'], g['key']))


# ---------- 集計 ----------

def _side(g, team):
    return 'home' if g['home'] == team else 'away'


def _other(side):
    return 'away' if side == 'home' else 'home'


def _pts(x):
    return 2 * x['p2m'] + 3 * x['p3m'] + x['ftm']


def _poss(x):
    return x['fga'] - x['orb'] + x['to'] + 0.44 * x['fta']


def team_games(games, team, n=LAST_N):
    return [g for g in games if team in (g['home'], g['away'])][-n:]


def metrics(games, team, n=LAST_N):
    last = team_games(games, team, n)
    if len(last) < n:
        return None
    me, op = Counter(), Counter()
    halves = {'15': [Counter(), Counter()], '16': [Counter(), Counter()], '17': [Counter(), Counter()]}
    quarters = [[0, 0] for _ in range(4)]
    wins = poss = pf = pa = pm = pa_ = opm = opa = 0
    log = []
    for g in last:
        s = _side(g, team)
        o = _other(s)
        a, b = g['summaries']['18'][s], g['summaries']['18'][o]
        me.update(a)
        op.update(b)
        x, y = _pts(a), _pts(b)
        pf += x
        pa += y
        wins += x > y
        poss += (_poss(a) + _poss(b)) / 2
        pm += g['paint_shots'][s][0]
        pa_ += g['paint_shots'][s][1]
        opm += g['paint_shots'][o][0]
        opa += g['paint_shots'][o][1]
        for pc in halves:
            if pc in g['summaries']:
                halves[pc][0].update(g['summaries'][pc][s])
                halves[pc][1].update(g['summaries'][pc][o])
        for i in range(4):
            quarters[i][0] += g['quarters'][s][i] or 0
            quarters[i][1] += g['quarters'][o][i] or 0
        log.append({'date': g['date'], 'opponent': g[o], 'venue': 'ホーム' if s == 'home' else 'アウェー',
                    'score': f'{x}-{y}', 'result': '勝ち' if x > y else '負け',
                    'overtime': max(0, (g.get('max_period') or 4) - 4), 'key': g['key'], 'url': g['url'],
                    'quarters': [[g['quarters'][s][i], g['quarters'][o][i]] for i in range(4)]})
    k = len(last)
    m = {
        'games': k, 'wins': wins, 'losses': k - wins, 'ppg': pf / k, 'opp_ppg': pa / k, 'pace': poss / k,
        'ortg': 100 * pf / poss, 'drtg': 100 * pa / poss,
        'efg': (me['fgm'] + 0.5 * me['p3m']) / me['fga'], 'opp_efg': (op['fgm'] + 0.5 * op['p3m']) / op['fga'],
        'tov_pct': me['to'] / (me['fga'] + 0.44 * me['fta'] + me['to']),
        'opp_tov_pct': op['to'] / (op['fga'] + 0.44 * op['fta'] + op['to']),
        'orb_pct': me['orb'] / (me['orb'] + op['drb']), 'opp_orb_pct': op['orb'] / (op['orb'] + me['drb']),
        'ft_rate': me['fta'] / me['fga'], 'opp_ft_rate': op['fta'] / op['fga'],
        'p3_pct': me['p3m'] / me['p3a'], 'opp_p3_pct': op['p3m'] / op['p3a'], 'p3_rate': me['p3a'] / me['fga'],
        'p2_pct': me['p2m'] / me['p2a'], 'opp_p2_pct': op['p2m'] / op['p2a'], 'ft_pct': me['ftm'] / me['fta'],
        'fta_g': me['fta'] / k, 'opp_fta_g': op['fta'] / k,
        'paint_pts_g': me['paint'] / k, 'opp_paint_pts_g': op['paint'] / k,
        'second_pts_g': me['second'] / k, 'opp_second_pts_g': op['second'] / k,
        'fastbreak_pts_g': me['fastbreak'] / k, 'opp_fastbreak_pts_g': op['fastbreak'] / k,
        'pts_off_to_g': me['pot'] / k, 'opp_pts_off_to_g': op['pot'] / k,
        'to_g': me['to'] / k, 'opp_to_g': op['to'] / k, 'blk_g': me['blk'] / k, 'ast_g': me['ast'] / k,
        'paint_fg_pct': pm / pa_ if pa_ else 0.0, 'opp_paint_fg_pct': opm / opa if opa else 0.0,
    }
    m['net'] = m['ortg'] - m['drtg']
    totals = {
        'points': [pf, pa, pf - pa],
        'p2_points': [2 * me['p2m'], 2 * op['p2m'], 2 * (me['p2m'] - op['p2m'])],
        'p3_points': [3 * me['p3m'], 3 * op['p3m'], 3 * (me['p3m'] - op['p3m'])],
        'ft_points': [me['ftm'], op['ftm'], me['ftm'] - op['ftm']],
        'p3': {'team': [me['p3m'], me['p3a']], 'opp': [op['p3m'], op['p3a']]},
        'p2': {'team': [me['p2m'], me['p2a']], 'opp': [op['p2m'], op['p2a']]},
        'ft': {'team': [me['ftm'], me['fta']], 'opp': [op['ftm'], op['fta']]},
        'orb': [me['orb'], op['orb']], 'to': [me['to'], op['to']],
        'second_pts': [me['second'], op['second']], 'paint_pts': [me['paint'], op['paint']],
        'paint_shots': {'team': [pm, pa_], 'opp': [opm, opa]},
    }
    half = {}
    for pc, name in (('15', 'first_half'), ('16', 'second_half'), ('17', 'overtime')):
        a, b = halves[pc]
        if not a and not b:
            continue
        half[name] = {'pts_g': _pts(a) / k, 'opp_pts_g': _pts(b) / k, 'diff_g': (_pts(a) - _pts(b)) / k,
                      'total_diff': _pts(a) - _pts(b),
                      'p2': [a['p2m'], a['p2a']], 'p3': [a['p3m'], a['p3a']],
                      'opp_p2': [b['p2m'], b['p2a']], 'opp_p3': [b['p3m'], b['p3a']],
                      'ft': [a['ftm'], a['fta']], 'opp_ft': [b['ftm'], b['fta']],
                      'paint_pts_g': a['paint'] / k, 'opp_paint_pts_g': b['paint'] / k,
                      'to_g': a['to'] / k, 'opp_orb_g': b['orb'] / k}
    q = [{'quarter': i + 1, 'pts_g': quarters[i][0] / k, 'opp_pts_g': quarters[i][1] / k,
          'diff_total': quarters[i][0] - quarters[i][1]} for i in range(4)]
    return {'metrics': m, 'totals': totals, 'halves': half, 'quarters': q, 'log': log}


def players(games, team, n=LAST_N):
    last = team_games(games, team, n)
    agg, played, seen = defaultdict(Counter), Counter(), {}
    minutes = Counter()
    for g in last:
        for r in g['players'][_side(g, team)]:
            seen[r['name']] = r.get('no')
            mm = re.fullmatch(r'(\d+):(\d+)', r.get('time') or '')
            sec = int(mm[1]) * 60 + int(mm[2]) if mm else 0
            if sec <= 0:
                continue
            played[r['name']] += 1
            minutes[r['name']] += sec
            agg[r['name']].update({k: r.get(k) or 0 for k in PLAYER})
    rows = []
    for name, a in agg.items():
        gp = played[name]
        rows.append({'name': name, 'no': seen.get(name), 'games': gp, 'min_g': minutes[name] / 60 / gp,
                     'pts_g': a['pts'] / gp, 'reb_g': a['reb'] / gp, 'ast_g': a['ast'] / gp, 'orb': a['orb'],
                     'p2': [a['p2m'], a['p2a']], 'p3': [a['p3m'], a['p3a']], 'ft': [a['ftm'], a['fta']],
                     'eff_g': a['eff'] / gp})
    rows.sort(key=lambda r: -r['pts_g'])
    # 今季このチームで出ていた選手のうち、直近の試合に出ていない人（欠場・ベンチ外。理由は公式発表で確かめる）
    earlier = set()
    for g in [g for g in games if team in (g['home'], g['away'])][:-n]:
        for r in g['players'][_side(g, team)]:
            mm = re.fullmatch(r'(\d+):(\d+)', r.get('time') or '')
            if mm and int(mm[1]) * 60 + int(mm[2]) >= 10 * 60:
                earlier.add(r['name'])
    missing = []
    for name in sorted(earlier):
        absent = [g['date'] for g in last if not any(r['name'] == name and re.fullmatch(r'\d+:\d+', r.get('time') or '')
                                                      and r['time'] not in ('0:00', '00:00')
                                                      for r in g['players'][_side(g, team)])]
        if absent:
            missing.append({'name': name, 'absent_dates': absent})
    return rows, missing


def league(games, n=LAST_N):
    teams = sorted({g['home'] for g in games} | {g['away'] for g in games})
    table = {}
    for t in teams:
        r = metrics(games, t, n)
        if r:
            table[t] = r['metrics']
    keys = [k for k in next(iter(table.values())) if k not in ('games', 'wins', 'losses')] if table else []
    ranks, avg = defaultdict(dict), {}
    for k in keys:
        order = sorted(table, key=lambda t: table[t][k], reverse=k not in LOWER_BETTER)
        for i, t in enumerate(order):
            ranks[t][k] = i + 1
        avg[k] = sum(table[t][k] for t in table) / len(table)
    return table, ranks, avg


def season_record(games, team):
    w = l = 0
    for g in games:
        if team in (g['home'], g['away']):
            s = _side(g, team)
            x, y = (g['home_score'], g['away_score']) if s == 'home' else (g['away_score'], g['home_score'])
            w += x > y
            l += x < y
    return w, l


def next_game(calendar, team, today, finished=()):
    short = {c['name']: c['short'] for c in json.loads((ROOT / 'scripts/team_colors.json').read_text('utf-8'))['clubs']}
    s = short.get(team)
    for month in calendar.get('months', []):
        for day, games in sorted(((month.get('leagues') or {}).get('BP') or {}).get('days', {}).items()):
            if day < today:
                continue
            for g in games:
                if (s in (g.get('home'), g.get('away')) and g.get('status') not in ('cancelled', 'postponed')
                        and str(g.get('game_id')) not in finished):
                    return {'date': day, 'time': g.get('time'), 'home': g['home'], 'away': g['away'],
                            'venue': 'ホーム' if g['home'] == s else 'アウェー', 'key': g.get('game_id')}
    return None


# ---------- チームの選び方 ----------

def history(root=ROOT):
    """これまでに書いたチーム分析記事：{チーム名: 最後に書いた日}。"""
    done = {}
    for path in Path(root).glob('article-analysis-*-*.html'):
        m = re.search(r'<meta name="analysis-team" content="([^"]+)"', path.read_text('utf-8', errors='ignore'))
        d = re.search(r'-(\d{8})\.html$', path.name)
        if m and d:
            day = f'{d[1][:4]}-{d[1][4:6]}-{d[1][6:]}'
            done[m[1]] = max(done.get(m[1], ''), day)
    return done


def current_streak(games, team):
    """今の連勝（プラス）・連敗（マイナス）の数。"""
    res = [(g['home_score'] > g['away_score']) == (g['home'] == team) for g in games if team in (g['home'], g['away'])]
    if not res:
        return 0
    n = 0
    for r in reversed(res):
        if r != res[-1]:
            break
        n += 1
    return n if res[-1] else -n


VOLUME_SCORE = {'10万～100万': 3, '1万～10万': 2, '1000～1万': 1}


def choose_team(games, calendar, today, done, keywords, n=LAST_N):
    cands = []
    for team in sorted({g['home'] for g in games} | {g['away'] for g in games}):
        last = team_games(games, team, n)
        if len(last) < n:
            continue
        if team in done and (dt.date.fromisoformat(today) - dt.date.fromisoformat(done[team])).days < GAP_DAYS:
            continue
        score = VOLUME_SCORE.get(((keywords.get('teams') or {}).get(team) or {}).get('volume'), 1)
        ng = next_game(calendar, team, today, {g['key'] for g in games})
        if ng and (dt.date.fromisoformat(ng['date']) - dt.date.fromisoformat(today)).days <= 1:
            score += 3
        streak = current_streak(games, team)
        if abs(streak) >= 3:
            score += min(abs(streak), 10) // 2       # 連勝・連敗が長いほど話題になる
        if (dt.date.fromisoformat(today) - dt.date.fromisoformat(last[-1]['date'])).days <= 2:
            score += 1
        cands.append((-score, done.get(team, ''), team))
    if not cands:
        return None
    cands.sort()
    return cands[0][2]


# ---------- 書き出しと数字の確かめ ----------

def _fmt(v):
    return round(v, 3) if isinstance(v, float) else v


def build_report(games, calendar, team, today, keywords):
    r = metrics(games, team)
    table, ranks, avg = league(games)
    rows, missing = players(games, team)
    w, l = season_record(games, team)
    numbers = {}
    for k, v in r['metrics'].items():
        if k in LABELS:
            numbers[k] = {'label': LABELS[k], 'value': _fmt(v), 'rank': ranks[team][k], 'league_avg': _fmt(avg[k]),
                          'percent': k in PERCENT, 'lower_is_better': k in LOWER_BETTER, 'of': len(table)}
    leaders = {}
    for k in ('p3_rate', 'tov_pct', 'net', 'ortg', 'drtg', 'second_pts_g', 'opp_fta_g'):
        order = sorted(table, key=lambda t: table[t][k], reverse=k not in LOWER_BETTER)
        leaders[k] = [[t, _fmt(table[t][k])] for t in order[:3]]
    return {
        'team': team, 'slug': SLUG.get(team, 'team'), 'date': today, 'last_n': LAST_N,
        'record_last_n': [r['metrics']['wins'], r['metrics']['losses']], 'season_record': [w, l],
        'streak': current_streak(games, team),
        'numbers': numbers, 'totals': r['totals'], 'halves': {k: {kk: _fmt(vv) for kk, vv in v.items()}
                                                                for k, v in r['halves'].items()},
        'quarters': [{k: _fmt(v) for k, v in q.items()} for q in r['quarters']], 'games': r['log'],
        'players': [{k: _fmt(v) for k, v in p.items()} for p in rows],
        'not_in_recent_games': missing, 'next_game': next_game(calendar, team, today, {g['key'] for g in games}),
        'league_top3': leaders, 'keywords': (keywords.get('teams') or {}).get(team),
        'keyword_terms': keywords.get('terms'), 'teams_compared': len(table),
        'definition': '順位は B.PREMIER 各チームの直近5試合で比べたもの。相手の強さや日程の違いは調整していない。'
                      '攻撃回数＝FGA−オフェンスリバウンド＋ターンオーバー＋0.44×FTA（両チームの平均）。',
    }


def allowed_decimals(report):
    """記事に書いてよい小数（JSON にある数字を、記事でよく使う形に丸めたもの）。"""
    out = set()

    def add(v):
        if isinstance(v, bool) or not isinstance(v, (int, float)):
            return
        for x in (v, v * 100):
            for d in (1, 2):
                out.add(f'{x:.{d}f}')
                out.add(f'{abs(x):.{d}f}')

    def walk(x):
        if isinstance(x, dict):
            for v in x.values():
                walk(v)
        elif isinstance(x, list):
            for v in x:
                walk(v)
            if len(x) == 2 and all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in x) and x[1]:
                add(x[0] / x[1])
        else:
            add(x)
    walk(report)
    for v in report['numbers'].values():
        add(v['value'] - v['league_avg'])        # 「平均より3.4点低い」のような差
        add(round(v['value'], 1) - round(v['league_avg'], 1))   # 表の丸めた数字どうしの差
    return out


def check_numbers(html, report):
    """記事本文の小数が、すべて JSON の数字から来ているかを確かめる。戻り値：根拠の無い小数のリスト。"""
    body = re.search(r'<article class="article">(.*?)</article>', html, re.S)
    text = re.sub(r'<details class="sources">.*?</details>', '', body.group(1) if body else html, flags=re.S)
    text = re.sub(r'<[^>]+>', ' ', text)
    ok = allowed_decimals(report)
    bad = []
    for m in re.finditer(r'(?<![\d.])(\d+\.\d+)(?![\d.])', text):
        if m[1] not in ok:
            bad.append(m[1])
    return bad


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument('--cache')
    p.add_argument('--out')
    p.add_argument('--team')
    p.add_argument('--date')
    p.add_argument('--no-fetch', action='store_true')
    p.add_argument('--scan', nargs=2, type=int, metavar=('FROM', 'TO'),
                   help='キャッシュを作り直す時：この範囲の試合番号を全部見る（2026-27 は 506379 から）')
    p.add_argument('--check')
    p.add_argument('--report')
    a = p.parse_args(argv)
    if a.check:
        report = json.loads(Path(a.report).read_text('utf-8'))
        bad = check_numbers(Path(a.check).read_text('utf-8'), report)
        if bad:
            print('根拠の無い小数：' + '、'.join(bad))
            return 1
        print('数字：指摘なし')
        return 0
    today = a.date or dt.datetime.now(JST).date().isoformat()
    calendar = json.loads((ROOT / 'data/schedule-calendar.json').read_text('utf-8'))
    if a.scan:
        print(f'範囲を見て保存した試合：{collect(a.cache, [str(k) for k in range(a.scan[0], a.scan[1] + 1)])}', file=sys.stderr)
    if not a.no_fetch:
        added = collect(a.cache, calendar_keys(calendar, today))
        print(f'新しく保存した試合：{added}', file=sys.stderr)
    games = load_games(a.cache, today)
    kw_path = ROOT / 'data/keywords.json'
    keywords = json.loads(kw_path.read_text('utf-8')) if kw_path.exists() else {}
    team = a.team or choose_team(games, calendar, today, history(), keywords)
    if not team:
        print('書けるチームがありません', file=sys.stderr)
        return 2
    report = build_report(games, calendar, team, today, keywords)
    Path(a.out).write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding='utf-8')
    print(team)
    return 0


if __name__ == '__main__':
    sys.exit(main())

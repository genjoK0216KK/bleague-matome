"""Read-only B.LEAGUE adapters. Parse HTML/JSON; never execute remote JavaScript."""
import hashlib
import json
import re
import time
from datetime import datetime, timezone, timedelta
JST = timezone(timedelta(hours=9))
from decimal import Decimal, InvalidOperation
from pathlib import Path
from urllib.parse import urlencode, urlparse

import requests
from bs4 import BeautifulSoup

BASE = 'https://www.bleague.jp'
LEAGUES = {'BP': (1, 'player-b1', 2, 'B.PREMIER'),
           'B1': (2, 'player-b2', 7, 'B.ONE'),
           'BN': (3, 'player-b3', 15, 'B.NEXT')}
CONVENTIONS_2026 = {'522': 'B1', '523': 'BN'}


class DataError(ValueError):
    pass


class Client:
    def __init__(self, cache=None, offline=False, max_requests=120, time_budget=360):
        self.cache = Path(cache) if cache else None
        self.offline = offline
        self.sources = []
        self.memory = {}
        self.max_requests = max_requests
        self.request_count = 0
        self.deadline = time.monotonic() + time_budget

    def get(self, url):
        if urlparse(url).hostname != 'www.bleague.jp' or not url.startswith('https://'):
            raise DataError('Only official HTTPS sources are allowed')
        if url in self.memory:
            return self.memory[url]
        if not self.offline and (self.request_count >= self.max_requests or time.monotonic() + 32 > self.deadline):
            raise DataError('Official fetch budget exhausted; prior data retained')
        key = hashlib.sha256(url.encode()).hexdigest()
        path = self.cache / (key + '.json') if self.cache else None
        if self.offline:
            if not path or not path.exists():
                raise DataError('Offline capture missing: ' + url)
            capture = json.loads(path.read_text())
            if capture['url'] != url:
                raise DataError('Capture URL mismatch')
        else:
            self.request_count += 1
            response = requests.get(url, timeout=30, headers={'User-Agent': 'BleagueMatomeBot/1.0 (+https://basuke-matome.jp/about.html)'})
            response.raise_for_status()
            if urlparse(response.url).hostname != 'www.bleague.jp':
                raise DataError('Unexpected redirect')
            response.encoding = 'utf-8'
            capture = {'url': url, 'retrieved_at': datetime.now(timezone.utc).isoformat(), 'body': response.text}
            if path:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(json.dumps(capture, ensure_ascii=False), encoding='utf-8')
            time.sleep(2)
        self.sources.append({k: capture[k] for k in ('url', 'retrieved_at')})
        self.memory[url] = capture['body']
        return capture['body']


def integer(value):
    if value is None or isinstance(value, bool) or not re.fullmatch(r'-?\d+', str(value).strip()):
        return None
    return int(value)


def context(page):
    match = re.search(r'\b_contexts_s3id\.data\s*=\s*', page)
    if not match:
        raise DataError('Official game context missing')
    value = json.JSONDecoder().raw_decode(page[match.end():])[0]
    if not isinstance(value, dict) or not isinstance(value.get('Game'), dict):
        raise DataError('Invalid official game context')
    return value


def parse_game(page, key, year, schedule_status=None):
    if not re.search(r'\b_contexts_s3id\.data\s*=', page):
        return parse_future_game(page, key, year, schedule_status)
    ctx = context(page)
    g = ctx['Game']
    if str(g.get('ScheduleKey')) != str(key) or integer(g.get('Year')) != year:
        raise DataError('Game identity/season mismatch')
    convention = g.get('ConventionNameJ', '')
    league = next((k for k, v in LEAGUES.items() if v[3].replace('B.', 'B.LEAGUE ') in convention
                   or v[3] in convention), None)
    if not league:
        raise DataError('Unknown competition: ' + convention)
    if 'リーグ戦' not in convention:
        raise DataError('Non-regular-season game')
    if year == 2026 and league in ('B1', 'BN') and CONVENTIONS_2026.get(str(g.get('ConventionKey'))) != league:
        raise DataError('Convention mismatch')
    timestamp = integer(g.get('GameDateTime'))
    if timestamp is None:
        raise DataError('Actual game timestamp missing')
    game = dict(game_id=str(key), season=f'{year}-{str(year+1)[-2:]}', competition=league,
                starts_at=datetime.fromtimestamp(timestamp, timezone.utc).isoformat(),
                ended=g.get('GameEndedFlg') is True, fixed=g.get('RecordFixedFlg') is True,
                source=f'{BASE}/game_detail/?ScheduleKey={key}', convention=convention,
                status='scheduled')
    for side in ('home', 'away'):
        prefix = side.title()
        game[side] = g.get(prefix + 'TeamShortNameJ') or g.get(prefix + 'TeamNameJ')
        game[side + '_full'] = g.get(prefix + 'TeamNameJ')
        game[side + '_id'] = str(g.get(prefix + 'TeamID') or '')
        game[side + '_score'] = integer(g.get(prefix + 'TeamScore'))
    game['status'] = 'final' if game['ended'] and game['fixed'] else 'unconfirmed'
    # Category and period are the only filters; PlayingFlg is not participation.
    game['players'] = [p for side in ('HomeBoxscores', 'AwayBoxscores') for p in ctx.get(side, [])
                       if integer(p.get('Category')) == 1 and integer(p.get('PeriodCategory')) == 18]
    return game


def stats_url(year, league, index=None, aggregation="tot"):
    if aggregation not in ('tot', 'avg'):
        raise DataError('Unsupported official aggregation')
    tab, target, event, _ = LEAGUES[league]
    params = dict(year=year, tab=tab, target=target, value='EFFPG' if aggregation == 'avg' else 'EFF', o='desc', e=event, dt=aggregation)
    if index is not None:
        params.update(data_format='json', index=index)
    return BASE + '/stats/?' + urlencode(params)


def stats_columns(page):
    soup = BeautifulSoup(page, 'html.parser')
    for head in soup.select('thead'):
        if head.select_one('[data-sort-value="EFF"], [data-sort-value="EFFPG"]'):
            cols = [th.get('data-sort-value') or 'rank' for th in head.select('th')
                    if th.has_attr('rowspan') or th.has_attr('data-sort-value')]
            if len(cols) != len(set(cols)) or 'GameCount' not in cols or 'PlayerNameJ' not in cols:
                raise DataError('Ambiguous stats headers')
            return cols
    raise DataError('Official EFF header missing')


def parse_stats_rows(topics, columns, url):
    records = []
    for fragment in topics:
        soup = BeautifulSoup(fragment, 'html.parser')
        for row in soup.select('tr'):
            cells = row.find_all('td', recursive=False)
            if not cells and row.find('th'):
                continue  # API repeats header rows within topics every 20 players.
            if len(cells) != len(columns):
                raise DataError('Stats column count changed')
            link = row.select_one('a[href*="PlayerID="]')
            if link is None:
                raise DataError('Stats player identity missing')
            pid = re.search(r'PlayerID=(\d+)', link['href']).group(1)
            fields = dict(zip(columns, (c.get_text(' ', strip=True) for c in cells)))
            raw = fields['EFFPG' if 'EFFPG' in fields else 'EFF'].replace(',', '')
            try:
                eff = Decimal(raw)
                if not eff.is_finite():
                    raise InvalidOperation
            except InvalidOperation:
                eff = None
            records.append(dict(player_id=pid, name=link.get_text(' ', strip=True),
                                team=fields['TeamNameJ'], games=integer(fields['GameCount']),
                                total=eff, stats_source=url))
    return records


def choose_totals(rows):
    """Prefer one official TOTAL; never add TOTAL to club rows or guess transfers."""
    grouped = {}
    for row in rows:
        grouped.setdefault(row['player_id'], []).append(row)
    out = {}
    for pid, items in grouped.items():
        unique = list({(p['team'], p['total'], p['games']): p for p in items}.values())
        totals = [p for p in unique if p['team'].strip().upper() in ('TOTAL', '合計', '通算')]
        if len(totals) == 1:
            out[pid] = totals[0]
        elif len(unique) == 1:
            out[pid] = unique[0]
        else:
            out[pid] = dict(unique[0], total=None, stats_problem='transfer_total_unverified')
    return out


def fetch_totals(client, year, league, aggregation="tot"):
    header_page = client.get(stats_url(year, league, aggregation=aggregation))
    header_soup = BeautifulSoup(header_page, 'html.parser')
    for field, expected in (('year', str(year)), ('data', aggregation), ('event', str(LEAGUES[league][2]))):
        option = header_soup.select_one(f'select[name="{field}"] option[selected]')
        if option is None or option.get('value') != expected:
            raise DataError('Stats scope/aggregation not confirmed')
    columns = stats_columns(header_page)
    if ('EFFPG' if aggregation == 'avg' else 'EFF') not in columns:
        raise DataError('Official EFF column does not match aggregation')
    index, seen, rows = 0, set(), []
    for _ in range(100):
        if index in seen:
            raise DataError('Stats pagination loop')
        seen.add(index)
        url = stats_url(year, league, index, aggregation=aggregation)
        payload = json.loads(client.get(url))
        topics = payload.get('topics')
        if not isinstance(topics, list):
            raise DataError('Stats topics missing')
        rows.extend(parse_stats_rows(topics, columns, url))
        following = integer(payload.get('index'))
        if not topics or following in (None, 0):
            totals = choose_totals(rows)
            for record in totals.values():
                record['stats_payload_source'] = record['stats_source']
                record['stats_source'] = stats_url(year, league, aggregation=aggregation)
            return totals
        if following <= index:
            raise DataError('Stats pagination did not advance')
        index = following
    raise DataError('Stats pagination limit exceeded')


def fetch_averages(client, year, league):
    """Read official dt=avg values; never derive averages from totals or boxscores."""
    records = fetch_totals(client, year, league, aggregation='avg')
    for row in records.values():
        row['average'] = row.pop('total')
        row['aggregation'] = 'average'
    return records


def parse_schedule(page, league, date):
    from datetime import date as Date
    d = Date.fromisoformat(date)
    soup = BeautifulSoup(page, 'html.parser')
    tab = LEAGUES[league][0]
    for field, expected in (('year', d.year if d.month >= 7 else d.year-1), ('mon', d.month)):
        selected = soup.select_one(f'select[name="{field}"] option[selected]')
        if selected is None or integer(selected.get('value')) != expected:
            raise DataError('Schedule period mismatch')
    container = soup.select_one(f'#schedule-b{tab}')
    if container is None:
        raise DataError('Schedule league container missing')
    days = {integer(x.get('data-day')) for x in soup.select('.js_click_data[data-day]')}
    if not days:
        raise DataError('Calendar empty: cannot prove no games')
    keys = sorted(set(re.findall(r'ScheduleKey=(\d+)', str(container))))
    current = {integer(x.get('data-day')) for x in soup.select('.js-schedule-date-slider-item.is-current [data-day]')}
    complete = d.day not in days or (current == {d.day} and bool(keys) and len(keys) < 20)
    # Page has a monthly calendar. A missing requested day proves no scheduled game;
    # keys may belong to the next date and must still be checked using GameDateTime.
    notices, notice_dates = {}, {}
    for item in container.select('li.list-item[id]'):
        text = item.get_text(' ', strip=True)
        status = 'cancelled' if '中止' in text else 'postponed' if '延期' in text else None
        if status:
            notices[item['id']] = status
            if item.get('data-dt') == d.strftime('%m%d'):
                notice_dates[item['id']] = d.isoformat()
    return {'keys': keys, 'complete': complete, 'no_games': d.day not in days, 'notices': notices, 'notice_dates': notice_dates}


def fetch_day(client, year, league, date):
    from datetime import date as Date
    d = Date.fromisoformat(date)
    url = BASE + '/schedule/?' + urlencode(dict(tab=LEAGUES[league][0], year=year, mon=d.month, day=d.day))
    plan = parse_schedule(client.get(url), league, date)
    games, errors = [], []
    if plan['no_games']:
        return [], plan['complete'], url, []
    for key in plan['keys']:
        try:
            g = parse_game(client.get(f'{BASE}/game_detail/?ScheduleKey={key}'), key, year, plan['notices'].get(key))
            if g['competition'] != league:
                raise DataError('Schedule/game league mismatch')
            if key in plan['notices']:
                g['status'] = plan['notices'][key]
                if key in plan['notice_dates']:
                    g['official_date'] = plan['notice_dates'][key]
            actual_date = g.get('official_date') if g['status'] in ('cancelled', 'postponed') else None
            if (actual_date or datetime.fromisoformat(g['starts_at']).astimezone(JST).date().isoformat()) != date:
                raise DataError('Schedule fallback returned a different actual game date')
            games.append(g)
        except (ValueError, requests.RequestException) as exc:
            errors.append(str(exc))
    return games, plan['complete'] and not errors, url, errors


def fetch_roster(client, team_id, team, year, league):
    url = f'{BASE}/club_detail/?TeamID={team_id}'
    soup = BeautifulSoup(client.get(url), 'html.parser')
    season = f'{year}-{str(year+1)[-2:]}'
    heading = soup.find('h3', string=re.compile(r'\d{4}-\d{2}シーズン成績'))
    if heading is None or heading.get_text(strip=True) != season + 'シーズン成績':
        raise DataError('Current roster season unverified')
    roster = []
    for card in soup.select('a.playerInfo-player[href*="PlayerID="]'):
        pid = re.search(r'PlayerID=(\d+)', card['href']).group(1)
        name_node = card.select_one('.playerInfo-player-name')
        if name_node is None:
            raise DataError('Roster player name missing')
        name = name_node.get_text(' ', strip=True)
        pos = card.select_one('.playerInfo-player-position')
        positions = re.findall(r'\b(?:PG|SG|SF|PF|C)\b', pos.get_text() if pos else '')
        roster.append(dict(player_id=pid, name=name, team=team, team_id=team_id,
                           season=season, competition=league, positions=positions,
                           position_source=url, availability='unknown'))
    if not roster:
        raise DataError('Current club roster missing')
    return roster


def injury_records(page):
    """Minimal official IL fields. Keep yearless dates literal; never retain diagnoses."""
    soup = BeautifulSoup(page, 'html.parser')
    table = soup.select_one('table.flat-tbl02')
    if table is None or '再登録不可期日' not in table.get_text():
        raise DataError('Injury list format changed')
    notice = re.search(r'公示日[：:]\s*(\d{4}年\d{1,2}月\d{1,2}日)', soup.get_text(' ', strip=True))
    records = []
    for row in table.select('tbody tr'):
        cells = [td.get_text(' ', strip=True) for td in row.select('td')]
        if not cells:
            continue
        if len(cells) != 7 or '/' not in cells[0] or not cells[4] or not cells[5]:
            raise DataError('Injury list row format changed')
        announced, removed = (v.strip() for v in cells[0].split('/', 1))
        records.append(dict(team=cells[4], name=cells[5], league=cells[3],
                            announced_date=announced, registered_date=cells[1], removed_date=removed,
                            unavailable_until=cells[2], active=not bool(removed),
                            notice_date=notice.group(1) if notice else '公示日未確認'))
    if not records:
        raise DataError('Empty injury list not verified')
    return records


def injury_rows(page):
    return [r for r in injury_records(page) if r['active']]


def apply_injuries(client, roster, active, game, removed=()):
    """Resolve exact names per club; profile fetch ordering is not identity evidence."""
    normalize = lambda s: re.sub(r'\s+', '', s).casefold()
    failures = []
    for side in ('home', 'away'):
        team_players = [p for p in roster if p['team_id'] == game.get(side + '_id')]
        candidates = [r for r in list(active) + list(removed)
                      if normalize(r['team']) == normalize(game[side + '_full'])]
        by_name = {}
        for r in candidates:
            by_name.setdefault(normalize(r['name']), []).append(r)
        resolved = {}
        for p in team_players:
            key = normalize(p['name'])
            if key in by_name:
                resolved[p['player_id']] = by_name.pop(key)
        # Prioritize likely matching scripts solely to save requests. Every match
        # still requires the exact English name from that PlayerID's official page.
        pending = [p for p in team_players if p['player_id'] not in resolved]
        pending.sort(key=lambda p: bool(re.search(r'[一-龯ぁ-ゟ]', p['name'])))
        for p in pending:
            if not by_name:
                break
            url = f'{BASE}/roster_detail/?PlayerID={p["player_id"]}'
            try:
                english = BeautifulSoup(client.get(url), 'html.parser').select_one('.js-player-name')
            except (ValueError, requests.RequestException) as exc:
                failures.append(str(exc))
                break
            key = normalize(english.get_text(' ', strip=True)) if english else ''
            if key in by_name:
                resolved[p['player_id']] = by_name.pop(key)
        for p in team_players:
            matches = resolved.get(p['player_id'], [])
            active_matches = [r for r in matches if r.get('active', True)]
            if active_matches:
                row = active_matches[0]
                p.update(availability='out', availability_source=BASE + '/news/injury.html',
                         availability_detail='公式IL登録中（取得時点）。選手公示日：' + row.get('announced_date', '未確認')
                         + '／リスト登録日：' + row.get('registered_date', '未確認') + '。次戦時点の解除・登録は再確認が必要')
            elif matches:
                p.update(il_removed_date=matches[0]['removed_date'], il_source=BASE + '/news/injury.html',
                         availability_detail='IL抹消（' + matches[0]['removed_date'] + '）。現在の公式登録一覧に掲載。出場は未確認')

    if failures:
        raise DataError('IL profile verification incomplete: ' + '; '.join(failures))


def parse_future_game(page, key, year, schedule_status=None):
    """Upcoming games lack boxscore JSON. Read only the game-specific static section.

    Never use the global scoreboard: it contains unrelated completed games.
    """
    soup = BeautifulSoup(page, 'html.parser')
    canonical = soup.select_one('meta[property="og:url"]')
    if canonical is None or canonical.get('content') != f'{BASE}/game_detail/?ScheduleKey={key}':
        raise DataError('Future-game identity mismatch')
    area = soup.select_one('section.game-top')
    if area is None:
        raise DataError('Future-game header missing')
    convention_node = area.select_one('#convention-name')
    day_node = area.select_one('.date-wrap .font-blg')
    time_node = area.select_one('.time')
    if convention_node is None or day_node is None:
        raise DataError('Future-game date/competition missing')
    convention = convention_node.get_text(' ', strip=True)
    season = f'{year}-{str(year+1)[-2:]}'
    league = next((k for k, v in LEAGUES.items() if v[3].replace('B.', 'B.LEAGUE ') in convention or v[3] in convention), None)
    if not league or season not in convention or 'リーグ戦' not in convention:
        raise DataError('Future-game competition/season mismatch')
    day = day_node.get_text(strip=True)
    time_text = time_node.get_text(strip=True) if time_node else ''
    time_match = re.fullmatch(r'(\d{2}:\d{2}) TIP OFF', time_text)
    if not time_match and schedule_status not in ('cancelled', 'postponed'):
        raise DataError('Future-game time unconfirmed')
    from datetime import timedelta
    starts = datetime.strptime(day + ' ' + time_match.group(1), '%Y.%m.%d %H:%M').replace(tzinfo=timezone(timedelta(hours=9))) if time_match else None
    game = dict(game_id=str(key), season=season, competition=league, starts_at=starts.isoformat() if starts else None,
                ended=False, fixed=False, source=canonical['content'], convention=convention,
                status=schedule_status or 'scheduled', players=[])
    if not starts:
        game['official_date'] = datetime.strptime(day, '%Y.%m.%d').date().isoformat()
    related = soup.select('.related-links a[href*="club_detail/?TeamID="]')
    for side in ('home', 'away'):
        team = area.select_one('.team-wrap.' + side)
        if team is None or any(team.select_one(sel) is None for sel in ('.team-point', '.team-name .for-pc', '.team-name .for-sp')):
            raise DataError('Future-game team markup missing')
        points = team.select_one('.team-point').find(string=True, recursive=False)
        if not points or points.strip() != '--':
            raise DataError('Game has scores but no official record context')
        full = team.select_one('.team-name .for-pc').get_text(strip=True)
        matches = [a for a in related if a.get_text(strip=True) == full]
        ids = {re.search(r'TeamID=(\d+)', a['href']).group(1) for a in matches}
        if len(ids) != 1:
            raise DataError('Future-game team identity ambiguous')
        game[side] = team.select_one('.team-name .for-sp').get_text(strip=True)
        game[side + '_full'] = full
        game[side + '_id'] = ids.pop()
        game[side + '_score'] = None
    return game


def fetch_next_games(client, year, league, after, horizon=35):
    """Find the next scheduled game date from official calendars, bounded lookahead.

    Explicit utility for callers choosing preview keys; never infer a next game from
    stats. Search months as necessary and validate each returned game timestamp.
    """
    from datetime import timedelta
    JST = timezone(timedelta(hours=9))
    if after.tzinfo is None:
        raise DataError('Timezone-aware cutoff required')
    checked = set()
    for offset in range(horizon):
        date = (after.astimezone(JST) + timedelta(days=offset)).date()
        month = (date.year, date.month)
        if month in checked:
            continue
        checked.add(month)
        url = BASE + '/schedule/?' + urlencode(dict(tab=LEAGUES[league][0], year=year, mon=date.month, day=date.day))
        soup = BeautifulSoup(client.get(url), 'html.parser')
        days = sorted({integer(x.get('data-day')) for x in soup.select('.js_click_data[data-day]')} - {None})
        for day in days:
            candidate_date = date.replace(day=day)
            if candidate_date < after.astimezone(JST).date() or (candidate_date - after.astimezone(JST).date()).days >= horizon:
                continue
            games, complete, _, errors = fetch_day(client, year, league, candidate_date.isoformat())
            if errors or not complete:
                raise DataError('Next-game schedule could not be verified')
            upcoming = [g for g in games if not g['ended'] and g['status'] not in ('cancelled', 'postponed')
                        and datetime.fromisoformat(g['starts_at']) > after]
            if upcoming:
                return upcoming
    return []

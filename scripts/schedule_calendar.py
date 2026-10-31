"""Official monthly schedule snapshots; no boxscores or inferred fixtures."""
import calendar
import json
import re
from datetime import date, datetime
from pathlib import Path
from urllib.parse import urlencode
from html import escape
from bs4 import BeautifulSoup
try:
    from . import official_data as official
except ImportError:
    import official_data as official


def url_for(year, league, day):
    return official.BASE + '/schedule/?' + urlencode(dict(tab=official.LEAGUES[league][0], year=year, mon=day.month, day=day.day))


def parse_day(page, league, day):
    plan = official.parse_schedule(page, league, day.isoformat())
    if plan['no_games']:
        return []
    if not plan['complete']:
        raise official.DataError('Daily schedule incomplete')
    soup = BeautifulSoup(page, 'html.parser')
    games = {}
    for item in soup.select(f'#schedule-b{official.LEAGUES[league][0]} > li.list-item[id]'):
        if item.get('data-dt') and item['data-dt'] != day.strftime('%m%d'):
            raise official.DataError('Schedule row date mismatch')
        key = item['id']
        if key not in plan['keys']:
            continue
        home = item.select_one('.team.home .team-name')
        away = item.select_one('.team.away .team-name')
        if not home or not away:
            raise official.DataError('Schedule team missing')
        times = re.findall(r'(?<!\d)([0-2]\d:[0-5]\d)(?!\d)', item.select_one('.info').get_text(' ',strip=True) if item.select_one('.info') else '')
        times = list(dict.fromkeys(times))
        if len(times) > 1 or any(int(t[:2]) > 23 for t in times):
            raise official.DataError('Ambiguous tipoff')
        games[key] = dict(game_id=key, date=day.isoformat(), league=league, home=home.get_text(' ',strip=True), away=away.get_text(' ',strip=True), time=times[0] if times else None, status=plan['notices'].get(key,'listed'), source=official.BASE+'/game_detail/?ScheduleKey='+key)
    if set(games) != set(plan['keys']):
        raise official.DataError('Schedule rows incomplete')
    return list(games.values())


def collect(client, year, now, previous=None):
    now = now.astimezone(official.JST)
    first = now.date().replace(day=1)
    following = date(first.year+first.month//12, first.month%12+1, 1)
    result = dict(updated_at=now.isoformat(), today=now.date().isoformat(), months=[], errors=[])
    old = {m['month']:m for m in (previous or {}).get('months',[])}
    for month in (first, following):
        month_id = month.strftime('%Y-%m')
        entry = dict(month=month_id, leagues={})
        for league in official.LEAGUES:
            source = url_for(year, league, month)
            snapshot = dict(status='unavailable', days={}, source=source, checked_at=now.isoformat())
            try:
                if (month.year if month.month >= 7 else month.year-1) != year:
                    raise official.DataError('Season not confirmed')
                page = client.get(source)
                official.parse_schedule(page, league, month.isoformat())
                soup = BeautifulSoup(page,'html.parser')
                active = {official.integer(x.get('data-day')) for x in soup.select('.js_click_data[data-day]')}
                if None in active:
                    raise official.DataError('Invalid schedule date')
                for number in range(1,calendar.monthrange(month.year,month.month)[1]+1):
                    day = month.replace(day=number)
                    snapshot['days'][day.isoformat()] = [] if number not in active else parse_day(client.get(url_for(year,league,day)),league,day)
                snapshot['status'] = 'complete'
                retrieved = [x['retrieved_at'] for x in getattr(client, 'sources', []) if x['url'].startswith(official.BASE+'/schedule/?') and f'tab={official.LEAGUES[league][0]}&' in x['url'] and f'&mon={month.month}&' in x['url']]
                if retrieved:
                    snapshot['checked_at'] = min(retrieved)
            except (ValueError, official.requests.RequestException) as exc:
                result['errors'].append(f'{month_id}/{league}: {exc}')
                prior = old.get(month_id,{}).get('leagues',{}).get(league)
                if prior and prior.get('status') in ('complete','stale'):
                    snapshot = dict(prior,status='stale')
            entry['leagues'][league] = snapshot
        result['months'].append(entry)
    return result


def update(client, root, year, now):
    path = Path(root)/'data/schedule-calendar.json'
    previous = json.loads(path.read_text()) if path.exists() else None
    result = collect(client,year,now,previous)
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    return result


def render(root):
    path = Path(root)/'data/schedule-calendar.json'
    if not path.exists():
        return '<section><h2>試合カレンダー</h2><p>日程を確認中です。<a href="https://www.bleague.jp/schedule/">公式日程を見る</a></p></section>'
    payload = json.loads(path.read_text())
    # JSON cannot close its script element even when a source contains HTML.
    encoded = json.dumps(payload,ensure_ascii=False).replace('<','\\u003c')
    return '''<section class="schedule-calendar" aria-labelledby="calendar-title">
<h2 id="calendar-title">試合カレンダー</h2><p>日付を選んで対戦カードを見る</p>
<div class="calendar-controls"><button type="button" data-month-step="-1" aria-label="前の月">‹</button><h3 id="calendar-month"></h3><button type="button" data-month-step="1" aria-label="次の月">›</button></div>
<p class="calendar-hint">カレンダーは横に動かせます</p>
<div class="calendar-scroll"><div class="calendar-week" aria-hidden="true"><span>日</span><span>月</span><span>火</span><span>水</span><span>木</span><span>金</span><span>土</span></div>
<div class="calendar-days" aria-label="試合日程の日付"></div></div>
<p class="calendar-key">● 掲載試合あり　? 一部未確認</p>
<div class="calendar-detail" aria-live="polite" aria-atomic="true"></div>
<details class="calendar-notes"><summary>日程の出典・更新情報</summary><p>時刻は日本時間（JST）。日程・開始時刻は変更される場合があります。延期・中止はカードに表示します。</p><div class="calendar-sources"></div></details>
<noscript><p>カレンダーにはJavaScriptが必要です。<a href="https://www.bleague.jp/schedule/">B.LEAGUE公式の日程を見る</a></p></noscript>
<script type="application/json" id="calendar-data">'''+encoded+'''</script></section><link rel="stylesheet" href="schedule-calendar.css?v=1"><script defer src="schedule-calendar.js?v=1"></script>'''

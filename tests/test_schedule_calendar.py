import json
import tempfile
import unittest
from datetime import date, datetime, timezone
from pathlib import Path
from unittest.mock import patch
from scripts import schedule_calendar as s, build


def page(day=16, active=True, time='19:05', note='', league=1):
    return f'''<select name="year"><option selected value="2026"></option></select><select name="mon"><option selected value="10"></option></select><div class="js_click_data" data-day="{16 if active else 17}"></div><div class="js-schedule-date-slider-item is-current"><b data-day="{day}"></b></div><ul id="schedule-b{league}"><li class="list-item" id="123"><a href="/game_detail/?ScheduleKey=123"><span class="team home"><span class="team-name">Home</span></span><span class="team away"><span class="team-name">Away</span></span><div class="info">{time} {note}</div></a></li></ul>'''


class CalendarTests(unittest.TestCase):
    def test_fixture_and_unset_time(self):
        g=s.parse_day(page(),'BP',date(2026,10,16))[0]
        self.assertEqual((g['date'],g['time'],g['league']),('2026-10-16','19:05','BP'))
        self.assertIsNone(s.parse_day(page(time='調整中'),'BP',date(2026,10,16))[0]['time'])
    def test_no_games_and_fallback(self):
        self.assertEqual(s.parse_day(page(active=False),'BP',date(2026,10,16)),[])
        with self.assertRaises(ValueError):s.parse_day(page(day=17),'BP',date(2026,10,16))
    def test_wrong_league_month_and_team(self):
        for html in [page(league=2),page().replace('value="10"','value="11"'),page().replace('team-name','missing')]:
            with self.assertRaises(ValueError):s.parse_day(html,'BP',date(2026,10,16))
    def test_cancellation_and_postponement(self):
        for word,status in [('中止','cancelled'),('延期','postponed')]:
            self.assertEqual(s.parse_day(page(note=word),'BP',date(2026,10,16))[0]['status'],status)
    def test_row_date_mismatch(self):
        with self.assertRaises(ValueError):s.parse_day(page().replace('id="123"','id="123" data-dt="1231"'),'BP',date(2026,10,16))
    def test_ambiguous_time(self):
        with self.assertRaises(ValueError):s.parse_day(page(time='19:05 20:05'),'BP',date(2026,10,16))
    def test_failed_fetch_keeps_prior_and_marks_unknown(self):
        class Fail:
            def get(self,url):raise ValueError('unavailable')
        old={'months':[{'month':'2026-10','leagues':{'BP':{'status':'complete','days':{'2026-10-16':[{'home':'A'}]},'checked_at':'old','source':'official'}}}]}
        r=s.collect(Fail(),2026,datetime(2026,9,30,15,tzinfo=timezone.utc),old)
        self.assertEqual(r['today'],'2026-10-01')
        self.assertEqual(r['months'][0]['leagues']['BP']['status'],'stale')
        self.assertEqual(r['months'][0]['leagues']['BP']['days'],old['months'][0]['leagues']['BP']['days'])
        self.assertEqual(r['months'][0]['leagues']['BN']['status'],'unavailable')
    def test_year_boundary_and_safe_json(self):
        class Fail:
            def get(self,url):raise ValueError('unavailable')
        r=s.collect(Fail(),2026,datetime(2026,12,31,tzinfo=timezone.utc))
        self.assertEqual([m['month'] for m in r['months']],['2026-12','2027-01'])
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'data';p.mkdir();(p/'schedule-calendar.json').write_text(json.dumps({'x':'</script><script>alert(1)</script>'}))
            self.assertNotIn('</script><script>alert',s.render(tmp))

    def test_category_build_contains_calendar_and_standings(self):
        with tempfile.TemporaryDirectory() as tmp:
            data=Path(tmp)/'data';data.mkdir();(data/'schedule-calendar.json').write_text(json.dumps({'months':[]}))
            with patch.object(build,'ROOT',tmp):
                build.update_category('data','cat-data.html',[],[],{},'test')
            html=(Path(tmp)/'cat-data.html').read_text()
            self.assertIn('id="calendar-data"',html)
            self.assertIn('順位表は取得待ち',html)

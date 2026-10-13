import json,tempfile,unittest
from pathlib import Path
from datetime import datetime,timezone
from decimal import Decimal
from bs4 import BeautifulSoup
from scripts import official_data as official, preview_data as data, day_articles, match_articles as articles, build, site_header
FIX=Path(__file__).parent/'fixtures'

class AveragesAndDays(unittest.TestCase):
    def test_official_average_value_not_recomputed(self):
        class C:
            def get(self,url):
                assert 'dt=avg' in url and 'value=EFFPG' in url
                return (FIX/('stats-averages.json' if 'data_format' in url else 'stats-average-header.html')).read_text()
        records=official.fetch_averages(C(),2026,'BP')
        self.assertEqual(records['51000312']['average'],Decimal('34.7'))
        self.assertNotEqual(records['51000312']['average'],Decimal(243)/7)
        self.assertEqual(records['51000312']['games'],7)
        self.assertNotIn('total',records['51000312'])

    def test_total_response_rejected_for_average(self):
        class C:
            def get(self,url):return (FIX/'stats-header.html').read_text()
        with self.assertRaises(official.DataError):official.fetch_averages(C(),2026,'BP')

    def summary(self):
        g=official.parse_game((FIX/'game-507233.html').read_text(),'507233',2026)
        summary=data.daily_results([g],date='2026-10-13',season='2026-27',competitions=official.LEAGUES,schedule_complete={'BP':True,'B1':True,'BN':True})
        summary.update(schedule_complete={'BP':True,'B1':True,'BN':True},sources=[g['source']],errors=[])
        return summary

    def test_three_leagues_and_missing_distinct_from_empty(self):
        s=self.summary();s['schedule_complete']['BN']=False
        _,html=day_articles.render(s,'.',[],'TEST');soup=BeautifulSoup(html,'html.parser')
        self.assertEqual([h.get_text() for h in soup.select('.league-games > h2')],['B.PREMIER','B.ONE','B.NEXT'])
        self.assertIn('この日の試合はありません',soup.select_one('#league-bp').get_text())
        self.assertIn('取得が未完了',soup.select_one('#league-bn').get_text())
        self.assertNotIn('試合はありません',soup.select_one('#league-bn').get_text())
        self.assertIn('80－71',soup.select_one('#league-b1').get_text())

    def test_date_alias_and_embedded_averages(self):
        s=self.summary();g=s['games'][0];g.update(ended=False,fixed=False,status='scheduled')
        class C: sources=[];offline=False
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);old=root/'article-results-one-next-20261013.html';old.write_text('OLD')
            preview='article-preview-507233.html';(root/preview).write_text('<article><p class="note preview-warning">公式IL情報の照合が未完了</p><div class="match-rankings"><h2>PG｜今季平均EFF</h2><table><tr><td>34.7</td></tr></table></div><p class="source"><a href="https://www.bleague.jp/stats/?dt=avg">公式</a></p></article>')
            name=day_articles.write(C(),root,s,[preview],'TEST')
            html=(root/name).read_text();soup=BeautifulSoup(html,'html.parser')
            self.assertEqual(len(soup.select('details.day-rankings')),1)
            self.assertIn('34.7',soup.get_text())
            self.assertIn('公式IL情報の照合が未完了',soup.select_one('details.day-rankings').get_text())
            self.assertIn('article-alias',old.read_text())
            self.assertIn(name,old.read_text())
            self.assertIn('dt=avg',html)

    def test_incomplete_fetch_keeps_games_and_adds_warning(self):
        class C: sources=[];offline=False
        with tempfile.TemporaryDirectory() as folder:
            s=self.summary();name=day_articles.write(C(),folder,s,[],'TEST')
            legacy=Path(folder)/'article-results-one-next-20261013.html'
            legacy.write_text('<html><head></head><body>Partial new legacy</body></html>')
            s['games']=[];s['schedule_complete']['B1']=False
            self.assertIsNone(day_articles.write(C(),folder,s,[],'NEW'))
            html=(Path(folder)/name).read_text()
            self.assertIn('80－71',html)
            self.assertIn('前回確認済みの試合情報を保持',html)
            self.assertIn('article-alias',legacy.read_text())
            self.assertIn('前回確認済みの試合情報を保持',legacy.read_text())
            self.assertIn('80－71',legacy.read_text())

    def test_actual_date_mismatch_excluded(self):
        s=self.summary();g=s['games'][0];g['starts_at']='2026-10-14T19:05:00+09:00'
        result=data.daily_results([g],date='2026-10-13',season='2026-27',competitions=official.LEAGUES,schedule_complete={'BP':True,'B1':True,'BN':True})
        self.assertEqual(result['games'],[])

if __name__=='__main__':unittest.main()

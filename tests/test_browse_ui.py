import unittest
from datetime import datetime
from pathlib import Path
from bs4 import BeautifulSoup
from scripts import browse_ui, fetch, preview_data

class BrowseUI(unittest.TestCase):
    def test_season_not_score(self):
        for title in ['2025-26 決算報告','2026-27 ルール変更','2026-10-13 お知らせ']:
            self.assertNotEqual(fetch.categorise(title),'kekka')
        self.assertEqual(fetch.categorise('東京 80-71 立川'),'kekka')

    def test_cancelled_and_missing_score(self):
        game=dict(home='東京',away='立川',status='cancelled',starts_at='2026-10-13T10:05:00+00:00')
        self.assertIn('中止',browse_ui.match_row(game,'2026-10-13'))
        self.assertNotIn('19:05',browse_ui.match_row(game,'2026-10-13'))
        game.update(status='final',home_score=None,away_score=71)
        self.assertNotIn('終了',browse_ui.match_row(game,'2026-10-13'))

    def test_no_games_vs_unknown(self):
        row=dict(date='2026-10-13',games=[],schedule_complete={'BP':True})
        text=browse_ui.day_body(row,2)
        self.assertIn('試合なし',text)
        self.assertIn('日程未確認',text)

    def test_release_boundary_jst(self):
        root=Path(__file__).resolve().parents[1]
        before=browse_ui.summaries(root,datetime(2026,10,13,22,59,tzinfo=preview_data.JST))
        after=browse_ui.summaries(root,datetime(2026,10,13,23,0,tzinfo=preview_data.JST))
        self.assertNotIn('2026-10-14',[r['date'] for r in before])
        self.assertIn('2026-10-14',[r['date'] for r in after])

    def test_generated_navigation_contract(self):
        root=Path(__file__).resolve().parents[1]
        soup=BeautifulSoup((root/'index.html').read_text(),'html.parser')
        # 10/21 承認：外部リンクは「公式・外部の更新」枠だけに、種類を付けて載せる（独自記事枠には混ぜない）
        external=[a for a in soup.select('div.main a[href^="http"]')]
        self.assertTrue(external)
        self.assertTrue(all(a.find_parent(id='updates') for a in external))
        self.assertIn(len(soup.select('#updates .upd-list li')),range(1,12))
        self.assertIn(len(BeautifulSoup((root/'news.html').read_text(),'html.parser').select('.item.ext')),range(5,11))
        result=BeautifulSoup((root/'cat-kekka.html').read_text(),'html.parser')
        self.assertFalse(result.select('.item.ext'))
        self.assertTrue(result.select_one('.date-chips'))
        self.assertIn('80 – 71',result.get_text())

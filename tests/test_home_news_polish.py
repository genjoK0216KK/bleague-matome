import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch
from bs4 import BeautifulSoup
from scripts import browse_ui, build, preview_data

class HomeNewsPolish(unittest.TestCase):
    def test_headings_follow_verified_results(self):
        now = datetime(2026,10,18,9,tzinfo=preview_data.JST)
        game = dict(competition='BP', home='A', away='B', status='scheduled')
        cases = [([game], '試合予定'), ([dict(game,ended=True,fixed=True,source='official',home_score=80,away_score=71)], '試合結果'), ([], '試合日程')]
        for games, expected in cases:
            with self.subTest(expected=expected), patch.object(browse_ui,'summaries',return_value=[dict(date='2026-10-18',games=games)]), patch.object(browse_ui.next_preview,'load',return_value=None):
                soup=BeautifulSoup(browse_ui.home(Path('.'),now),'html.parser')
                self.assertIn(expected,soup.select_one('.home-games .phase-label').text)
                self.assertIn('ベスト5・サブ5',soup.text)

    def test_every_news_page_navigation(self):
        for total in (1,2,7,8,24,100):
            for n in range(1,total+1):
                with self.subTest(total=total,n=n):
                    soup=BeautifulSoup(build.render_pager('news',n,total),'html.parser')
                    if total==1:
                        self.assertFalse(soup.select('nav')); continue
                    self.assertEqual(soup.select_one('[aria-current=page]').text,str(n))
                    self.assertEqual(bool(soup.select_one('[rel=prev]')),n>1)
                    self.assertEqual(bool(soup.select_one('[rel=next]')),n<total)
                    if n<total:self.assertEqual(soup.select_one('[rel=next]')['href'],build.page_file('news',n+1))
                    if n>1:self.assertEqual(soup.select_one('[rel=prev]')['href'],build.page_file('news',n-1))
                    if total>7:self.assertLessEqual(len([a for a in soup.select('a') if a.text.isdigit()]),4)

    def test_generated_news_counts_and_targets_preserved(self):
        import subprocess
        root=Path(__file__).resolve().parents[1]
        for p in [root/'news.html',*root.glob('news-[0-9]*.html')]:
            before=BeautifulSoup(subprocess.check_output(['git','show','HEAD:'+p.name],cwd=root,text=True),'html.parser')
            after=BeautifulSoup(p.read_text(),'html.parser')
            self.assertEqual([str(x) for x in before.select('.item.ext')],[str(x) for x in after.select('.item.ext')])
            for a in after.select('.pager a'):self.assertTrue((root/a['href']).exists())

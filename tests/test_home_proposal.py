"""トップ変更案（10/22・未承認）：既定は公開中の並び。案A/Bは今日と過去を混ぜない。"""
import json
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from bs4 import BeautifulSoup

from scripts import browse_ui, home_sections, next_preview, preview_data

ROOT = Path(__file__).resolve().parents[1]
NOW = datetime(2026, 10, 22, 9, 0, tzinfo=preview_data.JST)
ARTICLES = [
    dict(href='article-games-20261022.html', title='試合予定', date='2026.10.22', extra='', desc=''),
    dict(href='article-daily-20261021.html', title='ライセンス判定', date='2026.10.21', extra='B.PREMIER', desc=''),
    dict(href='article-daily-20261020.html', title='広島が8連勝', date='2026.10.20', extra='B.PREMIER', desc=''),
]


def rows():
    return [json.loads((ROOT / 'data/match_articles' / n).read_text())
            for n in ('article-games-20261022.json', 'article-games-20261021.json', 'article-games-20261019.json')]


class Proposal(unittest.TestCase):
    def render(self, variant):
        with patch.object(browse_ui, 'summaries', return_value=rows()), patch.object(next_preview, 'load', return_value=None):
            return BeautifulSoup(home_sections.home(ROOT, ARTICLES, [], [], '', NOW, variant=variant), 'html.parser')

    def test_default_stays_on_the_published_order(self):
        self.assertEqual(home_sections.HOME_VARIANT, 'current')

    def test_variant_a_order_and_folded_eff(self):
        soup = self.render('A')
        ids = [n['id'] for n in soup.find_all(['section', 'details'], id=True, recursive=False)]
        self.assertEqual(ids, ['today', 'own-articles', 'updates', 'ranking'])
        self.assertIn('10月22日（木）', soup.select_one('#today h2').text)
        self.assertEqual(len(soup.select('#today .match-row')), 4)
        self.assertIn('前日 10月21日（水）の 9 試合', soup.select_one('#today').text)
        fold = soup.select_one('details#ranking')
        self.assertIsNone(fold.get('open'))
        self.assertIn('10/19 の試合で活躍した選手', fold.summary.text)

    def test_past_articles_are_not_shown_as_today(self):
        soup = self.render('A')
        own = soup.select_one('#own-articles')
        self.assertEqual(own.h2.text, 'バスケ深掘り')
        self.assertIn('今日の記事は準備中です', own.text)
        self.assertEqual([a['href'] for a in own.select('a.own-card')],
                         ['article-daily-20261021.html', 'article-daily-20261020.html'])

    def test_variant_b_name_and_link(self):
        soup = self.render('B')
        self.assertEqual(soup.select_one('#own-articles h2').text, '編集部の記事')
        self.assertIn('10/19 の試合で活躍した選手', soup.select_one('#ranking').text)


if __name__ == '__main__':
    unittest.main()

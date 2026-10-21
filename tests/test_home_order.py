"""トップの並び（10/21 本人承認）：ランキング → 独自記事 → 公式・外部の更新 → 試合（補助）。"""
import json
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from bs4 import BeautifulSoup

from scripts import browse_ui, build, day_articles, home_sections, next_preview, preview_data

ROOT = Path(__file__).resolve().parents[1]
NEWS = [
    dict(title='公式のお知らせ', url='https://www.bleague.jp/news_detail/id=1', source='B.LEAGUE公式', date='2026-10-21'),
    dict(title='メディア記事', url='https://basket-count.com/a', source='バスケット・カウント', date='2026-10-21'),
]
MATOME = [dict(title='他社のまとめ', url='https://example.com/m', source='他社ブログ', date='2026-10-21')]
ARTICLES = [
    dict(href='article-games-20261019.html', title='10/19 試合結果', date='2026.10.19', extra='', desc=''),
    dict(href='article-stats-20261018.html', title='10月18日の貢献度ランキング', date='2026.10.18', extra='B.PREMIER / 貢献度ランキング', desc='TOP10'),
    dict(href='article-daily-20261021.html', title='ライセンス判定', date='2026.10.21', extra='B.PREMIER / クラブライセンス', desc='判定結果の解説'),
]


def game_day(date='2026-10-19'):
    return json.loads((ROOT / 'data/match_articles' / ('article-games-' + date.replace('-', '') + '.json')).read_text())


class HomeOrder(unittest.TestCase):
    def render(self, now, preview=None, rows=None):
        rows = rows if rows is not None else [game_day()]
        with patch.object(browse_ui, 'summaries', return_value=rows), \
             patch.object(next_preview, 'load', return_value=preview):
            # 10/21 承認の並び（'current'）の試験。10/22 からの既定は案C（test_home_proposal で試験）
            return BeautifulSoup(home_sections.home(ROOT, ARTICLES, NEWS, MATOME, '', now, variant='current'), 'html.parser')

    def test_sections_in_approved_order(self):
        soup = self.render(datetime(2026, 10, 22, 1, tzinfo=preview_data.JST))
        order = [s['id'] for s in soup.find_all('section', id=True, recursive=False)]
        self.assertEqual(order[:4], ['ranking', 'own-articles', 'updates', 'games'])

    def test_own_articles_exclude_external_and_result_pages(self):
        soup = self.render(datetime(2026, 10, 22, 1, tzinfo=preview_data.JST))
        own = soup.select_one('#own-articles')
        hrefs = [a['href'] for a in own.select('a.own-card')]
        self.assertEqual(hrefs, ['article-stats-20261018.html', 'article-daily-20261021.html'])
        self.assertFalse([a for a in own.select('a') if a['href'].startswith('http')])
        self.assertEqual([k.text for k in own.select('.own-kind')], ['分析', '解説・まとめ'])

    def test_updates_are_labelled_by_kind_and_external(self):
        soup = self.render(datetime(2026, 10, 22, 1, tzinfo=preview_data.JST))
        upd = soup.select_one('#updates')
        metas = [m.text for m in upd.select('.upd-meta')]
        self.assertTrue(metas[0].startswith('公式発信・B.LEAGUE公式'))
        self.assertTrue(metas[1].startswith('外部メディア・バスケット・カウント'))
        self.assertTrue(metas[2].startswith('他社まとめ・他社ブログ'))
        for a in upd.select('.upd-list a'):
            self.assertEqual(a['target'], '_blank')
            self.assertIn('nofollow', a['rel'])

    def test_game_day_leaders_match_stored_rank_one(self):
        row = game_day()
        soup = self.render(datetime(2026, 10, 22, 1, tzinfo=preview_data.JST), rows=[row])
        shown = [(tr.td.text, tr.strong.text, tr.find_all('td')[-1].text)
                 for tr in soup.select('#ranking table.leaders tbody tr') if tr.strong]
        expected = [(pos, p['name'], str(p['eff']))
                    for league in row['game_day_rankings']['leagues'].values()
                    for pos, players in league.get('positions', {}).items()
                    for p in players if p['rank'] == 1]
        self.assertTrue(expected)
        self.assertEqual(shown, expected)
        self.assertIn('対象日 2026-10-19', soup.select_one('#ranking h2').text)

    def test_valid_preview_uses_existing_lineup_renderer(self):
        preview = json.loads((ROOT / 'data/match_articles/next-preview.json').read_text())
        now = datetime(2026, 10, 21, 12, tzinfo=preview_data.JST)
        soup = self.render(now, preview=preview)
        ranking = soup.select_one('#ranking')
        self.assertIn('今季平均 EFF', ranking.select_one('.phase-label').text)
        self.assertEqual(ranking['data-preview-valid-until'], next_preview.valid_until(preview).isoformat())
        canonical = BeautifulSoup(day_articles.lineup_html(preview, heading=False), 'html.parser')
        self.assertEqual(str(ranking.select_one('.daily-lineups')), str(canonical.select_one('.daily-lineups')))
        self.assertIn('出場を確約するものではありません', ranking.text)

    def test_generated_index_follows_order_and_keeps_ad_off_top(self):
        soup = BeautifulSoup((ROOT / 'index.html').read_text(), 'html.parser')
        ids = [s.get('id') for s in soup.select('div.main > [id]')]
        # 10/22 04:10 本人承認で公開した案Cの並び
        self.assertEqual(ids[:5], ['today', 'own-articles', 'past-games', 'ranking', 'updates'])
        first = soup.select_one('aside.side').find(True, recursive=False)
        self.assertNotIn('adbox', first.get('class') or [])

    def test_home_styles_follow_design_contract(self):
        """独立QA（10/22）指摘：更新リンク48px・ランキング表見出し16px・注記は黒×ライム/角丸4px。"""
        import re
        css = (ROOT / 'design-system.css').read_text()

        def rule(selector):
            m = re.search(re.escape(selector) + r'\{([^}]*)\}', css)
            self.assertIsNotNone(m, selector)
            return m.group(1)

        self.assertIn('min-height:48px', rule('.upd-list a'))
        self.assertIn('font-size:16px', rule('.home-ranking th'))
        note = rule('.home-ranking .note')
        self.assertIn('border-left:4px solid #ccf43b', note)
        self.assertIn('border-radius:4px', note)

    def test_read_articles_has_description(self):
        rows = {a['href']: a for a in build.read_articles()}
        self.assertTrue(rows['article-daily-20261021.html']['desc'].startswith('Bリーグは10月20日'))


if __name__ == '__main__':
    unittest.main()

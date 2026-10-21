"""サムネの新しい構図（試合前プレビュー・独自比較）。入力に無い数値・名前を描かない。"""
import json
import re
import unittest
from pathlib import Path

from scripts import thumbgen

ROOT = Path(__file__).resolve().parents[1]
SAMPLES = ROOT / 'samples/thumb-20261022'


class Layouts(unittest.TestCase):
    def render(self, name):
        return thumbgen.render(json.loads((SAMPLES / name).read_text()))

    def test_preview_shows_every_card_and_no_score(self):
        svg = self.render('preview.json')
        for team in ('仙台', '横浜BC', 'A東京', '茨城', '八王子', '東京U', '湘南', '山口'):
            self.assertIn(team, svg)
        self.assertIn('10.22  19:05', svg)
        self.assertNotIn('FINAL', svg)
        self.assertNotIn('WIN', svg)

    def test_compare_draws_only_the_input_values(self):
        data = json.loads((SAMPLES / 'compare.json').read_text())
        svg = thumbgen.render(data)
        numbers = set(re.findall(r'>(\d+\.\d)<', svg))
        self.assertEqual(numbers, {str(r['value']) for r in data['rows']})
        for r in data['rows']:
            self.assertIn(r['name'], svg)

    def test_unknown_clubs_get_a_visible_color(self):
        self.assertEqual(thumbgen.visible_color('湘南', 0), thumbgen.FALLBACK[0])
        self.assertNotEqual(thumbgen.visible_color('仙台', 0), thumbgen.FALLBACK[0])

    def test_compare_note_does_not_overlap_brand(self):
        """独立実見：注記（取得日・出場未確認）が右下の「バスケまとめ」と同じ行で重なっていた。"""
        svg = self.render('compare.json')
        note_y = float(re.search(r'<text x="20" y="(\d+)"[^>]*>10/14', svg).group(1))
        brand_y = float(re.search(r'<text x="462" y="(\d+)"[^>]*>バスケまとめ', svg).group(1))
        self.assertGreaterEqual(brand_y - note_y, 12)
        last_row_bottom = max(float(y) + 24 for y in re.findall(r'<rect x="272" y="(\d+)"', svg))
        self.assertLess(last_row_bottom, note_y - 12)

    def test_preview_marks_unconfirmed_card(self):
        svg = self.render('preview.json')
        self.assertEqual(svg.count('未再確認'), 1)
        self.assertNotIn('当日確認済', svg)

    def test_simple_variant_has_three_elements(self):
        svg = self.render('simple-compare.json')
        texts = [t for t in re.findall(r'>([^<>]+)</text>', svg) if t.strip() and t != 'バスケまとめ']
        self.assertEqual(texts, ['比較', '湘南 vs 山口', 'ポジション別 今季平均EFF'])

    def test_samples_are_up_to_date(self):
        for name in ('preview', 'compare', 'simple-preview', 'simple-compare'):
            svg = self.render(name + '.json')
            body = lambda t: re.sub(r'<style>@font-face.*?</style>', '', t, flags=re.S)
            self.assertEqual(body(svg), body((SAMPLES / ('sample-' + name + '.svg')).read_text()))

    def test_existing_types_still_render(self):
        for d in thumbgen.SAMPLES.values():
            self.assertTrue(thumbgen.render(d).startswith('<svg'))


if __name__ == '__main__':
    unittest.main()

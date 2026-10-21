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

    def test_samples_are_up_to_date(self):
        for name in ('preview', 'compare'):
            svg = self.render(name + '.json')
            body = lambda t: re.sub(r'<style>@font-face.*?</style>', '', t, flags=re.S)
            self.assertEqual(body(svg), body((SAMPLES / ('sample-' + name + '.svg')).read_text()))

    def test_existing_types_still_render(self):
        for d in thumbgen.SAMPLES.values():
            self.assertTrue(thumbgen.render(d).startswith('<svg'))


if __name__ == '__main__':
    unittest.main()

"""Published-ID retention and standalone stats shared-head regressions."""
import copy
import json
from pathlib import Path
from unittest.mock import patch
from test_stats_daily import Base, game
from scripts import stats, build, page_assets, save_stats


class PublishedIDs(Base):
    def test_missing_old_ids_retained_for_replacement_and_mixed_growth(self):
        date = '2026-10-22'
        original = [game('506495'), game('506496')]
        with patch.object(stats, 'thumbnail'):
            self.save(date, copy.deepcopy(original)); self.run_stats()
            path = self.root / 'data/stats/2026-10-22.json'
            article = self.root / 'article-stats-20261022.html'
            expected = (path.read_bytes(), article.read_bytes())
            for keys in [('506495',), ('506495', '506500'), ('506500', '506501'),
                         ('506495', '506500', '506501')]:
                with self.subTest(keys=keys):
                    self.save(date, [game(k) for k in keys]); self.run_stats()
                    self.assertEqual((path.read_bytes(), article.read_bytes()), expected)
                    self.assertEqual(self.state()['days'][date]['state'], 'held')
                    self.assertIn('506496', self.state()['pending'])

    def test_superset_and_same_ids_with_official_correction_allowed(self):
        date = '2026-10-22'
        with patch.object(stats, 'thumbnail'):
            self.save(date, [game('506495')]); self.run_stats()
            self.save(date, [game('506495'), game('506496')]); self.run_stats()
            self.assertEqual({g['key'] for g in self.day_json(date)['games']}, {'506495','506496'})
            corrected = game('506495'); corrected['players'][0]['EFF'] = 77
            self.save(date, [corrected, game('506496')]); self.run_stats()
            self.assertEqual(self.day_json(date)['eff_top'][0]['eff'], 77)


class SharedHead(Base):
    def test_standalone_run_and_repeat_keeps_configured_ga_and_css(self):
        cfg = self.root / 'data/site_config.json'
        cfg.write_text(json.dumps({'ga4_id':'G-TEST123','x_list_url':''}))
        with patch.object(stats, 'thumbnail'):
            self.save('2026-10-22', [game('506495')]); self.run_stats(); self.run_stats()
        for filename in ['stats.html','article-stats-20261022.html']:
            text = (self.root / filename).read_text()
            self.assertEqual(text.count('AUTO:GA:START'), 1)
            self.assertEqual(text.count('gtag/js?id=G-TEST123'), 1)
            self.assertEqual(text.count('href="design-system.css?v=1"'), 1)
            self.assertIn('site-nav.js',text)
            self.assertEqual(page_assets.ensure(text,'G-TEST123'), text)

    def test_empty_config_omits_tracking_but_not_css(self):
        text = stats.page('title','desc','stats.html','body')
        self.assertNotIn('googletagmanager',text)
        self.assertIn('design-system.css?v=1',text)

    def test_shared_assets_are_idempotent_and_build_compatible(self):
        raw='<html><head></head><body></body></html>'
        first = page_assets.ensure(raw,'G-TEST123')
        self.assertEqual(first,page_assets.ensure(first,'G-TEST123'))
        self.assertEqual(build.ensure_ga(raw,'G-TEST123'),page_assets.ensure_ga(raw,'G-TEST123'))
        self.assertNotIn('googletagmanager',page_assets.ensure(first,''))

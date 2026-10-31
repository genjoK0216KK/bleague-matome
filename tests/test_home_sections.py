import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts import home_sections


class GamesLine(unittest.TestCase):
    def test_season_eff_link_stays_when_no_schedule_is_saved(self):
        with tempfile.TemporaryDirectory() as root:
            html = home_sections.games_line(Path(root), datetime(2026, 10, 31, 12), [])
        self.assertIn('今日の試合：日程を確認中', html)
        self.assertIn('href="next-games.html">今季平均EFFのベスト5・サブ5 ›</a>', html)
        self.assertNotIn('試合の詳細', html)


if __name__ == '__main__':
    unittest.main()

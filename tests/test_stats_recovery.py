"""Regression tests for the stats day-aggregation recurrence bug.

A day that was published while only some of its games had been recorded must be
re-aggregated once the remaining games are fixed — it must NOT be skipped just
because the date is already in ``state['published']`` (the original bug), and a
stable day must not be rewritten when nothing new appears.
"""
import json
import os
import tempfile
import unittest
from unittest.mock import patch

from scripts import stats

DATE = "2026-10-17"


def fake_player(name, eff, pts=10):
    return {
        "name": name, "name_en": name, "no": "1", "team": "秋田", "team_full": "秋田",
        "opp": "宇都宮", "won": True, "key": "x", "jp": None,
        "nationality": None, "nationality_verified": False,
        "min": 25.0, "pts": pts, "reb": 5, "ast": 3, "stl": 1, "blk": 0, "tov": 1,
        "fgm": 4, "fga": 8, "tpm": 1, "tpa": 3, "ftm": 1, "fta": 2, "eff": eff, "pm": 5,
    }


def fake_game(key, top_eff):
    return {
        "key": key, "date": DATE, "convention": "りそなB.LEAGUE PREMIER",
        "ended": True, "fixed": True, "home": "秋田", "away": "宇都宮",
        "home_full": "秋田ノーザンハピネッツ", "away_full": "宇都宮ブレックス",
        "home_score": 100, "away_score": 90, "ot": False, "stadium": "A",
        "same_day": [key],
        "players": [fake_player(f"選手{key}", top_eff), fake_player(f"控え{key}", 5, 4)],
    }


class StatsRecurrence(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        stats.STATS_DIR = os.path.join(self.tmp, "data", "stats")
        stats.STATE_PATH = os.path.join(stats.STATS_DIR, "state.json")
        stats.ROOT = self.tmp
        os.makedirs(stats.STATS_DIR, exist_ok=True)

    def _run_with(self, keys, effs):
        games = {k: fake_game(k, e) for k, e in zip(keys, effs)}

        def fake_get(url):
            if url == stats.SCHEDULE_URL:
                return " ".join(f"ScheduleKey={k}" for k in keys)
            return ""

        def fake_parse(key, page):
            return games.get(str(key))

        with patch.object(stats, "get", side_effect=fake_get), \
             patch.object(stats, "parse_game", side_effect=fake_parse):
            stats.run()

    def _day(self):
        with open(os.path.join(stats.STATS_DIR, f"{DATE}.json"), encoding="utf-8") as f:
            return json.load(f)

    def _state(self):
        with open(stats.STATE_PATH, encoding="utf-8") as f:
            return json.load(f)

    def test_published_day_reaggregates_when_late_games_arrive(self):
        # 最初は2試合だけで公開（取りこぼし状態を再現）
        self._run_with(["506470", "506471"], [35, 30])
        first = self._day()
        self.assertEqual(len(first["games"]), 2)
        self.assertEqual(first["eff_top"][0]["eff"], 35)
        self.assertIn(DATE, self._state()["published"])

        # 後から残り4試合が確定 → 公開済みでもスキップせず6試合に再集計される
        self._run_with(
            ["506467", "506468", "506469", "506470", "506471", "506472"],
            [42, 20, 20, 35, 30, 20],
        )
        after = self._day()
        self.assertEqual(len(after["games"]), 6, "公開済み日が再集計されていない（取りこぼし回収失敗）")
        self.assertEqual(after["eff_top"][0]["eff"], 42, "追加試合のトップが反映されていない")
        self.assertEqual(after["player_count"], 12)

    def test_stable_published_day_not_rewritten(self):
        self._run_with(["506467", "506468"], [42, 20])
        path = os.path.join(stats.STATS_DIR, f"{DATE}.json")
        before = os.stat(path).st_mtime_ns
        # 同じ試合集合で再実行 → 書き換えない（churn防止）
        self._run_with(["506467", "506468"], [42, 20])
        self.assertEqual(os.stat(path).st_mtime_ns, before, "変化が無いのに再書き込みされた")

    def test_unpublished_incomplete_day_is_held(self):
        # 1試合が未確定なら未公開日は持ち越し、公開しない
        g_done = fake_game("506467", 42)
        g_pending = fake_game("506468", 20)
        g_pending["fixed"] = False
        g_pending["players"] = []
        games = {"506467": g_done, "506468": g_pending}
        with patch.object(stats, "get", side_effect=lambda u: "ScheduleKey=506467 ScheduleKey=506468" if u == stats.SCHEDULE_URL else ""), \
             patch.object(stats, "parse_game", side_effect=lambda k, p: games.get(str(k))):
            stats.run()
        state = self._state()
        self.assertNotIn(DATE, state["published"], "未確定日を公開してはいけない")
        self.assertIn("506467", state["pending"])


if __name__ == "__main__":
    unittest.main()

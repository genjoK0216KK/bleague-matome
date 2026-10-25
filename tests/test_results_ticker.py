import unittest
from datetime import datetime, timedelta

from scripts import results_ticker as t
from scripts import official_data as official

NOW = datetime(2026, 10, 26, 21, 0, tzinfo=t.JST)


def game(gid, start, final=False, status="unconfirmed", league="BP"):
    g = {"game_id": gid, "competition": league, "starts_at": start.isoformat(), "status": status,
         "ended": final, "fixed": final}
    if final:
        g.update(source="https://www.bleague.jp/game_detail/?ScheduleKey=" + gid, home_score=80, away_score=70)
    return g


def day(games, rankings=True):
    leagues = {g["competition"] for g in games if g.get("status") not in ("cancelled", "postponed")}
    return {"schedule_complete": {k: True for k in official.LEAGUES}, "games": games,
            "game_day_rankings": {"leagues": {k: {} for k in leagues} if rankings else {}}}


class Due(unittest.TestCase):
    def test_game_still_in_progress_is_not_due(self):
        s = day([game("1", NOW - timedelta(minutes=60))])
        self.assertIsNone(t.due_since(s, NOW))

    def test_game_past_expected_end_is_due(self):
        start = NOW - timedelta(minutes=115)
        self.assertEqual(t.due_since(day([game("1", start)]), NOW), start + t.FINISH_AFTER)

    def test_all_final_with_rankings_is_done(self):
        s = day([game("1", NOW - timedelta(hours=3), final=True)])
        self.assertIsNone(t.due_since(s, NOW))

    def test_all_final_but_top3_missing_is_due(self):
        s = day([game("1", NOW - timedelta(hours=3), final=True)], rankings=False)
        self.assertEqual(t.due_since(s, NOW), NOW)

    def test_cancelled_game_is_ignored(self):
        s = day([game("1", NOW - timedelta(hours=3), final=True),
                 game("2", NOW - timedelta(hours=3), status="cancelled")])
        s["games"][1]["source"] = "https://www.bleague.jp/"
        self.assertIsNone(t.due_since(s, NOW))

    def test_missing_day_is_fetched(self):
        self.assertEqual(t.due_since(None, NOW), NOW)

    def test_unreadable_start_is_checked(self):
        g = game("1", NOW)
        g["starts_at"] = ""
        self.assertEqual(t.due_since(day([g]), NOW), NOW)


class Throttle(unittest.TestCase):
    def test_fresh_result_dispatches_every_tick(self):
        due = NOW - timedelta(minutes=10)
        self.assertTrue(t.should_dispatch(due, NOW, NOW - timedelta(minutes=5)))

    def test_stale_unconfirmed_result_is_throttled(self):
        due = NOW - timedelta(hours=5)
        self.assertFalse(t.should_dispatch(due, NOW, NOW - timedelta(minutes=10)))
        self.assertTrue(t.should_dispatch(due, NOW, NOW - timedelta(minutes=31)))

    def test_nothing_due(self):
        self.assertFalse(t.should_dispatch(None, NOW, None))


if __name__ == "__main__":
    unittest.main()

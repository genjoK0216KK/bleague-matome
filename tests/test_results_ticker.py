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
        start = NOW - timedelta(hours=3)
        s = day([game("1", start, final=True)], rankings=False)
        self.assertEqual(t.need(s, NOW), (start + t.FINISH_AFTER, "rankings"))

    def test_cancelled_game_is_ignored(self):
        s = day([game("1", NOW - timedelta(hours=3), final=True),
                 game("2", NOW - timedelta(hours=3), status="cancelled")])
        s["games"][1]["source"] = "https://www.bleague.jp/"
        self.assertIsNone(t.due_since(s, NOW))

    def test_missing_day_is_fetched(self):
        self.assertEqual(t.need(None, NOW), (NOW, "missing"))

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


class Loop(unittest.TestCase):
    """main() を時計・保存データ・起動を偽物にして回し、起動回数を数える（独立QA RT-1〜3 の再現条件）。"""

    def run_loop(self, start, minutes, today=None, yday=None):
        from unittest import mock
        clock = {"now": start}
        calls = []

        class FakeDT(datetime):
            @classmethod
            def now(cls, tz=None):
                return clock["now"]

        def sleep(sec):
            clock["now"] += timedelta(seconds=sec)
            if clock["now"] - start >= timedelta(minutes=minutes):
                raise StopIteration

        def load(date):
            return today if date == start.date() else yday

        with mock.patch.object(t, "datetime", FakeDT), mock.patch.object(t.time, "sleep", sleep), \
                mock.patch.object(t, "load", load), mock.patch.object(t, "site_update_busy", return_value=False), \
                mock.patch.object(t, "dispatch", side_effect=lambda: calls.append(clock["now"]) or True), \
                mock.patch.object(t.subprocess, "run"), mock.patch.object(t, "log"):
            try:
                t.main()
            except StopIteration:
                pass
        return calls

    def test_rt1_day_without_saved_data_is_checked_every_30_minutes(self):
        calls = self.run_loop(NOW, 60)
        self.assertEqual(len(calls), 2)            # 修正前は 12〜13回
        self.assertEqual(calls[1] - calls[0], timedelta(minutes=30))

    def test_rt2_old_final_day_waiting_for_top3_is_thinned(self):
        old = day([game("1", NOW - timedelta(hours=6), final=True)], rankings=False)
        calls = self.run_loop(NOW, 60, today=old)
        self.assertEqual(len(calls), 2)            # 修正前は 12〜13回（30分間引きが効かない）

    def test_rt2_fresh_top3_wait_still_retries_every_tick(self):
        fresh = day([game("1", NOW - timedelta(minutes=110), final=True)], rankings=False)
        self.assertEqual(len(self.run_loop(NOW, 30, today=fresh)), 6)   # 5分ごと

    def test_rt3_no_dispatch_at_or_after_the_end_time(self):
        pending = day([game("1", NOW - timedelta(hours=1))])
        for start in (datetime(2026, 10, 27, 2, 0, tzinfo=t.JST), datetime(2026, 10, 27, 2, 5, tzinfo=t.JST)):
            with self.subTest(start=start):
                late = day([game("1", start - timedelta(hours=4))])
                self.assertEqual(self.run_loop(start, 30, today=late, yday=pending), [])

    def test_rt3_stops_before_run_limit_without_extra_dispatch(self):
        begin = datetime(2026, 10, 26, 15, 0, tzinfo=t.JST)
        live = day([game("1", begin - timedelta(minutes=110))])
        calls = self.run_loop(begin, 400, today=live)
        self.assertEqual(len(calls), 36 + 4)     # 終了見込みから3時間は5分ごと、以後30分ごと
        self.assertLess(calls[-1] - begin, t.RUN_LIMIT)

    def test_missing_yesterday_is_not_fetched(self):
        done_today = day([game("1", NOW + timedelta(hours=2))])     # 今日は試合前
        self.assertEqual(self.run_loop(NOW, 30, today=done_today, yday=None), [])


if __name__ == "__main__":
    unittest.main()

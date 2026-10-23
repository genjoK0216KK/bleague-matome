"""Regression tests for the stats day-aggregation recurrence bug (10/17・10/18).

A day that was published while only some of its games had been recorded must be
re-aggregated once the remaining games are fixed, a stable day must not be rewritten,
and an unpublished incomplete day must be held. Since 10/24 the input is the saved,
verified-final results (not a fresh official fetch); the date is fixed so the tests do not
depend on today's date.
"""
from datetime import datetime

from scripts import stats
from tests.test_stats_daily import Base, game

DATE = "2026-10-17"
NOW = datetime(2026, 10, 18, 7, 0, tzinfo=stats.JST)


def finals(effs):
    return [game(k, players=[{**r, "EFF": e} if r["PlayerNameJ"].startswith("選手") else r
                             for r in game(k)["players"]]) for k, e in effs.items()]


class StatsRecurrence(Base):
    def test_published_day_reaggregates_when_late_games_arrive(self):
        self.save(DATE, finals({"506470": 35, "506471": 30}))
        self.run_stats(NOW)
        first = self.day_json(DATE)
        self.assertEqual(len(first["games"]), 2)
        self.assertEqual(first["eff_top"][0]["eff"], 35)
        self.assertIn(DATE, self.state()["published"])

        self.save(DATE, finals({"506467": 42, "506468": 20, "506469": 20, "506470": 35, "506471": 30, "506472": 20}))
        self.run_stats(NOW)
        after = self.day_json(DATE)
        self.assertEqual(len(after["games"]), 6, "公開済み日が再集計されていない（取りこぼし回収失敗）")
        self.assertEqual(after["eff_top"][0]["eff"], 42, "追加試合のトップが反映されていない")
        self.assertEqual(after["player_count"], 12)

    def test_stable_published_day_not_rewritten(self):
        self.save(DATE, finals({"506467": 42, "506468": 20}))
        self.run_stats(NOW)
        path = self.root / "data/stats" / f"{DATE}.json"
        before = path.stat().st_mtime_ns
        self.run_stats(NOW)
        self.assertEqual(path.stat().st_mtime_ns, before, "変化が無いのに再書き込みされた")

    def test_unpublished_incomplete_day_is_held(self):
        self.save(DATE, finals({"506467": 42}) + [game("506468", status="unconfirmed")])
        self.run_stats(NOW)
        state = self.state()
        self.assertNotIn(DATE, state["published"], "未確定日を公開してはいけない")
        self.assertEqual(state["pending"], {"506468": DATE})
        self.assertEqual(state["days"][DATE]["holds"][0]["reason"], "record_not_fixed")

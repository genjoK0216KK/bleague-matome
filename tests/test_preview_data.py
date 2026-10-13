import unittest
from scripts.preview_data import daily_results, jst_date, position_rankings


def player(player_id="p1", **changes):
    p = dict(player_id=player_id, name="TEST PLAYER", positions=["SF", "PF"],
             season="2026-27", competition="BP", metric="EFF", aggregation="total",
             total=130, coverage_complete=True, availability="unknown",
             stats_source="https://example.invalid/stats", position_source="https://example.invalid/player")
    return dict(p, **changes)


def game(game_id="g1", **changes):
    g = dict(game_id=game_id, season="2026-27", competition="B1", starts_at="2026-10-13T10:00:00Z",
             ended=True, fixed=True, home_score=80, away_score=71, source="https://example.invalid/game")
    return dict(g, **changes)


def rank(players):
    return position_rankings(players, season="2026-27", competition="BP", metric="EFF")


def results(games, **changes):
    args = dict(date="2026-10-13", season="2026-27", competitions=["B1", "BN"],
                schedule_complete={"B1": True, "BN": True})
    args.update(changes)
    return daily_results(games, **args)


class Rankings(unittest.TestCase):
    def test_missing_not_zero(self):
        r = rank([player(total=None)])
        self.assertEqual(r["positions"]["SF"], [])
        self.assertEqual(r["excluded"][0]["exclusion_reason"], "total_unverified")

    def test_ties_and_multiple_positions(self):
        r = rank([player("a"), player("b"), player("c", total=129)])
        self.assertEqual([p["rank"] for p in r["positions"]["SF"]], [1, 1, 3])
        self.assertEqual(len(r["positions"]["PF"]), 3)

    def test_no_average_conversion(self):
        self.assertEqual(len(rank([player(aggregation="average", total=26)]) ["excluded"]), 1)

    def test_wrong_scope_and_partial_coverage(self):
        for changes in ({"season": "2025-26"}, {"competition": "B1"}, {"coverage_complete": False}):
            self.assertEqual(len(rank([player(**changes)])["excluded"]), 1)

    def test_unknown_is_not_expected(self):
        self.assertEqual(rank([player()])["positions"]["SF"][0]["availability"], "unknown")

    def test_absence_and_evidence(self):
        self.assertEqual(rank([player(availability="out", availability_source="https://example.invalid/injury")])["positions"]["SF"], [])
        with self.assertRaises(ValueError):
            rank([player(availability="expected")])

    def test_invalid_and_zero_totals(self):
        for value in ("NaN", "Infinity", "bad", True):
            self.assertEqual(len(rank([player(total=value)])["excluded"]), 1)
        self.assertEqual(rank([player(total=0)])["positions"]["SF"][0]["total"], 0)

    def test_duplicate_identity(self):
        self.assertEqual(len(rank([player(), player()])["positions"]["SF"]), 1)
        with self.assertRaises(ValueError):
            rank([player(), player(total=131)])

    def test_positions_require_source(self):
        for changes in ({"positions": []}, {"position_source": None}, {"positions": ["F"]}):
            self.assertEqual(len(rank([player(**changes)])["excluded"]), 1)


class Results(unittest.TestCase):
    def test_jst_boundary(self):
        self.assertEqual(jst_date("2026-10-12T15:00:00Z"), "2026-10-13")
        self.assertEqual(jst_date("2026-10-13T15:00:00Z"), "2026-10-14")
        with self.assertRaises(ValueError):
            jst_date("2026-10-13T10:00:00")

    def test_schedule_fallback_date_is_excluded(self):
        self.assertEqual(results([game(starts_at="2026-10-22T19:00:00+09:00")])["status"], "no_games")

    def test_empty_vs_failed_schedule(self):
        self.assertEqual(results([])["status"], "no_games")
        self.assertEqual(results([], schedule_complete={"B1": True})["status"], "pending")

    def test_both_leagues_one_article(self):
        r = results([game(), game("g2", competition="BN")])
        self.assertEqual(r["status"], "ready")
        self.assertEqual(len(r["games"]), 2)
        self.assertEqual(r["article_key"], "article-results-one-next-20261013")

    def test_unfinished_or_missing_score_blocks(self):
        for changes in ({"ended": False}, {"fixed": False}, {"home_score": None}, {"source": None}):
            self.assertEqual(results([game(**changes)])["status"], "pending")

    def test_individual_requires_evidence(self):
        self.assertEqual(results([game(notable_reason="TEST")])["individual_candidates"], [])
        self.assertEqual(len(results([game(notable_reason="TEST", notable_source="https://example.invalid/report")])["individual_candidates"]), 1)

    def test_duplicate_games_and_season(self):
        self.assertEqual(len(results([game(), game()])["games"]), 1)
        self.assertEqual(results([game(season="2025-26")])["status"], "no_games")
        with self.assertRaises(ValueError):
            results([game(), game(home_score=81)])


if __name__ == "__main__":
    unittest.main()

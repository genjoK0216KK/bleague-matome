"""Offline preparation layer; normalized inputs are NOT an official API schema.

No fetching, publishing, file writes, or fallback metric calculation. Adapters must
verify official season, competition, identities, positions, availability evidence,
and cumulative metric coverage before passing records to these functions.
"""
from datetime import datetime, timedelta, timezone
from decimal import Decimal

JST = timezone(timedelta(hours=9))
POSITIONS = ("PG", "SG", "SF", "PF", "C")
AVAILABILITY = {"expected", "unknown", "out", "entry_confirmed", "unannounced", "suspended"}


def jst_date(timestamp):
    """Use actual game time, never a requested schedule URL's date."""
    value = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
    if value.tzinfo is None:
        raise ValueError("A timezone-aware actual game timestamp is required")
    return value.astimezone(JST).date().isoformat()


def position_rankings(players, *, season, competition, metric):
    """Rank both next-game rosters by verified season totals, with competition ties.

    Missing/unverified totals stay out of rankings. Unknown availability remains
    explicitly unknown; confirmed absences are returned separately. A multi-position
    player appears once in each officially registered position. IDs, not names,
    identify players. Conflicting duplicate IDs fail closed.
    """
    groups = {p: [] for p in POSITIONS}
    excluded, seen = [], {}
    for player in players:
        p = dict(player)
        player_id = p["player_id"]
        if player_id in seen:
            if seen[player_id] != p:
                raise ValueError("Conflicting duplicate player: " + player_id)
            continue
        seen[player_id] = p
        if p.get("availability", "unknown") not in AVAILABILITY:
            raise ValueError("Unsupported availability")
        p.setdefault("availability", "unknown")
        if p["availability"] not in ("unknown", "unannounced") and not p.get("availability_source"):
            raise ValueError("Availability requires official evidence")
        reason = None
        if p.get("season") != season or p.get("competition") != competition:
            reason = "scope_mismatch"
        elif p["availability"] in ("out", "suspended"):
            reason = "out"
        elif p.get("games") == 0:
            reason = "no_appearance"
        elif not p.get("positions") or any(pos not in POSITIONS for pos in p["positions"]):
            reason = "position_unknown"
        elif not p.get("position_source"):
            reason = "position_unverified"
        elif (p.get("metric") != metric or p.get("aggregation") != "total"
              or p.get("total") is None or p.get("coverage_complete") is not True
              or not p.get("stats_source")):
            reason = "total_unverified"
        else:
            try:
                total = Decimal(str(p["total"]))
            except Exception:
                reason = "total_invalid"
            else:
                if not total.is_finite():
                    reason = "total_invalid"
        if reason:
            excluded.append(dict(p, exclusion_reason=reason))
            continue
        for pos in dict.fromkeys(p["positions"]):
            groups[pos].append(dict(p, total=total))
    for rows in groups.values():
        rows.sort(key=lambda p: (-p["total"], p["player_id"]))
        previous, rank = None, 0
        for index, p in enumerate(rows, 1):
            if previous != p["total"]:
                rank = index
            p["rank"] = rank
            previous = p["total"]
    return {"positions": groups, "excluded": excluded}


def is_verified_final(game):
    """Single final-result predicate shared by planning, highlights and rendering."""
    return (game.get("status") not in ("cancelled", "postponed")
            and game.get("ended") is True and game.get("fixed") is True
            and bool(game.get("source"))
            and all(type(game.get(key)) is int and game[key] >= 0
                    for key in ("home_score", "away_score")))


def daily_results(games, *, date, season, competitions, schedule_complete):
    """Plan one combined article per JST date; publish only verified final records.

    `schedule_complete` must explicitly confirm each requested competition's
    authoritative daily schedule, including empty schedules. Empty is not a fetch
    failure. The caller must handle cancellations/postponements in the adapter.
    """
    competitions = tuple(competitions)
    selected, seen = [], {}
    for raw in games:
        if raw.get("season") != season or raw.get("competition") not in competitions:
            continue
        actual_date = raw.get("official_date") if raw.get("status") in ("cancelled", "postponed") else None
        if (actual_date or jst_date(raw["starts_at"])) != date:
            continue
        game = dict(raw)
        key = (game["competition"], game["game_id"])
        if key in seen:
            if seen[key] != game:
                raise ValueError("Conflicting duplicate game: " + game["game_id"])
            continue
        seen[key] = game
        selected.append(game)
    selected.sort(key=lambda g: (g["competition"], (g.get("starts_at") or ""), g["game_id"]))
    complete = all(schedule_complete.get(c) is True for c in competitions)
    final = all((g.get("status") in ("cancelled", "postponed") and g.get("source"))
                or is_verified_final(g) for g in selected)
    status = "pending" if not complete or not final else "ready" if selected else "no_games"
    return {"date": date, "status": status,
            "article_key": "article-results-one-next-" + date.replace("-", ""),
            "games": selected,
            # Editorially verified reason + evidence required; no arbitrary score threshold.
            "individual_candidates": [g for g in selected if status == "ready" and is_verified_final(g)
                                      and g.get("notable_reason") and g.get("notable_source")]}

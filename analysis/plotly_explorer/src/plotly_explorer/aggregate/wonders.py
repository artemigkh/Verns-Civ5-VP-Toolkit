"""Wonders report fact tables: every wonder completion, and who could have built it.

Two CSVs, built in one pass over a single pushed-down query:

* ``wonder_builds``    — one row per wonder completed: game, builder, wonder,
  unlock era and completion turn.
* ``wonder_game_civs`` — one row per (game, civ) that played a retained game,
  carrying the social-policy branches that civ opened in it.

Unlike every other report here, this one ships *facts* rather than summaries: the
frontend filters by civilization and by policy-branch cohort, and both charts —
the per-civ averages and the completion-turn KDEs — are recomputed per filter.
Precomputing them is not an option, since it would take a curve set per
(civ x branch subset), i.e. 44 x 2^12 of them. The facts are small enough to ship
whole (~13.7k builds, ~2k pairs) and the aggregation is cheap in JS; see
``assets/wonders.js``, which owns the KDE and the averages.

**There is no wonders table.** ``BuildingsOverview`` is a per-turn snapshot of
what every civ owns, so a wonder's completion turn is the first turn it appears:
``MIN(Turn)`` per (GameId, Civ, Building). Conquest transfers wonders, which is
why the same wonder shows up under two to four civs in a game; the civ that owns
it earliest is the builder and the later owners are dropped, so a capture is
never counted as a construction. The scan and the group-by run in the DB —
``BuildingsOverview`` is ~40M rows, far too large to read whole (see
:mod:`plotly_explorer.db`) — and only the builder rows come back.

``era`` is the wonder's *unlock* era (metadata.load_wonder_eras), never the
game-state era of the civ that built it: the point of both charts is when a
wonder becomes available versus when it actually gets finished.

Games whose building log does not start at turn 1 are dropped, because their
completion turns are left-censored (see :func:`_fully_logged_games`).

``wonder_game_civs`` is what makes an average a *rate*: it lists the (game, civ)
pairs that could have built something, including the ones that built nothing, so
the frontend divides by games played rather than by games with a wonder. That
deliberately diverges from the R prototype
(``analysis/r_scripts/14b_wonders_stacked_bar.R``), which divides by the games a
civ built at least one wonder in — a workaround for the old Spark
``power_ranking`` carrying only partial game counts, noted in
``14_wonders_per_civ_lollipop.R``. That input is fixed here, and dividing by the
smaller denominator inflates weak wonder-builders by up to 55%. Carrying the
branches on the same row means a branch-filtered cohort narrows the numerator and
the denominator together.
"""

from __future__ import annotations

import pandas as pd

from ..config import Config
from ..db import read_query, read_table
from ..metadata import load_wonder_eras
from .cache import ensure_group
from .policies_performance import BRANCH_ORDER, BRANCH_SET

# A game whose BuildingsOverview log starts after this turn is dropped: its
# completion turns are left-censored at the log start (see _fully_logged_games).
# Real games log from turn 1; the cutoff only allows for an off-by-one start.
MAX_LOG_START_TURN = 2

# Separator for the branch list packed into one wonder_game_civs column. Chosen
# because no VP branch name contains it (unlike the comma in "Peace, Land, Bread").
BRANCH_SEP = "|"

# Cache-busting version for the wonder set and the builder rule (see
# ensure_group's ``fingerprint``). Bump on any change to WONDER_ERA_OVERRIDES,
# to _BUILDER_SQL, or to the columns below.
WONDER_RULES_VERSION = 4

OUTPUT_COLUMNS_BUILDS = ["game_id", "civ", "wonder", "era", "turn"]
OUTPUT_COLUMNS_GAME_CIVS = ["game_id", "civ", "branches"]


# ---------------------------------------------------------------------------
# Aggregation
# ---------------------------------------------------------------------------

# ``game_start`` is the first turn a game logged buildings at all (every civ owns
# a Palace from turn 1, so over the whole table this is the log's start, not the
# first wonder); ``first_owner`` is the first turn each civ is seen holding each
# wonder; ``ranked`` then keeps only the earliest of those owners per (game,
# wonder), i.e. the civ that built it. Kept portable across SQLite (>= 3.25) and
# DuckDB.
_BUILDER_SQL = """
WITH game_start AS (
    SELECT "GameId" AS GameId, MIN("Turn") AS FirstLoggedTurn
    FROM "BuildingsOverview"
    GROUP BY "GameId"
),
first_owner AS (
    SELECT "GameId" AS GameId,
           "Civ"    AS Civ,
           "Building" AS Building,
           MIN("Turn") AS Turn
    FROM "BuildingsOverview"
    WHERE "Building" IN ({names})
    GROUP BY "GameId", "Civ", "Building"
),
ranked AS (
    SELECT GameId, Civ, Building, Turn,
           ROW_NUMBER() OVER (PARTITION BY GameId, Building
                              ORDER BY Turn, Civ) AS rn
    FROM first_owner
)
SELECT r.GameId, r.Civ, r.Building, r.Turn, s.FirstLoggedTurn
FROM ranked r
JOIN game_start s ON s.GameId = r.GameId
WHERE r.rn = 1
"""


def _sql_string_list(names: list[str]) -> str:
    """SQL literal list of ``names`` (single quotes doubled)."""
    return ", ".join("'" + n.replace("'", "''") + "'" for n in names)


def _fully_logged_games(cfg: Config, df: pd.DataFrame) -> set:
    """GameIds whose building log covers the whole game, and which are real games.

    Two filters. ``game_result.csv`` drops the sub-turn-100 dev test completions,
    as everywhere else in the pipeline. The second is specific to this report:
    82 of the 339 Warlord games only start logging ``BuildingsOverview`` partway
    in (a few past turn 300), and every wonder the civ already held then shows up
    at that first logged turn. Those completion turns are left-censored — they
    are log starts, not build turns — and they clump: every Ancient wonder gained
    an identical 50-completion spike late in the game. Nothing distinguishes a
    censored row from a real one after the fact, so the whole game is dropped
    rather than a doomed attempt at repairing it.
    """
    valid = set(pd.read_csv(cfg.game_result_path)["game_id"])
    starts = df.drop_duplicates("game_id").set_index("game_id")["FirstLoggedTurn"]
    complete = set(starts[starts <= MAX_LOG_START_TURN].index)
    return valid & complete


def _build_builds(cfg: Config, wonder_eras: dict[str, str]) -> pd.DataFrame:
    """One row per wonder actually completed, in fully-logged real games.

    The retained game ids ride along as ``.attrs["games"]`` so the companion
    (game, civ) table covers exactly the same games.
    """
    df = read_query(cfg, _BUILDER_SQL.format(names=_sql_string_list(sorted(wonder_eras))))
    df = df.rename(
        columns={"GameId": "game_id", "Civ": "civ", "Building": "wonder", "Turn": "turn"}
    )

    games = _fully_logged_games(cfg, df)
    df = df[df["game_id"].isin(games)]

    df["era"] = df["wonder"].map(wonder_eras)
    df = df.dropna(subset=["era"])

    out = df[OUTPUT_COLUMNS_BUILDS].sort_values(["game_id", "civ", "turn"])
    out = out.reset_index(drop=True)
    out.attrs["games"] = games
    return out


def _build_game_civs(cfg: Config, games: set) -> pd.DataFrame:
    """Every (game, civ) that played a retained game, with the branches it opened.

    ``GameResult`` has one row per (game, civ) and is authoritative for who played
    what — a civ that built no wonders still needs a row, or it would vanish from
    the denominator. ``policy_choices.csv`` is joined onto that rather than the
    other way around: it carries one open row for a (game, civ) pair with no
    ``GameResult`` entry, which is dropped here rather than inventing a player.

    A branch open is a ``policy_choices`` row whose ``item`` is a branch name —
    ``build_policy_choices`` writes the branch there for the open row (the one
    with an empty ``Policy``), and no VP policy shares a name with a branch. This
    is the same rule :mod:`.policies_performance` uses, so the two reports agree
    on what "opened a branch" means. The open turn is deliberately ignored: a civ
    counts as having a branch for the whole game, so an early wonder still counts
    for a late-opened ideology.
    """
    pairs = read_table(cfg, "GameResult")[["GameId", "Civ"]].drop_duplicates()
    pairs = pairs[pairs["GameId"].isin(games)]
    pairs = pairs.rename(columns={"GameId": "game_id", "Civ": "civ"})

    choices = pd.read_csv(cfg.policy_choices_path)
    opens = choices[choices["item"].isin(BRANCH_SET)][["game_id", "civ", "item"]]
    opens = opens[opens["game_id"].isin(games)].drop_duplicates()
    # Branch order within the packed string follows BRANCH_ORDER, so the payload's
    # bitmask assignment is stable regardless of the order civs picked them.
    rank = {b: i for i, b in enumerate(BRANCH_ORDER)}
    opens = opens.sort_values("item", key=lambda s: s.map(rank))
    packed = opens.groupby(["game_id", "civ"])["item"].agg(BRANCH_SEP.join)

    out = pairs.merge(packed.rename("branches"), on=["game_id", "civ"], how="left")
    out["branches"] = out["branches"].fillna("")
    return out[OUTPUT_COLUMNS_GAME_CIVS].sort_values(["game_id", "civ"]).reset_index(drop=True)


def _build_summaries(cfg: Config) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Build the two wonders fact CSVs from one pass over the builder rows.

    ``__main__`` runs ``ensure_game_summaries`` first, so ``game_result.csv`` and
    ``policy_choices.csv`` exist and are fresh.
    """
    builds = _build_builds(cfg, load_wonder_eras())
    return builds, _build_game_civs(cfg, builds.attrs["games"])


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def ensure_wonders_summaries(cfg: Config, *, force: bool = False) -> None:
    """Generate the two wonders fact CSVs (built together, cached by mtime)."""
    ensure_group(
        cfg,
        [cfg.wonder_builds_path, cfg.wonder_game_civs_path],
        lambda: _build_summaries(cfg),
        force=force,
        # Bump whenever the wonder set or the builder rule changes: the CSVs are
        # newer than the DB, so mtime alone would keep serving the old numbers.
        fingerprint=f"wonders=v{WONDER_RULES_VERSION}",
    )

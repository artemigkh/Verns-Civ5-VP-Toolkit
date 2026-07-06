"""Religion Performance report summaries: attainment-time KDE + belief pick/win rates.

Three CSVs, built in one pass from the game-stats intermediates
(``religion_choices`` + ``game_result``, produced by :mod:`.game_summaries`):

* ``religion_attainment_kde``     — Gaussian-KDE density curves of the turn each
  religion milestone (pantheon / founded / enhanced / reformed) is attained.
* ``religion_attainment_moments`` — mean/median/sample-size per milestone (the
  vertical reference lines on the KDE plot).
* ``religion_pick_performance``   — per-(section, belief) pick count and how often
  the picking civ went on to win, split into the six report sections.

The win join is identical to :func:`.game_summaries.build_religion_stats`: a belief
pick counts as a win when the picking ``(game_id, civ)`` matches a game's winner.
Founder/enhancer vs follower beliefs are separated by *belief category*, inferred
from the set of ``type`` values a belief ever appears under (mirrors the R report's
``load_religion_data`` in ``analysis/r_scripts/common.R``).
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from scipy.stats import gaussian_kde

from ..config import Config
from .cache import ensure_group

# Attainment-time milestones, in display order. Maps the religion_choices ``type``
# value to the label the frontend keys off (and shows in the KDE legend).
ATTAINMENT_EVENTS = [
    ("pantheon", "Pantheon Founded"),
    ("religion_founded", "Religion Founded"),
    ("religion_enhanced", "Religion Enhanced"),
    ("religion_reformed", "Religion Reformed"),
]

# Number of points on the shared KDE x-grid (0 -> max attainment turn).
KDE_GRID_POINTS = 300

# Belief category from the frozenset of ``type`` values a belief appears under.
_CATEGORY_BY_TYPES = {
    frozenset({"pantheon"}): "PANTHEON",
    frozenset({"religion_reformed"}): "REFORMATION",
    frozenset({"religion_founded"}): "FOUNDER",
    frozenset({"religion_enhanced"}): "ENHANCER",
    frozenset({"religion_founded", "religion_enhanced"}): "FOLLOWER",
}

OUTPUT_COLUMNS_KDE = ["event_type", "x", "density"]
OUTPUT_COLUMNS_MOMENTS = ["event_type", "mean", "median", "n"]
OUTPUT_COLUMNS_PICK = ["section", "belief", "chosen_count", "wins", "losses", "avg_turn"]


def _attainment_samples(choices: pd.DataFrame) -> pd.DataFrame:
    """One turn per (game, civ, milestone): the turn that milestone was attained.

    A founding/enhancing emits two belief rows on the same turn; ``drop_duplicates``
    collapses them so each attainment is counted once.
    """
    return choices.drop_duplicates(["game_id", "civ", "type", "turn"])[["type", "turn"]]


def _build_attainment_kde(samples: pd.DataFrame) -> pd.DataFrame:
    """Gaussian-KDE density of attainment turns per milestone, on a shared x-grid."""
    max_turn = float(samples["turn"].max()) if not samples.empty else 0.0
    grid = np.linspace(0.0, max_turn, KDE_GRID_POINTS)

    frames: list[pd.DataFrame] = []
    for type_value, label in ATTAINMENT_EVENTS:
        turns = samples.loc[samples["type"] == type_value, "turn"].to_numpy(dtype=float)
        # gaussian_kde needs >=2 points and non-zero variance (singular otherwise).
        if turns.size < 2 or np.ptp(turns) == 0:
            continue
        density = gaussian_kde(turns)(grid)
        frames.append(
            pd.DataFrame({"event_type": label, "x": grid, "density": density})
        )

    if not frames:
        return pd.DataFrame(columns=OUTPUT_COLUMNS_KDE)
    out = pd.concat(frames, ignore_index=True)
    out["density"] = out["density"].round(8)
    out["x"] = out["x"].round(4)
    return out[OUTPUT_COLUMNS_KDE]


def _build_attainment_moments(samples: pd.DataFrame) -> pd.DataFrame:
    """Mean, median and sample size of attainment turns per milestone."""
    rows: list[dict] = []
    for type_value, label in ATTAINMENT_EVENTS:
        turns = samples.loc[samples["type"] == type_value, "turn"]
        if turns.empty:
            continue
        rows.append(
            {
                "event_type": label,
                "mean": round(float(turns.mean()), 4),
                "median": round(float(turns.median()), 4),
                "n": int(turns.size),
            }
        )
    return pd.DataFrame(rows, columns=OUTPUT_COLUMNS_MOMENTS)


def _belief_categories(choices: pd.DataFrame) -> pd.Series:
    """belief -> category, inferred from the set of ``type`` values it appears under."""
    type_sets = choices.groupby("belief")["type"].agg(lambda s: frozenset(s.unique()))
    return type_sets.map(lambda ts: _CATEGORY_BY_TYPES.get(ts, "OTHER"))


def _section_for(row_type: str, category: str) -> str | None:
    """Map a (choice type, belief category) pair to one of the six report sections."""
    if row_type == "pantheon":
        return "pantheon"
    if row_type == "religion_reformed":
        return "reformation"
    if row_type == "religion_founded":
        return "follower_found" if category == "FOLLOWER" else "founder"
    if row_type == "religion_enhanced":
        return "follower_enhance" if category == "FOLLOWER" else "enhancer"
    return None


def _build_pick_performance(
    choices: pd.DataFrame, game_result: pd.DataFrame
) -> pd.DataFrame:
    """Per-(section, belief) pick count, wins, losses and average pick turn."""
    winners = (
        game_result[["game_id", "victory_civ"]]
        .dropna(subset=["victory_civ"])
        .drop_duplicates()
        .assign(won=1)
    )
    merged = choices.merge(
        winners,
        left_on=["game_id", "civ"],
        right_on=["game_id", "victory_civ"],
        how="left",
    )
    merged["won"] = merged["won"].fillna(0).astype(int)

    category = _belief_categories(choices)
    merged["category"] = merged["belief"].map(category)
    merged["section"] = [
        _section_for(t, c) for t, c in zip(merged["type"], merged["category"], strict=True)
    ]
    merged = merged[merged["section"].notna()]

    out = merged.groupby(["section", "belief"], as_index=False).agg(
        chosen_count=("won", "size"),
        wins=("won", "sum"),
        avg_turn=("turn", "mean"),
    )
    out["losses"] = out["chosen_count"] - out["wins"]
    out["avg_turn"] = out["avg_turn"].round(4)
    out = out[OUTPUT_COLUMNS_PICK]
    # Sort each section by pick frequency (descending) so the frontend can render
    # bars in the order shown in the mockups without re-sorting.
    return out.sort_values(
        ["section", "chosen_count", "belief"], ascending=[True, False, True]
    ).reset_index(drop=True)


def _build_summaries(cfg: Config) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Build the three religion-performance CSVs from the game-stats intermediates.

    ``__main__`` runs ``ensure_game_summaries`` first, so these CSVs exist and are
    fresh; reading them keeps this aggregator decoupled from the raw DB tables.
    """
    choices = pd.read_csv(cfg.religion_choices_path)
    game_result = pd.read_csv(cfg.game_result_path)

    samples = _attainment_samples(choices)
    return (
        _build_attainment_kde(samples),
        _build_attainment_moments(samples),
        _build_pick_performance(choices, game_result),
    )


def ensure_religion_performance_summaries(cfg: Config, *, force: bool = False) -> None:
    """Generate the three religion-performance CSVs (built together, cached by mtime)."""
    ensure_group(
        cfg,
        [
            cfg.religion_attainment_kde_path,
            cfg.religion_attainment_moments_path,
            cfg.religion_pick_performance_path,
        ],
        lambda: _build_summaries(cfg),
        force=force,
    )

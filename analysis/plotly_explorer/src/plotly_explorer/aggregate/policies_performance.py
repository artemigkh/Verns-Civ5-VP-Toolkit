"""Policy-branch performance CSVs for the Policies Performance report.

Two CSVs are built from the game-stats intermediates (not the raw DB), mirroring
:mod:`.religion_performance`:

* ``policy_branch_opens``  — per-(civ, branch) count of branch opens.
* ``policy_branch_wins``   — per-(branch, victory_type) count of wins by a civ
  that had opened that branch.

A *branch open* is a ``policy_choices`` row whose ``item`` is one of the twelve
policy-branch names (``build_policy_choices`` stores the branch name as ``item``
for the empty-``Policy`` open row). A civ opens a given branch at most once per
game, so each open is one ``(game, civ, branch)`` unit. Opens are restricted to
the ``game_id``s present in ``game_result`` (real games, turn >= 100) so the
per-branch open totals line up with the win-rate denominators the report derives.
"""

from __future__ import annotations

import pandas as pd

from ..config import Config
from .cache import ensure_group

# Policy branches in their in-game tree order (the report's column/bar order).
BRANCH_ORDER = [
    "Tradition",
    "Progress",
    "Authority",
    "Fealty",
    "Statecraft",
    "Artistry",
    "Industry",
    "Imperialism",
    "Rationalism",
    "Freedom",
    "Order",
    "Autocracy",
]
BRANCH_SET = set(BRANCH_ORDER)

# Victory types shown in the report (matches civs.js VICTORY_COLORS). "Time"
# victories exist in the DB but are intentionally excluded, as in the mockup.
SHOWN_VICTORY_TYPES = ["Cultural", "Science", "Domination", "Diplomatic"]

OUTPUT_COLUMNS_OPENS = ["civ", "branch", "opens"]
OUTPUT_COLUMNS_WINS = ["branch", "victory_type", "wins"]


def _branch_opens(choices: pd.DataFrame, valid_games: set) -> pd.DataFrame:
    """Branch-open rows (game_id, civ, branch) restricted to real games."""
    opens = choices[choices["item"].isin(BRANCH_SET)][["game_id", "civ", "item"]]
    opens = opens.rename(columns={"item": "branch"})
    return opens[opens["game_id"].isin(valid_games)]


def _build_opens(opens: pd.DataFrame) -> pd.DataFrame:
    """Per-(civ, branch) open count."""
    if opens.empty:
        return pd.DataFrame(columns=OUTPUT_COLUMNS_OPENS)
    out = opens.groupby(["civ", "branch"]).size().reset_index(name="opens")
    return out[OUTPUT_COLUMNS_OPENS].sort_values(["civ", "branch"]).reset_index(drop=True)


def _build_wins(opens: pd.DataFrame, game_result: pd.DataFrame) -> pd.DataFrame:
    """Per-(branch, victory_type) count of opens whose civ won that game."""
    winners = (
        game_result[["game_id", "victory_civ", "victory_type"]]
        .dropna(subset=["victory_civ"])
        .drop_duplicates("game_id")
    )
    merged = opens.merge(
        winners,
        left_on=["game_id", "civ"],
        right_on=["game_id", "victory_civ"],
        how="left",
    )
    won = merged[merged["victory_type"].isin(SHOWN_VICTORY_TYPES)]
    if won.empty:
        return pd.DataFrame(columns=OUTPUT_COLUMNS_WINS)
    out = won.groupby(["branch", "victory_type"]).size().reset_index(name="wins")
    return out[OUTPUT_COLUMNS_WINS].sort_values(["branch", "victory_type"]).reset_index(drop=True)


def _build_summaries(cfg: Config) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Build the opens + wins CSVs from the game-stats intermediates."""
    choices = pd.read_csv(cfg.policy_choices_path)  # game_id, turn, civ, item, pick_order
    game_result = pd.read_csv(cfg.game_result_path)  # game_id, ..., victory_type, victory_civ

    valid_games = set(game_result["game_id"])
    opens = _branch_opens(choices, valid_games)
    return _build_opens(opens), _build_wins(opens, game_result)


def ensure_policies_performance_summaries(cfg: Config, *, force: bool = False) -> None:
    """Generate the two policy-branch CSVs, cached by mtime."""
    ensure_group(
        cfg,
        [cfg.policy_branch_opens_path, cfg.policy_branch_wins_path],
        lambda: _build_summaries(cfg),
        force=force,
    )

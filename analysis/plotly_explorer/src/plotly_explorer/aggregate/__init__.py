"""Intermediate aggregation step (decoupled from rendering and the web UI)."""

from .game_summaries import ensure_game_summaries
from .pipeline import ensure_summaries
from .policies_performance import ensure_policies_performance_summaries
from .religion import ensure_religion_summaries
from .religion_performance import ensure_religion_performance_summaries
from .units import ensure_unit_summaries

__all__ = [
    "ensure_summaries",
    "ensure_religion_summaries",
    "ensure_unit_summaries",
    "ensure_game_summaries",
    "ensure_religion_performance_summaries",
    "ensure_policies_performance_summaries",
]

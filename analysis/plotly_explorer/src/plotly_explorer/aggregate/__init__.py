"""Intermediate aggregation step (decoupled from rendering and the web UI)."""

from .pipeline import ensure_summaries
from .religion import ensure_religion_summaries
from .units import ensure_unit_summaries

__all__ = ["ensure_summaries", "ensure_religion_summaries", "ensure_unit_summaries"]

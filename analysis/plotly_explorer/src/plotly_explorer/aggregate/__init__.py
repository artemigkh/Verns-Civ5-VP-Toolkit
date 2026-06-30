"""Intermediate aggregation step (decoupled from rendering and the web UI)."""

from .pipeline import ensure_summaries
from .religion import ensure_religion_summaries

__all__ = ["ensure_summaries", "ensure_religion_summaries"]

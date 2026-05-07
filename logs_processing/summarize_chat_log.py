"""Summarize a VS Code chat trace log into a markdown table.

Usage:
    python summarize_chat_log.py <path-to-log.json>
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path


def parse_iso(ts: str) -> datetime:
    # Python's fromisoformat handles "...+00:00" but not the trailing "Z" pre-3.11
    if ts.endswith("Z"):
        ts = ts[:-1] + "+00:00"
    return datetime.fromisoformat(ts)


def format_duration(seconds: float) -> str:
    if seconds < 0:
        seconds = 0
    h, rem = divmod(int(seconds), 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h}h {m}m {s}s"
    if m:
        return f"{m}m {s}s"
    return f"{s}s"


def summarize(path: Path) -> str:
    data = json.loads(path.read_text(encoding="utf-8"))
    logs = data.get("logs", [])

    n_requests = 0
    n_tool_calls = 0
    input_tokens_total = 0       # prompt_tokens reported by API (includes cached)
    cached_tokens = 0
    output_tokens = 0

    times: list[datetime] = []

    for entry in logs:
        kind = entry.get("kind")
        if kind == "request":
            n_requests += 1
            md = entry.get("metadata") or {}
            usage = md.get("usage") or {}
            input_tokens_total += int(usage.get("prompt_tokens", 0) or 0)
            output_tokens += int(usage.get("completion_tokens", 0) or 0)
            details = usage.get("prompt_tokens_details") or {}
            cached_tokens += int(details.get("cached_tokens", 0) or 0)
            for key in ("startTime", "endTime"):
                ts = md.get(key)
                if ts:
                    try:
                        times.append(parse_iso(ts))
                    except ValueError:
                        pass
        elif kind == "toolCall":
            n_tool_calls += 1

        # Top-level "time" stamps appear on tool calls too — include them.
        ts = entry.get("time")
        if ts:
            try:
                times.append(parse_iso(ts))
            except ValueError:
                pass

    non_cached_input = input_tokens_total - cached_tokens

    if times:
        start = min(times)
        end = max(times)
        total_seconds = (end - start).total_seconds()
        duration_str = format_duration(total_seconds)
        span_str = f"{duration_str} ({start.astimezone(timezone.utc).isoformat()} -> {end.astimezone(timezone.utc).isoformat()})"
    else:
        span_str = "n/a"

    lines = [
        "| Metric | Value |",
        "| --- | ---: |",
        f"| Number of Requests | {n_requests:,} |",
        f"| Number of Tool calls | {n_tool_calls:,} |",
        f"| Total time from start to end | {span_str} |",
        f"| Input Tokens | {non_cached_input:,} |",
        f"| Input Tokens (Cached) | {cached_tokens:,} |",
        f"| Total Input Tokens | {input_tokens_total:,} |",
        f"| Output Tokens | {output_tokens:,} |",
    ]
    return "\n".join(lines)


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(__doc__, file=sys.stderr)
        return 2
    path = Path(argv[1])
    if not path.is_file():
        print(f"File not found: {path}", file=sys.stderr)
        return 1
    print(summarize(path))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))

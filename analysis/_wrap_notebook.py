"""One-shot transformer for Report.ipynb.

For every code cell:
  * Comment out SHAP-related lines (no `shap` package is required to run).
  * Replace the last top-level expression with `_maybe_display(<expr>)` so the
    notebook keeps its implicit "show last value" behaviour even after we
    wrap the cell in try/except.
  * Wrap the cell body in `try: ... except Exception: traceback.print_exc()`
    so that one failing cell never stops the whole report.

Idempotent: if a cell already starts with our sentinel header it is left
unchanged.
"""
from __future__ import annotations

import ast
import json
import re
from pathlib import Path

NB = Path(__file__).with_name("Report.ipynb")

SENTINEL = "# === auto-wrapped (safe-run) ==="

HELPER_HEADER = (
    f"{SENTINEL}\n"
    "try:\n"
    "    _maybe_display  # type: ignore[name-defined]\n"
    "except NameError:\n"
    "    def _maybe_display(_x):\n"
    "        if _x is None:\n"
    "            return _x\n"
    "        try:\n"
    "            from IPython.display import display as _d\n"
    "            _d(_x)\n"
    "        except Exception:\n"
    "            print(repr(_x))\n"
    "        return _x\n"
)

SHAP_RE = re.compile(
    r"\b(import\s+shap\b"
    r"|from\s+shap\b"
    r"|shap\."
    r"|xgb_shap_values\b"
    r"|explainer\s*=\s*shap\b)"
)


def comment_shap(src: str) -> str:
    """Comment out any logical line that touches SHAP, including multi-line
    function calls (we keep commenting until paren/bracket/brace depth is back
    to zero and the line doesn't end with a continuation)."""
    out = []
    in_shap = False
    depth = 0
    cont = False
    for line in src.splitlines():
        starts = SHAP_RE.search(line) and not line.lstrip().startswith("#")
        if not in_shap and starts:
            in_shap = True
            depth = 0
            cont = False
        if in_shap:
            indent = re.match(r"^(\s*)", line).group(1)
            out.append(f"{indent}# [SHAP-DISABLED] {line.lstrip()}")
            # update paren depth ignoring chars inside strings/comments (rough
            # but good enough for these cells).
            stripped = re.sub(r"#.*$", "", line)
            stripped = re.sub(r"'[^']*'|\"[^\"]*\"", "", stripped)
            for ch in stripped:
                if ch in "([{":
                    depth += 1
                elif ch in ")]}":
                    depth -= 1
            cont = stripped.rstrip().endswith("\\")
            if depth <= 0 and not cont:
                in_shap = False
                depth = 0
        else:
            out.append(line)
    return "\n".join(out)


def transform_last_expr(src: str) -> str:
    """If the last top-level node is an Expr, wrap it in `_maybe_display(...)`."""
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return src
    if not tree.body:
        return src
    last = tree.body[-1]
    if not isinstance(last, ast.Expr):
        return src
    # Skip if it's a docstring constant.
    if isinstance(last.value, ast.Constant) and isinstance(last.value.value, str):
        return src
    expr_src = ast.get_source_segment(src, last)
    if expr_src is None:
        return src
    # Skip if it already calls _maybe_display / display / print / plt.show etc.
    stripped = expr_src.lstrip()
    skip_prefixes = (
        "_maybe_display(",
        "display(",
        "print(",
        "plt.show(",
        "plt.close(",
        "plt.savefig(",
        "fig.show(",
    )
    if stripped.startswith(skip_prefixes):
        return src
    lines = src.splitlines()
    start = last.lineno - 1
    end = (last.end_lineno or last.lineno)
    indent = re.match(r"^(\s*)", lines[start]).group(1)
    # Reflow expr to a single (possibly long) line; safe because it's an Expr
    # and we add explicit parens via the call.
    flat = " ".join(part.strip() for part in expr_src.splitlines() if part.strip())
    new_lines = lines[:start] + [f"{indent}_maybe_display({flat})"] + lines[end:]
    return "\n".join(new_lines)


def wrap_cell(src: str, idx: int) -> str:
    if not src.strip():
        return src
    if src.lstrip().startswith(SENTINEL):
        return src  # already wrapped
    src1 = comment_shap(src)
    src2 = transform_last_expr(src1)
    indented = "\n".join(("    " + ln) if ln else "" for ln in src2.splitlines())
    body = (
        f"{HELPER_HEADER}"
        f"try:\n"
        f"{indented}\n"
        f"except Exception:\n"
        f"    print('[CELL ERROR] cell index {idx}')\n"
        f"    import traceback as _tb\n"
        f"    _tb.print_exc()\n"
    )
    return body


def main() -> None:
    nb = json.loads(NB.read_text(encoding="utf-8"))
    n_changed = 0
    for i, cell in enumerate(nb["cells"]):
        if cell.get("cell_type") != "code":
            continue
        src = cell["source"]
        if isinstance(src, list):
            src = "".join(src)
        new_src = wrap_cell(src, i)
        if new_src != src:
            n_changed += 1
        # Store as list of lines (with trailing newlines except last) to match nbformat.
        lines = new_src.splitlines(keepends=True)
        cell["source"] = lines
        cell["outputs"] = []
        cell["execution_count"] = None
    NB.write_text(json.dumps(nb, indent=1, ensure_ascii=False), encoding="utf-8")
    print(f"wrapped {n_changed} cells")


if __name__ == "__main__":
    main()

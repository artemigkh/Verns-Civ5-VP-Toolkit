"""Frontend asset invariants.

The explorer ships one concatenated <script>, so a single JS parse error
silently kills every report; and a module left out of render()'s bundle tuple
never registers with the router. Both are cheap to catch here.
"""

from __future__ import annotations

import inspect
import re
import shutil
import subprocess

import pytest

from plotly_explorer import render as R

ASSETS = R.ASSETS_DIR


def bundle_names() -> list[str]:
    """The js_bundle tuple inside render(), read from its source."""
    src = inspect.getsource(R.render)
    m = re.search(r"js_bundle = \((.*?)\)", src, re.S)
    assert m, "js_bundle tuple not found in render()"
    return re.findall(r'"([\w.]+\.js)"', m.group(1))


def test_bundle_starts_with_router_and_ends_with_switcher():
    names = bundle_names()
    assert names[0] == "router.js" and names[-1] == "switcher.js"
    assert len(names) == len(set(names))


def test_every_bundled_file_exists_and_every_module_is_bundled():
    names = bundle_names()
    for name in names:
        assert (ASSETS / name).is_file(), f"{name} is in js_bundle but not in assets/"
    on_disk = {p.name for p in ASSETS.glob("*.js")}
    # boot.js is appended outside __explorerMain by design.
    assert on_disk - set(names) == {"boot.js"}, "a JS module in assets/ is not in js_bundle"


def test_template_has_the_placeholders_render_fills():
    template = (ASSETS / "template.html").read_text(encoding="utf-8")
    for name in ("STYLES", "PLOTLYJS", "DATASETS", "DATA", "APPJS"):
        assert template.count(f"/*__{name}__*/") == 1, name
    assert 'id="payload-default"' in template  # boot.js reads the inlined payload from here
    assert 'id="report-select"' in template and 'id="dataset-select"' in template


def test_every_report_option_has_a_pane_and_a_show_rule():
    template = (ASSETS / "template.html").read_text(encoding="utf-8")
    styles = (ASSETS / "styles.css").read_text(encoding="utf-8")
    select = re.search(r'<select id="report-select">(.*?)</select>', template, re.S).group(1)
    keys = re.findall(r'<option value="(\w+)"', select)
    assert len(keys) >= 10
    for key in keys:
        assert f'class="report-{key}"' in template, f"no .report-{key} pane in template.html"
        assert f"#app.show-{key} " in styles, f"no show-{key} rule in styles.css"


def test_static_dev_payloads_parse_and_drop_comments():
    for build in (R.build_process_memory_payload, R.build_draw_list_buffer_payload):
        out = build()
        assert out and not any(k.startswith("_") for k in out)


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not on PATH")
@pytest.mark.parametrize("name", sorted(p.name for p in ASSETS.glob("*.js")))
def test_asset_js_parses(name):
    proc = subprocess.run(["node", "--check", str(ASSETS / name)], capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr

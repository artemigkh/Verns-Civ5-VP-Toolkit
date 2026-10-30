"""render(): the inlined index.html, the per-dataset sidecars, and stale-sidecar cleanup.

The payload builders and Plotly are stubbed; the real template, styles and JS
bundle are used, so this also proves the bundle assembles.
"""

from __future__ import annotations

import dataclasses
import json
import re

import pytest

from plotly_explorer import render as R
from plotly_explorer.datasets import Dataset

DESC = dict(patch="5.4.8", difficulty="Emperor", mapscript="Communitu 3.2.0", size="Standard")


@pytest.fixture
def rendered(cfg, tmp_path, monkeypatch):
    def fake_payload(ds: Dataset) -> dict:
        return {
            "defaultReport": "civs",
            "dataset": ds.id,
            "unavailable": {},
            "civs": {"kpis": {"patch": ds.patch, "games": 3}, "note": "</script>"},
        }

    monkeypatch.setattr(R, "build_payload", fake_payload)
    monkeypatch.setattr(R.po, "get_plotlyjs", lambda: "/* plotly stub */")

    other_cfg = dataclasses.replace(cfg, db_path=tmp_path / "other.db")
    datasets = [
        Dataset(id="main", label="Main", cfg=cfg, is_default=True, **DESC),
        Dataset(id="old_run", label="Old run", cfg=other_cfg, **DESC),
    ]
    sidecars = cfg.publish_dir / R.DATASETS_SUBDIR
    sidecars.mkdir(parents=True)
    (sidecars / "dropped.js").write_text("stale", encoding="utf-8")

    out = R.render(cfg, datasets)
    return out, out.read_text(encoding="utf-8"), sidecars


def test_index_html_has_every_placeholder_filled(rendered):
    path, html, _ = rendered
    assert path.name == "index.html"
    assert "/*__" not in html
    assert "/* plotly stub */" in html
    assert "window.__explorerMain = function ()" in html
    # The CSS and the template's own markup are present.
    assert '<select id="report-select">' in html
    assert "--bg: #0e1117" in html


def test_index_html_inlines_the_default_dataset_safely(rendered):
    _, html, _ = rendered
    m = re.search(r'<script type="application/json" id="payload-default">\n(.*?)\n</script>', html, re.S)
    assert m, "the default payload JSON block is missing"
    payload = json.loads(m.group(1))
    assert payload["dataset"] == "main"
    assert payload["civs"]["note"] == "</script>"  # round-trips through the <\/ escape
    assert "</script><" not in m.group(1)


def test_manifest_lists_every_dataset_in_order(rendered):
    _, html, _ = rendered
    m = re.search(r"window\.EXPLORER_DATASETS = (\{.*?\});", html)
    manifest = json.loads(m.group(1))
    assert manifest == {
        "default": "main",
        "dir": "datasets",
        "list": [{"id": "main", "label": "Main"}, {"id": "old_run", "label": "Old run"}],
    }


def test_sidecars_written_and_stale_ones_removed(rendered):
    _, _, sidecars = rendered
    names = sorted(p.name for p in sidecars.glob("*.js"))
    assert "dropped.js" not in names
    assert "old_run.js" in names and "main.js" not in names  # the default is inlined, not a sidecar
    full = (sidecars / "old_run.js").read_text(encoding="utf-8")
    assert full.startswith("window.PAYLOAD = {") and full.rstrip().endswith("};")
    assert json.loads(full[len("window.PAYLOAD = ") : full.rindex(";")])["dataset"] == "old_run"


def test_every_dataset_gets_an_overview_slice(rendered):
    _, _, sidecars = rendered
    for ds_id in ("main", "old_run"):
        text = (sidecars / f"{ds_id}.civs.js").read_text(encoding="utf-8")
        assert text.startswith("window.EXPLORER_CIVS_SLICES = window.EXPLORER_CIVS_SLICES || {};")
        m = re.search(r'window\.EXPLORER_CIVS_SLICES\["(\w+)"\] = (\{.*\});', text)
        assert m.group(1) == ds_id
        assert json.loads(m.group(2))["kpis"]["games"] == 3


def test_build_payload_marks_unavailable_reports_as_null(cfg, monkeypatch):
    monkeypatch.setattr(R, "build_civs_payload", lambda *a: {"ok": True})
    monkeypatch.setattr(R, "build_building_payload", lambda cfg: {"ok": True})
    for name in (
        "build_religion_payload",
        "build_units_payload",
        "build_policies_performance_payload",
        "build_instant_yields_payload",
        "build_wonders_payload",
    ):
        monkeypatch.setattr(R, name, lambda cfg: {"ok": True})
    monkeypatch.setattr(R, "build_religion_performance_payload", lambda *a: {"ok": True})
    monkeypatch.setattr(R, "build_leaders_payload", lambda: {"static": True})
    ds = Dataset(id="d", label="d", cfg=cfg, is_default=True, **DESC)
    monkeypatch.setattr(Dataset, "unavailable_reports", lambda self: {"instant_yields": "too old"})

    out = R.build_payload(ds)
    assert out["dataset"] == "d" and out["defaultReport"] == "civs"
    assert out["unavailable"] == {"instant_yields": "too old"}
    assert out["instant_yields"] is None
    assert out["civs"] == {"ok": True} and out["leaders"] == {"static": True}
    # The two static dev reports ship with every dataset.
    assert "_comment" not in out["process_memory"] and "_comment" not in out["draw_list_buffer"]

"""Tests for the pure helper functions in autoplay.runner.game_controller.

Focuses on:
* ``_make_tar_gz`` (per-file gzip inside an uncompressed tar)
* ``_snapshot_csv_segment`` (segment numbering + skip on no CSVs)
* ``_consolidate_csv_segments`` (header-stripping + raw concat)
* ``_make_game_id`` (ISO-with-dots format)
* ``_kill_process_tree`` happy + missing-pid paths
* ``_clear_logs_dir`` / ``_clear_segments_root``
* ``_should_include`` ignore-pattern matching
"""

from __future__ import annotations

import gzip
import io
import re
import tarfile
from pathlib import Path

import pytest

from autoplay.runner import game_controller as gc


# --------------------------------------------------------------------------
# _make_game_id
# --------------------------------------------------------------------------


class TestMakeGameId:
    def test_sortable_iso_with_dots(self) -> None:
        gid = gc._make_game_id()
        # No colons (replaced with dots).
        assert ":" not in gid
        # Roughly ISO-shaped: YYYY-MM-DDTHH.MM.SS(.ffffff)
        assert re.match(r"^\d{4}-\d{2}-\d{2}T\d{2}\.\d{2}\.\d{2}", gid)


# --------------------------------------------------------------------------
# _should_include / ignore patterns
# --------------------------------------------------------------------------


class TestShouldInclude:
    @pytest.mark.parametrize("name", ["foo.csv", "WorldState_Log.csv"])
    def test_includes_normal_files(self, name: str) -> None:
        assert gc._should_include(Path(name), ["CitySites_*", "TradePlayerRouteLog_*"])

    @pytest.mark.parametrize("name", ["CitySites_001.csv", "TradePlayerRouteLog_x.csv"])
    def test_excludes_matching_patterns(self, name: str) -> None:
        assert not gc._should_include(
            Path(name), ["CitySites_*", "TradePlayerRouteLog_*"]
        )


# --------------------------------------------------------------------------
# _make_tar_gz
# --------------------------------------------------------------------------


class TestMakeTarGz:
    def test_each_file_is_individually_gzipped(self, tmp_path: Path) -> None:
        logs = tmp_path / "Logs"
        logs.mkdir()
        (logs / "a.csv").write_bytes(b"hello,a\n1,2\n")
        (logs / "b.csv").write_bytes(b"hello,b\n3,4\n")

        bundle = gc._make_tar_gz(logs, ignore_patterns=[])
        # The outer tar must be uncompressed (mode=w).
        with tarfile.open(fileobj=io.BytesIO(bundle), mode="r") as tar:
            names = sorted(m.name for m in tar.getmembers())
            assert names == ["a.csv.gz", "b.csv.gz"]
            # Each member is gzipped individually.
            ma = tar.extractfile("a.csv.gz")
            assert ma is not None
            assert gzip.decompress(ma.read()) == b"hello,a\n1,2\n"
            mb = tar.extractfile("b.csv.gz")
            assert mb is not None
            assert gzip.decompress(mb.read()) == b"hello,b\n3,4\n"

    def test_honors_ignore_patterns(self, tmp_path: Path) -> None:
        logs = tmp_path / "Logs"
        logs.mkdir()
        (logs / "WorldState_Log.csv").write_bytes(b"x")
        (logs / "CitySites_1.csv").write_bytes(b"x")
        (logs / "TradePlayerRouteLog_1.csv").write_bytes(b"x")
        bundle = gc._make_tar_gz(
            logs, ignore_patterns=["CitySites_*", "TradePlayerRouteLog_*"]
        )
        with tarfile.open(fileobj=io.BytesIO(bundle), mode="r") as tar:
            assert sorted(m.name for m in tar.getmembers()) == ["WorldState_Log.csv.gz"]

    def test_empty_logs_dir_yields_empty_tar(self, tmp_path: Path) -> None:
        logs = tmp_path / "Logs"
        logs.mkdir()
        bundle = gc._make_tar_gz(logs, ignore_patterns=[])
        with tarfile.open(fileobj=io.BytesIO(bundle), mode="r") as tar:
            assert tar.getmembers() == []

    def test_missing_logs_dir_yields_empty_tar(self, tmp_path: Path) -> None:
        bundle = gc._make_tar_gz(tmp_path / "missing", ignore_patterns=[])
        with tarfile.open(fileobj=io.BytesIO(bundle), mode="r") as tar:
            assert tar.getmembers() == []

    def test_skips_subdirectories(self, tmp_path: Path) -> None:
        logs = tmp_path / "Logs"
        logs.mkdir()
        (logs / "a.csv").write_bytes(b"a")
        (logs / "subdir").mkdir()
        bundle = gc._make_tar_gz(logs, ignore_patterns=[])
        with tarfile.open(fileobj=io.BytesIO(bundle), mode="r") as tar:
            names = [m.name for m in tar.getmembers()]
            assert names == ["a.csv.gz"]


# --------------------------------------------------------------------------
# _snapshot_csv_segment
# --------------------------------------------------------------------------


class TestSnapshotCsvSegment:
    def test_no_logs_dir_returns_none(self, tmp_path: Path) -> None:
        result = gc._snapshot_csv_segment(
            tmp_path / "missing", "g1", tmp_path, label="x"
        )
        assert result is None

    def test_no_csvs_returns_none(self, tmp_path: Path) -> None:
        logs = tmp_path / "Logs"
        logs.mkdir()
        (logs / "not_a_csv.txt").write_text("x")
        result = gc._snapshot_csv_segment(logs, "g1", tmp_path, label="x")
        assert result is None
        # No segment dir should be left behind.
        assert not (tmp_path / "AutoplayLogSegments" / "g1").exists()

    def test_creates_seg_000_first(self, tmp_path: Path) -> None:
        logs = tmp_path / "Logs"
        logs.mkdir()
        (logs / "WorldState_Log.csv").write_bytes(b"Turn,X\n1,a\n")
        (logs / "Score_Log.csv").write_bytes(b"hdr\n1\n")
        seg = gc._snapshot_csv_segment(logs, "g1", tmp_path, label="x")
        assert seg is not None
        assert seg.name == "seg_000"
        assert (seg / "WorldState_Log.csv").read_bytes() == b"Turn,X\n1,a\n"
        assert (seg / "Score_Log.csv").read_bytes() == b"hdr\n1\n"

    def test_increments_segment_number(self, tmp_path: Path) -> None:
        logs = tmp_path / "Logs"
        logs.mkdir()
        (logs / "a.csv").write_bytes(b"x")
        s0 = gc._snapshot_csv_segment(logs, "g1", tmp_path, label="x")
        s1 = gc._snapshot_csv_segment(logs, "g1", tmp_path, label="x")
        s2 = gc._snapshot_csv_segment(logs, "g1", tmp_path, label="x")
        assert s0 is not None and s0.name == "seg_000"
        assert s1 is not None and s1.name == "seg_001"
        assert s2 is not None and s2.name == "seg_002"


# --------------------------------------------------------------------------
# _consolidate_csv_segments — the most important concat logic
# --------------------------------------------------------------------------


class TestConsolidateCsvSegments:
    def test_no_segments_returns_zero(self, tmp_path: Path) -> None:
        logs = tmp_path / "Logs"
        logs.mkdir()
        (logs / "WorldState_Log.csv").write_bytes(b"x")
        n = gc._consolidate_csv_segments(logs, "g1", tmp_path)
        assert n == 0

    def test_single_segment_strips_no_header(self, tmp_path: Path) -> None:
        """For a non-headered CSV: raw bytes from segment + current concatenated."""
        logs = tmp_path / "Logs"
        logs.mkdir()
        # Snapshot first.
        (logs / "Foo.csv").write_bytes(b"line1\nline2\n")
        gc._snapshot_csv_segment(logs, "g1", tmp_path, label="x")
        # Now current logs has more data.
        (logs / "Foo.csv").write_bytes(b"line3\nline4\n")

        n = gc._consolidate_csv_segments(logs, "g1", tmp_path)
        assert n == 1
        # No header stripping for non-headered CSVs.
        result = (logs / "Foo.csv").read_bytes()
        assert result == b"line1\nline2\nline3\nline4\n"

    def test_headered_csv_strips_subsequent_headers(self, tmp_path: Path) -> None:
        logs = tmp_path / "Logs"
        logs.mkdir()
        # Segment 0
        (logs / "WorldState_Log.csv").write_bytes(
            b"Turn,Player,Score\n1,A,10\n2,A,20\n"
        )
        gc._snapshot_csv_segment(logs, "g1", tmp_path, label="x")
        # Segment 1
        (logs / "WorldState_Log.csv").write_bytes(
            b"Turn,Player,Score\n3,A,30\n4,A,40\n"
        )
        gc._snapshot_csv_segment(logs, "g1", tmp_path, label="x")
        # Current
        (logs / "WorldState_Log.csv").write_bytes(
            b"Turn,Player,Score\n5,A,50\n"
        )

        n = gc._consolidate_csv_segments(logs, "g1", tmp_path)
        assert n == 1
        result = (logs / "WorldState_Log.csv").read_bytes()
        # Header from seg_000 only; subsequent segments lose their header.
        assert result == (
            b"Turn,Player,Score\n"
            b"1,A,10\n"
            b"2,A,20\n"
            b"3,A,30\n"
            b"4,A,40\n"
            b"5,A,50\n"
        )

    def test_only_current_present_skips(self, tmp_path: Path) -> None:
        logs = tmp_path / "Logs"
        logs.mkdir()
        (logs / "WorldState_Log.csv").write_bytes(b"Turn,X\n1,a\n")
        # Create empty segment root.
        (tmp_path / "AutoplayLogSegments" / "g1" / "seg_000").mkdir(parents=True)
        # Segment dir has no copy of WorldState_Log.csv.
        before = (logs / "WorldState_Log.csv").read_bytes()
        gc._consolidate_csv_segments(logs, "g1", tmp_path)
        # Current file untouched (only one source).
        assert (logs / "WorldState_Log.csv").read_bytes() == before

    def test_handles_missing_intermediate_file(self, tmp_path: Path) -> None:
        """Segment dir present but missing the file -> still consolidates others."""
        logs = tmp_path / "Logs"
        logs.mkdir()
        (logs / "Foo.csv").write_bytes(b"a\n")
        gc._snapshot_csv_segment(logs, "g1", tmp_path, label="x")  # seg_000
        (logs / "Foo.csv").write_bytes(b"b\n")
        gc._snapshot_csv_segment(logs, "g1", tmp_path, label="x")  # seg_001
        # Delete Foo.csv from seg_001 to simulate a copy failure.
        (tmp_path / "AutoplayLogSegments" / "g1" / "seg_001" / "Foo.csv").unlink()
        (logs / "Foo.csv").write_bytes(b"c\n")

        gc._consolidate_csv_segments(logs, "g1", tmp_path)
        # seg_000 + current
        assert (logs / "Foo.csv").read_bytes() == b"a\nc\n"

    def test_appends_newline_between_segments_if_missing(
        self, tmp_path: Path
    ) -> None:
        logs = tmp_path / "Logs"
        logs.mkdir()
        (logs / "Foo.csv").write_bytes(b"line1")  # no trailing \n
        gc._snapshot_csv_segment(logs, "g1", tmp_path, label="x")
        (logs / "Foo.csv").write_bytes(b"line2")
        gc._consolidate_csv_segments(logs, "g1", tmp_path)
        # seg_000 had no newline; one is inserted between segments.
        result = (logs / "Foo.csv").read_bytes()
        assert result == b"line1\nline2"

    def test_multiple_csv_types_mixed(self, tmp_path: Path) -> None:
        logs = tmp_path / "Logs"
        logs.mkdir()
        (logs / "WorldState_Log.csv").write_bytes(b"Turn,X\n1,a\n")
        (logs / "OtherLog.csv").write_bytes(b"raw1\n")
        gc._snapshot_csv_segment(logs, "g1", tmp_path, label="x")
        (logs / "WorldState_Log.csv").write_bytes(b"Turn,X\n2,b\n")
        (logs / "OtherLog.csv").write_bytes(b"raw2\n")
        gc._consolidate_csv_segments(logs, "g1", tmp_path)
        assert (logs / "WorldState_Log.csv").read_bytes() == b"Turn,X\n1,a\n2,b\n"
        assert (logs / "OtherLog.csv").read_bytes() == b"raw1\nraw2\n"


# --------------------------------------------------------------------------
# _kill_process_tree
# --------------------------------------------------------------------------


class TestKillProcessTree:
    def test_terminates_process_and_children(self, mock_psutil) -> None:
        gc._kill_process_tree(1234)
        mock_psutil.Process.assert_called_once_with(1234)
        # The fake parent's terminate should be called.
        parent = mock_psutil.Process.return_value
        assert parent.terminate.called

    def test_no_such_process_is_silent(self, monkeypatch) -> None:
        from unittest.mock import MagicMock

        fake_psutil = MagicMock()
        fake_psutil.NoSuchProcess = type("NoSuchProcess", (Exception,), {})
        fake_psutil.Process = MagicMock(side_effect=fake_psutil.NoSuchProcess())
        monkeypatch.setattr(gc, "psutil", fake_psutil)
        # Must not raise.
        gc._kill_process_tree(9999)


# --------------------------------------------------------------------------
# _clear_logs_dir / _clear_segments_root
# --------------------------------------------------------------------------


class TestClearLogsDir:
    def test_removes_all_children(self, tmp_path: Path) -> None:
        logs = tmp_path / "Logs"
        logs.mkdir()
        (logs / "a.csv").write_text("x")
        (logs / "sub").mkdir()
        (logs / "sub" / "b.csv").write_text("y")
        gc._clear_logs_dir(logs)
        assert logs.is_dir()
        assert list(logs.iterdir()) == []

    def test_creates_dir_if_missing(self, tmp_path: Path) -> None:
        target = tmp_path / "no_such_logs"
        gc._clear_logs_dir(target)
        assert target.is_dir()


class TestClearSegmentsRoot:
    def test_removes_root(self, tmp_path: Path) -> None:
        root = tmp_path / "AutoplayLogSegments"
        (root / "g1" / "seg_000").mkdir(parents=True)
        (root / "g1" / "seg_000" / "x.csv").write_text("y")
        gc._clear_segments_root(tmp_path)
        assert not root.exists()

    def test_idempotent_when_missing(self, tmp_path: Path) -> None:
        # Should not raise even if AutoplayLogSegments doesn't exist.
        gc._clear_segments_root(tmp_path)

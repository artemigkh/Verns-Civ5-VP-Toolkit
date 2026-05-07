"""Tests for autoplay.common.constants."""

from __future__ import annotations

import pytest

from autoplay.common.constants import MODPACK_FOLDER_PREFIX, MODPACK_FOLDER_REGEX


class TestModpackFolderRegex:
    @pytest.mark.parametrize(
        "name,expected_version",
        [
            ("MP_AUTOPLAY_VP_5_2_3", "5_2_3"),
            ("MP_AUTOPLAY_VP_10_0_0", "10_0_0"),
            ("MP_AUTOPLAY_VP_v1", "v1"),
            ("MP_AUTOPLAY_VP_5.2.3", "5.2.3"),
        ],
    )
    def test_matches_valid_names(self, name: str, expected_version: str) -> None:
        m = MODPACK_FOLDER_REGEX.match(name)
        assert m is not None
        assert m.group("version") == expected_version

    @pytest.mark.parametrize(
        "name",
        [
            "",
            "MP_AUTOPLAY_VP_",  # empty version
            "AUTOPLAY_VP_5_2_3",  # missing prefix
            "mp_autoplay_vp_5_2_3",  # case-sensitive
            "prefix_MP_AUTOPLAY_VP_5_2_3",  # not at start
        ],
    )
    def test_rejects_invalid(self, name: str) -> None:
        assert MODPACK_FOLDER_REGEX.match(name) is None

    def test_prefix_constant_is_consistent(self) -> None:
        assert MODPACK_FOLDER_PREFIX == "MP_AUTOPLAY_VP_"
        # The regex should match the prefix + arbitrary version.
        assert MODPACK_FOLDER_REGEX.match(MODPACK_FOLDER_PREFIX + "x") is not None

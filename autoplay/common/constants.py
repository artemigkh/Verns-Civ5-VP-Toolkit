"""Constants shared by the hypervisor and runner."""

from __future__ import annotations

import re

MODPACK_FOLDER_PREFIX = "MP_AUTOPLAY_VP_"
"""Folder name prefix used for autoplay modpack folders in the DLC directory."""

MODPACK_FOLDER_REGEX = re.compile(rf"^{re.escape(MODPACK_FOLDER_PREFIX)}(?P<version>.+)$")
"""Regex that matches a modpack folder name and captures its version string."""

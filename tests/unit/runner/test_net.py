"""Tests for autoplay.runner.net.detect_lan_host (ipconfig parsing)."""

from __future__ import annotations

import subprocess

import pytest

from autoplay.runner import net


_IPCONFIG_TARGET_GW = """
Windows IP Configuration

Ethernet adapter Ethernet:

   Connection-specific DNS Suffix  . :
   IPv4 Address. . . . . . . . . . . : 192.168.2.42
   Subnet Mask . . . . . . . . . . . : 255.255.255.0
   Default Gateway . . . . . . . . . : 192.168.2.1
"""

_IPCONFIG_OTHER_GW_THEN_PREFIX = """
Windows IP Configuration

Wireless LAN adapter Wi-Fi:
   IPv4 Address. . . . . . . . . . . : 10.0.0.5
   Default Gateway . . . . . . . . . : 10.0.0.1

Ethernet adapter Ethernet:
   IPv4 Address. . . . . . . . . . . : 192.168.2.99
   Default Gateway . . . . . . . . . : 192.168.99.1
"""

_IPCONFIG_NO_MATCH = """
Wireless LAN adapter Wi-Fi:
   IPv4 Address. . . . . . . . . . . : 10.0.0.5
   Default Gateway . . . . . . . . . : 10.0.0.1
"""

_IPCONFIG_MULTIPLE_TARGET = """
Ethernet adapter A:
   IPv4 Address. . . . . . . . . . . : 192.168.2.5
   Default Gateway . . . . . . . . . : 192.168.99.1

Ethernet adapter B:
   IPv4 Address. . . . . . . . . . . : 192.168.2.42
   Default Gateway . . . . . . . . . : 192.168.2.1

Ethernet adapter C:
   IPv4 Address. . . . . . . . . . . : 192.168.2.99
   Default Gateway . . . . . . . . . : 192.168.2.1
"""


def _patch_ipconfig(monkeypatch, output: str) -> None:
    def _fake_check_output(cmd, **kwargs):  # noqa: ARG001
        return output

    monkeypatch.setattr(subprocess, "check_output", _fake_check_output)


def test_picks_adapter_with_target_gateway(monkeypatch) -> None:
    _patch_ipconfig(monkeypatch, _IPCONFIG_TARGET_GW)
    assert net.detect_lan_host() == "192.168.2.42"


def test_falls_back_to_prefix_when_no_target_gateway(monkeypatch) -> None:
    _patch_ipconfig(monkeypatch, _IPCONFIG_OTHER_GW_THEN_PREFIX)
    assert net.detect_lan_host() == "192.168.2.99"


def test_returns_localhost_when_nothing_matches(monkeypatch) -> None:
    _patch_ipconfig(monkeypatch, _IPCONFIG_NO_MATCH)
    assert net.detect_lan_host() == "localhost"


def test_returns_localhost_on_subprocess_error(monkeypatch) -> None:
    def _fake(cmd, **kwargs):  # noqa: ARG001
        raise OSError("ipconfig not found")

    monkeypatch.setattr(subprocess, "check_output", _fake)
    assert net.detect_lan_host() == "localhost"


def test_picks_first_target_gateway_match_when_multiple(monkeypatch) -> None:
    _patch_ipconfig(monkeypatch, _IPCONFIG_MULTIPLE_TARGET)
    # Either 192.168.2.42 or 192.168.2.99 are acceptable; first wins.
    assert net.detect_lan_host() == "192.168.2.42"


def test_empty_ipconfig_output(monkeypatch) -> None:
    _patch_ipconfig(monkeypatch, "")
    assert net.detect_lan_host() == "localhost"

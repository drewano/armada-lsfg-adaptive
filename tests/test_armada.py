import lsfg.armada as armada_mod
from lsfg.armada import (
    _parse_env_output,
    default_target_fps,
    host_arch,
    parse_refresh_rates,
)


def test_host_arch_prefers_filesystem_probe(monkeypatch):
    # FEX emulation case: python reports x86_64 but the system is aarch64
    monkeypatch.setattr(armada_mod.platform, "machine", lambda: "x86_64")
    monkeypatch.setattr(
        armada_mod.os.path, "exists",
        lambda p: p == "/lib/ld-linux-aarch64.so.1",
    )
    assert host_arch() == "aarch64"


def test_host_arch_x86_when_only_x86_loader(monkeypatch):
    monkeypatch.setattr(armada_mod.platform, "machine", lambda: "x86_64")
    monkeypatch.setattr(
        armada_mod.os.path, "exists",
        lambda p: p == "/lib/ld-linux-x86-64.so.2",
    )
    assert host_arch() == "x86_64"


def test_host_arch_falls_back_to_platform(monkeypatch):
    monkeypatch.setattr(armada_mod.os.path, "exists", lambda p: False)
    monkeypatch.setattr(armada_mod.platform, "machine", lambda: "aarch64")
    assert host_arch() == "aarch64"


def test_parse_env_output():
    env = _parse_env_output(
        "PATH=/usr/bin\n"
        'ARMADA_PANEL_REFRESH_RATES="60,90,120"\n'
        "ARMADA_DEVICE_NAME=Odin 2\n"
        "ARMADA_PANEL_REFRESH_RATES=ignored-duplicate\n"
    )
    assert env["ARMADA_PANEL_REFRESH_RATES"] == "60,90,120"
    assert env["ARMADA_DEVICE_NAME"] == "Odin 2"
    assert "PATH" not in env


def test_parse_refresh_rates_formats():
    assert parse_refresh_rates("60,90,120") == [60, 90, 120]
    assert parse_refresh_rates("60.00 120.00") == [60, 120]
    assert parse_refresh_rates("120") == [120]
    assert parse_refresh_rates("") == []
    assert parse_refresh_rates(None) == []
    assert parse_refresh_rates("junk, 60, 9999") == [60]


def test_default_target_fps():
    assert default_target_fps(120) == 120
    assert default_target_fps(144) == 120
    assert default_target_fps(90) == 90
    assert default_target_fps(60) == 60
    assert default_target_fps(None) == 60

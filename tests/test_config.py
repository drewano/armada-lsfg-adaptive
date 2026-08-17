import tomllib

from lsfg.config import (
    ConfigError,
    ProfileData,
    load_config,
    profile_from_block,
    read_profiles,
    render_profile,
    set_global_dll,
    split_config,
    write_config,
)


def make_profile(**kwargs):
    base = dict(key="game.exe", name="Game", active_in=["Game.exe"],
                target_fps=120, max_multiplier=3)
    base.update(kwargs)
    return ProfileData(**base)


def test_render_profile_adaptive():
    text = render_profile(make_profile())
    doc = tomllib.loads(text)
    p = doc["profile"][0]
    assert p["adaptive"] is True
    assert p["target_fps"] == 120
    assert p["adaptive_max_multiplier"] == 3
    assert p["frame_generation_enabled"] is True
    assert p["flow_scale"] == 0.5
    assert "multiplier" not in p


def test_render_profile_fixed_multiplier():
    text = render_profile(make_profile(adaptive=False))
    p = tomllib.loads(text)["profile"][0]
    assert p["adaptive"] is False
    assert p["multiplier"] == 2
    assert "target_fps" not in p


def test_flow_scale_rendered_as_float():
    p = make_profile(flow_scale=1.0)
    assert "flow_scale = 1.00" in render_profile(p)


def test_validate_rejects_bad_multiplier():
    try:
        make_profile(max_multiplier=5).validate()
        assert False, "should raise"
    except ConfigError:
        pass


def test_validate_rejects_bad_target_fps():
    try:
        make_profile(target_fps=300).validate()
        assert False, "should raise"
    except ConfigError:
        pass


def test_split_config_keeps_commented_blocks():
    text = (
        '[global]\ndll = "/old/path.dll"\n\n'
        "# [[profile]]\n# commented out\n\n"
        '[[profile]]\nname = "X"\nactive_in = ["X.exe"]\n'
    )
    global_text, blocks = split_config(text)
    assert global_text.startswith("[global]")
    assert len(blocks) == 1
    assert 'name = "X"' in blocks[0]


def test_set_global_dll_replaces_existing():
    text = '[global]\ndll = "/old/path.dll"\nother = 1\n'
    out = set_global_dll(text, "/new/path.dll")
    assert 'dll = "/new/path.dll"' in out
    assert "other = 1" in out
    assert "/old/path" not in out


def test_set_global_dll_appends_when_missing():
    text = "[global]\nother = 1\n"
    out = set_global_dll(text, "/p.dll")
    assert out.rstrip().endswith('dll = "/p.dll"')
    assert "other = 1" in out


def test_write_and_read_roundtrip(tmp_path):
    conf = tmp_path / "conf.toml"
    profiles = [make_profile(), make_profile(key="other.exe", name="Other",
                                              active_in=["Other.exe"], adaptive=False)]
    write_config(conf, profiles, dll_path="/steam/Lossless.dll")
    doc = load_config(conf)
    assert doc["global"]["dll"] == "/steam/Lossless.dll"
    names = {p["name"] for p in doc["profile"]}
    assert names == {"Game", "Other"}
    back = read_profiles(conf)
    by_key = {p.key: p for p in back}
    assert by_key["game.exe"].adaptive is True
    assert by_key["other.exe"].adaptive is False


def test_write_preserves_foreign_blocks(tmp_path):
    conf = tmp_path / "conf.toml"
    conf.write_text(
        '[global]\nfoo = "bar"\n\n'
        "[[profile]]\n"
        'name = "Foreign Tool Profile"\n'
        'active_in = ["foreign.exe"]\n'
        "multiplier = 3\n"
        "weird_custom_key = [1, 2]\n",
        encoding="utf-8",
    )
    foreign_keys = write_config(conf, [make_profile()], dll_path="/d.dll")
    text = conf.read_text(encoding="utf-8")
    assert foreign_keys == ["foreign.exe"]
    assert "Foreign Tool Profile" in text
    assert "weird_custom_key" in text
    assert 'foo = "bar"' in text
    doc = load_config(conf)
    assert len(doc["profile"]) == 2


def test_unparseable_block_quarantined(tmp_path):
    conf = tmp_path / "conf.toml"
    conf.write_text(
        "[[profile]]\nname = broken this is not toml\n",
        encoding="utf-8",
    )
    write_config(conf, [make_profile()])
    text = conf.read_text(encoding="utf-8")
    assert "name = broken this is not toml" not in text
    rejected = (tmp_path / "conf.toml.armada-lsfg-adaptive.rejected").read_text(encoding="utf-8")
    assert "name = broken this is not toml" in rejected


def test_disabled_profiles_removed_from_file(tmp_path):
    conf = tmp_path / "conf.toml"
    write_config(conf, [make_profile(enabled=False)])
    doc = load_config(conf)
    assert doc.get("profile", []) == []


def test_write_creates_backup(tmp_path):
    conf = tmp_path / "conf.toml"
    conf.write_text("[global]\n", encoding="utf-8")
    write_config(conf, [make_profile()])
    assert (tmp_path / "conf.toml.armada-lsfg-adaptive.bak").exists()


def test_profile_from_block_defaults():
    p = profile_from_block({"active_in": ["A.exe"]})
    assert p.key == "a.exe"
    assert p.enabled is True
    assert p.adaptive is False


def test_conf_version_survives_legacy_misplacement(tmp_path):
    # a legacy file carried `version = 2` INSIDE [global] (parsed as
    # global.version): the rewrite must move it back to the true top level
    conf = tmp_path / "conf.toml"
    conf.write_text(
        '[global]\nversion = 2\ndll = "/d.dll"\n',
        encoding="utf-8",
    )
    write_config(conf, [make_profile()])
    doc = load_config(conf)
    assert doc["version"] == 2
    assert "version" not in doc["global"]
    assert doc["global"]["dll"] == "/d.dll"


def test_conf_version_normalized_from_v1(tmp_path):
    conf = tmp_path / "conf.toml"
    conf.write_text(
        'version = 1\n\n[global]\ndll = "/d.dll"\n',
        encoding="utf-8",
    )
    write_config(conf, [make_profile()])
    doc = load_config(conf)
    assert doc["version"] == 2


def test_conf_version_keeps_global_body(tmp_path):
    conf = tmp_path / "conf.toml"
    conf.write_text(
        'version = 2\n\n[global]\ndll = "/d.dll"\nallow_fp16 = true\n',
        encoding="utf-8",
    )
    write_config(conf, [make_profile()])
    doc = load_config(conf)
    assert doc["version"] == 2
    assert doc["global"]["allow_fp16"] is True
    assert doc["global"]["dll"] == "/d.dll"

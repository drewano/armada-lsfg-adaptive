import os

from lsfg.steam import (
    discover_executables,
    library_folders,
    parse_manifest,
    parse_vdf,
    scan_libraries,
)

LIBRARY_VDF = """
"libraryfolders"
{
	"0"
	{
		"path"		"/home/armada/.local/share/Steam"
		"label"		""
		"apps"
		{
			"228983"		"1223842"
		}
	}
	"1"
	{
		"path"		"/run/media/mmcblk0p1/SteamLibrary"
		"apps"
		{
			"1091500"		"83838383"
		}
	}
}
"""

APPMANIFEST = """
"AppState"
{
	"appid"		"1091500"
	"universe"		"1"
	"name"		"Cyberpunk 2077"
	"installdir"		"Cyberpunk 2077"
	"LastUpdated"		"1700000000"
}
"""


def test_parse_vdf_libraryfolders():
    doc = parse_vdf(LIBRARY_VDF)
    folders = doc["libraryfolders"]
    assert folders["0"]["path"] == "/home/armada/.local/share/Steam"
    assert folders["1"]["path"] == "/run/media/mmcblk0p1/SteamLibrary"
    assert folders["0"]["apps"]["228983"] == "1223842"


def test_parse_manifest():
    info = parse_manifest(APPMANIFEST)
    assert info == {
        "appid": "1091500",
        "name": "Cyberpunk 2077",
        "installdir": "Cyberpunk 2077",
    }


def test_parse_manifest_rejects_garbage():
    assert parse_manifest("not a manifest at all") is None


def _make_game_dir(root):
    game = root / "steamapps" / "common" / "Cyberpunk 2077"
    game.mkdir(parents=True)
    (game / "bin" / "x64").mkdir(parents=True)
    # main exe: name matches installdir
    (game / "bin" / "x64" / "Cyberpunk2077.exe").write_bytes(b"x" * 1000)
    # redist exe must be ignored
    redist = game / "Redist"
    redist.mkdir()
    (redist / "vcredist_x64.exe").write_bytes(b"x" * 5000)
    # small launcher exe
    (game / "Launcher.exe").write_bytes(b"x" * 10)
    return game


def test_discover_executables_filters_and_prefers_name_match(tmp_path):
    game = _make_game_dir(tmp_path)
    exes = discover_executables(game)
    paths = [e["path"] for e in exes]
    assert any("Cyberpunk2077.exe" in p for p in paths)
    assert not any("vcredist" in p.lower() for p in paths)
    assert exes[0]["path"].endswith("Cyberpunk2077.exe")


def test_library_folders_from_vdf(tmp_path):
    (tmp_path / "steamapps").mkdir()
    (tmp_path / "steamapps" / "libraryfolders.vdf").write_text(LIBRARY_VDF)
    folders = library_folders(tmp_path)
    # only libraries that actually exist on disk are returned
    assert tmp_path in folders


def test_scan_libraries_end_to_end(tmp_path, monkeypatch):
    import lsfg.steam as steam

    lib = tmp_path / "Steam"
    (lib / "steamapps").mkdir(parents=True)
    (lib / "steamapps" / "libraryfolders.vdf").write_text(
        LIBRARY_VDF.replace("/home/armada/.local/share/Steam", str(lib))
    )
    _make_game_dir(lib)
    # Lossless Scaling installed
    ls_dir = lib / "steamapps" / "common" / "Lossless Scaling"
    ls_dir.mkdir(parents=True)
    (ls_dir / "Lossless.dll").write_bytes(b"dll")
    (lib / "steamapps" / "appmanifest_1091500.acf").write_text(APPMANIFEST)
    (lib / "steamapps" / "appmanifest_993090.acf").write_text(
        APPMANIFEST.replace("1091500", "993090")
        .replace("Cyberpunk 2077", "Lossless Scaling")
    )

    monkeypatch.setattr(steam, "STEAM_ROOT_CANDIDATES", ("Steam",))
    result = scan_libraries(tmp_path)
    games = result["games"]
    assert len(games) == 1  # Lossless Scaling itself is skipped
    assert games[0]["name"] == "Cyberpunk 2077"
    assert games[0]["recommended"].endswith("Cyberpunk2077.exe")
    assert result["lossless_dll"].endswith("Lossless Scaling/Lossless.dll")

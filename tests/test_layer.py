import json
import struct

from lsfg.layer import LayerManager, elf_arch, load_layer_info


def make_elf(path, machine=183):
    """Craft a minimal fake ELF header (aarch64 by default)."""
    header = bytearray(64)
    header[0:4] = b"\x7fELF"
    header[4] = 2  # ELFCLASS64
    header[5] = 1  # little endian
    struct.pack_into("<H", header, 18, machine)
    path.write_bytes(bytes(header))
    return path


def make_bin_dir(tmp_path):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    info = {
        "layer_name": "VK_LAYER_LSFGVK_frame_generation",
        "lib": "liblsfg-vk-layer.so",
        "version": "0.13.0-adaptive",
        "source": "experimental",
        "capabilities": {"adaptive": True},
    }
    (bin_dir / "layer-info.json").write_text(json.dumps(info))
    make_elf(bin_dir / "liblsfg-vk-layer.so")
    return bin_dir, info


def test_elf_arch_detection(tmp_path):
    assert elf_arch(make_elf(tmp_path / "a.so", machine=183)) == "aarch64"
    assert elf_arch(make_elf(tmp_path / "b.so", machine=62)) == "x86_64"
    junk = tmp_path / "junk.so"
    junk.write_bytes(b"not an elf")
    assert elf_arch(junk) is None


def test_load_layer_info(tmp_path):
    bin_dir, info = make_bin_dir(tmp_path)
    assert load_layer_info(bin_dir) == info


def test_bundled_status(tmp_path):
    bin_dir, _ = make_bin_dir(tmp_path)
    mgr = LayerManager(user_home=tmp_path / "home", bin_dir=bin_dir, host_arch="aarch64")
    status = mgr.bundled_status()
    assert status["available"] is True
    assert status["arch_ok"] is True
    assert status["capabilities"]["adaptive"] is True


def test_bundled_status_arch_mismatch(tmp_path):
    bin_dir, _ = make_bin_dir(tmp_path)
    mgr = LayerManager(user_home=tmp_path / "home", bin_dir=bin_dir, host_arch="x86_64")
    status = mgr.bundled_status()
    assert status["arch_ok"] is False


def test_install_writes_lib_and_manifest(tmp_path):
    bin_dir, info = make_bin_dir(tmp_path)
    home = tmp_path / "home"
    mgr = LayerManager(user_home=home, bin_dir=bin_dir, host_arch="aarch64")
    status = mgr.install()

    lib = home / ".local/share/armada-lsfg-adaptive/lib/liblsfg-vk-layer.so"
    assert lib.is_file()
    manifest = home / ".local/share/vulkan/implicit_layer.d/VK_LAYER_LSFGVK_frame_generation.json"
    assert manifest.is_file()
    doc = json.loads(manifest.read_text())
    layer = doc["layer"]
    assert layer["name"] == info["layer_name"]
    assert layer["library_path"] == str(lib.resolve())
    assert layer["disable_environment"] == {
        "DISABLE_LSFGVK": "1",
        "DISABLE_LSFGVK_EXPERIMENTAL": "1",
    }
    assert status["installed"]["lib_exists"] is True
    assert status["installed"]["manifest_ok"] is True
    assert status["installed"]["version"] == "0.13.0-adaptive"


def test_install_rejects_wrong_arch(tmp_path):
    bin_dir, _ = make_bin_dir(tmp_path)
    mgr = LayerManager(user_home=tmp_path / "home", bin_dir=bin_dir, host_arch="x86_64")
    try:
        mgr.install()
        assert False, "should raise"
    except Exception as exc:
        assert "arch" in str(exc)


def test_needs_update_after_new_bundle(tmp_path):
    bin_dir, info = make_bin_dir(tmp_path)
    home = tmp_path / "home"
    mgr = LayerManager(user_home=home, bin_dir=bin_dir, host_arch="aarch64")
    mgr.install()
    assert mgr.status()["installed"]["needs_update"] is False
    # ship a new bundle version, same plugin version
    info["version"] = "0.14.0-adaptive"
    (bin_dir / "layer-info.json").write_text(json.dumps(info))
    mgr2 = LayerManager(user_home=home, bin_dir=bin_dir, host_arch="aarch64")
    assert mgr2.status()["installed"]["needs_update"] is True


def test_uninstall_removes_layer(tmp_path):
    bin_dir, _ = make_bin_dir(tmp_path)
    home = tmp_path / "home"
    mgr = LayerManager(user_home=home, bin_dir=bin_dir, host_arch="aarch64")
    mgr.install()
    mgr.uninstall()
    assert not (home / ".local/share/armada-lsfg-adaptive").is_dir()
    assert not mgr.manifest_path.exists()

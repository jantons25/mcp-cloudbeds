import json
from pathlib import Path

from cloudbeds_mcp.desktop_config import apply, find_config, merge, server_entry

ROOT = Path("D:/x/mcp-cloudbeds")


def test_server_entry_windows_y_macos():
    win = server_entry(ROOT, "win32")
    assert win["command"].endswith(str(Path(".venv/Scripts/python.exe")))
    assert win["args"] == ["-m", "cloudbeds_mcp.server"]
    assert win["env"]["PYTHONPATH"] == str(ROOT / "src")
    assert "cwd" not in win  # Claude Desktop lo descarta
    assert server_entry(ROOT, "darwin")["command"].endswith(str(Path(".venv/bin/python")))


def test_prefiere_claude_data_e_ignora_ubicacion_abandonada(tmp_path):
    local, roaming = tmp_path / "Local", tmp_path / "Roaming"
    data = local / "Claude-Data" / "claude_abc"
    data.mkdir(parents=True)
    legacy = local / "Packages" / "Claude_abc" / "LocalCache" / "Roaming" / "Claude"
    legacy.mkdir(parents=True)
    (legacy / ".user-data-left.claude_abc").touch()  # marcador real observado
    path, candidates = find_config({"LOCALAPPDATA": str(local), "APPDATA": str(roaming)}, tmp_path, "win32")
    assert path == data / "claude_desktop_config.json"
    assert legacy / "claude_desktop_config.json" not in candidates


def test_instalacion_clasica_usa_appdata(tmp_path):
    roaming = tmp_path / "Roaming"
    (roaming / "Claude").mkdir(parents=True)
    path, _ = find_config({"LOCALAPPDATA": str(tmp_path / "Local"), "APPDATA": str(roaming)}, tmp_path, "win32")
    assert path == roaming / "Claude" / "claude_desktop_config.json"


def test_varias_carpetas_claude_data_es_ambiguo(tmp_path):
    local = tmp_path / "Local"
    (local / "Claude-Data" / "claude_a").mkdir(parents=True)
    (local / "Claude-Data" / "claude_b").mkdir(parents=True)
    path, candidates = find_config({"LOCALAPPDATA": str(local)}, tmp_path, "win32")
    assert path is None and len(candidates) == 2


def test_macos(tmp_path):
    path, _ = find_config({}, tmp_path, "darwin")
    assert path == tmp_path / "Library" / "Application Support" / "Claude" / "claude_desktop_config.json"


def test_merge_conserva_otras_claves_y_servidores():
    entry = server_entry(ROOT, "win32")
    config = {"preferences": {"x": 1}, "mcpServers": {"otro": {"command": "a"}}}
    new, changed = merge(config, entry)
    assert changed and new["preferences"] == {"x": 1}
    assert set(new["mcpServers"]) == {"otro", "cloudbeds"}
    assert merge(new, entry) == (new, False)


def test_apply_hace_backup_y_conserva_bom(tmp_path):
    path = tmp_path / "claude_desktop_config.json"
    path.write_bytes(b"\xef\xbb\xbf" + json.dumps({"preferences": {"a": True}}).encode())
    changed, backup = apply(path, server_entry(ROOT, "win32"))
    assert changed and backup and backup.exists()
    raw = path.read_bytes()
    assert raw.startswith(b"\xef\xbb\xbf")
    data = json.loads(raw.decode("utf-8-sig"))
    assert data["preferences"] == {"a": True} and "cloudbeds" in data["mcpServers"]
    assert apply(path, server_entry(ROOT, "win32")) == (False, None)


def test_apply_crea_archivo_si_no_existe(tmp_path):
    path = tmp_path / "nuevo" / "claude_desktop_config.json"
    changed, backup = apply(path, server_entry(ROOT, "win32"))
    assert changed and backup is None
    assert json.loads(path.read_text(encoding="utf-8"))["mcpServers"]["cloudbeds"]["args"] == ["-m", "cloudbeds_mcp.server"]

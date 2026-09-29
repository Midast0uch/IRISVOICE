import json

import config

ORIGINAL_DEFAULTS = {"host": "127.0.0.1", "port": 8080, "debug": False, "log_level": "info"}


def test_missing_keys_filled(tmp_path):
    path = tmp_path / "c.json"
    path.write_text(json.dumps({"port": 9000, "debug": True}), encoding="utf-8")
    cfg = config.load_config(str(path))
    assert cfg == {"host": "127.0.0.1", "port": 9000, "debug": True, "log_level": "info"}


def test_extra_keys_kept(tmp_path):
    path = tmp_path / "c.json"
    path.write_text(json.dumps({"theme": "dark"}), encoding="utf-8")
    cfg = config.load_config(str(path))
    assert cfg["theme"] == "dark" and cfg["port"] == 8080


def test_missing_file_gives_a_copy_of_defaults(tmp_path):
    cfg = config.load_config(str(tmp_path / "nope.json"))
    assert cfg == ORIGINAL_DEFAULTS
    assert cfg is not config.DEFAULTS


def test_defaults_never_modified(tmp_path):
    cfg = config.load_config(str(tmp_path / "nope.json"))
    cfg["port"] = 1
    path = tmp_path / "c.json"
    path.write_text(json.dumps({"host": "0.0.0.0"}), encoding="utf-8")
    config.load_config(str(path))["log_level"] = "debug"
    assert config.DEFAULTS == ORIGINAL_DEFAULTS

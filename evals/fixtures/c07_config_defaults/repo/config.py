"""Application configuration loading."""

import json

DEFAULTS = {"host": "127.0.0.1", "port": 8080, "debug": False, "log_level": "info"}


def load_config(path):
    """Load the JSON config file at `path`."""
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)

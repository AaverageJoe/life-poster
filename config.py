"""JSON-backed settings store for Life Poster.

One global config dict, persisted to data/settings.json. Thread-safe enough for
our use: a single lock guards read-modify-write, and the worker only reads.
"""
from __future__ import annotations

import copy
import json
import os
import threading

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
UPLOAD_DIR = os.path.join(DATA_DIR, "uploads")
PREVIEW_DIR = os.path.join(DATA_DIR, "preview")
SETTINGS_PATH = os.path.join(DATA_DIR, "settings.json")

for _d in (DATA_DIR, UPLOAD_DIR, PREVIEW_DIR):
    os.makedirs(_d, exist_ok=True)

# Display panel is 800x480 for both the 7-colour and Spectra 6 7.3" boards.
PANEL_W = 800
PANEL_H = 480

DEFAULTS = {
    # active mode: poster | control | info | draw
    "mode": "info",
    "display": {
        "rotation": 0,          # 0 | 90 | 180 | 270
        "saturation": 0.5,       # 0.0 - 1.0, passed to inky.set_image
        "fit": "cover",          # cover | contain
        "background": "#ffffff",  # letterbox colour when fit == contain
        "auto_enhance": False,    # mild contrast/sharpness bump before dithering
    },
    "poster": {
        "interval_minutes": 60,
        "shuffle": False,
        "playlist": [],           # filenames living in data/uploads
        "index": 0,
    },
    "info": {
        "headline": "",
        "show_seconds": False,
        "time_format": "24h",     # 24h | 12h
        "refresh_minutes": 10,
        "bg": "#ffffff",
        "fg": "#000000",
        "accent": "#d4001a",
    },
    "control": {"current": None},   # filename in data/uploads
    "draw": {"last": None},         # filename in data/uploads
}

_lock = threading.RLock()
_config: dict = {}


def _deep_merge(base: dict, override: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in (override or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def load() -> dict:
    global _config
    with _lock:
        stored = {}
        if os.path.exists(SETTINGS_PATH):
            try:
                with open(SETTINGS_PATH, "r", encoding="utf-8") as fh:
                    stored = json.load(fh)
            except (ValueError, OSError):
                stored = {}
        _config = _deep_merge(DEFAULTS, stored)
        return copy.deepcopy(_config)


def get() -> dict:
    with _lock:
        if not _config:
            load()
        return copy.deepcopy(_config)


def save(mutator) -> dict:
    """Apply mutator(cfg) in place under the lock, then persist."""
    global _config
    with _lock:
        if not _config:
            load()
        mutator(_config)
        tmp = SETTINGS_PATH + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(_config, fh, indent=2)
        os.replace(tmp, SETTINGS_PATH)
        return copy.deepcopy(_config)


load()

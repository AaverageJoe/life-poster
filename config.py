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

MODES = ("poster", "control", "info", "draw")

DEFAULTS = {
    # active mode: poster | control | info | draw
    "mode": "poster",
    # what mode to jump to on service start: last | poster | control | info | draw
    "boot_mode": "poster",
    "display": {
        "rotation": 0,            # 0 | 90 | 180 | 270  (global default)
        "saturation": 0.5,        # 0.0 - 1.0, passed to inky.set_image
        "fit": "cover",           # cover | contain
        "background": "#ffffff",  # letterbox colour when fit == contain
        "auto_enhance": False,    # mild contrast/sharpness bump before dithering
    },
    "poster": {
        "interval_minutes": 60,
        "shuffle": False,
        # list of {"name": str, "rotation": int, "fit": "cover"|"contain"|None}
        "playlist": [],
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
        "weather": "",            # optional "town,country" for a wttr.in line
    },
    "control": {"current": None, "pending": None},
    "draw": {"last": None},
    "buttons": {"enabled": True},  # A/B step poster, C cycle mode, D refresh
    "schedule": {                 # blank the panel overnight to reduce wear
        "sleep_enabled": False,
        "sleep_start": "23:00",
        "sleep_end": "07:00",
    },
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


def _normalise(cfg: dict) -> None:
    """Migrate older shapes in place (e.g. playlist of bare filenames)."""
    pl = cfg.get("poster", {}).get("playlist", []) or []
    norm = []
    for item in pl:
        if isinstance(item, str):
            norm.append({"name": item, "rotation": 0, "fit": None})
        elif isinstance(item, dict) and item.get("name"):
            fit = item.get("fit")
            norm.append({
                "name": str(item["name"]),
                "rotation": int(item.get("rotation", 0)) % 360,
                "fit": fit if fit in ("cover", "contain") else None,
            })
    cfg["poster"]["playlist"] = norm
    if cfg.get("mode") not in MODES:
        cfg["mode"] = "poster"
    if cfg.get("boot_mode") not in ("last", *MODES):
        cfg["boot_mode"] = "poster"


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
        _normalise(_config)
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
        _normalise(_config)
        tmp = SETTINGS_PATH + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(_config, fh, indent=2)
        os.replace(tmp, SETTINGS_PATH)
        return copy.deepcopy(_config)


load()

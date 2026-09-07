"""Background worker: owns the display, reacts to config + explicit requests.

Web handlers change config.py and call `wake()` / `request_show(...)`. They never
block on an e-ink refresh - this thread does.
"""
from __future__ import annotations

import datetime as _dt
import gc
import os
import random
import threading
import time

from PIL import Image

import config
import render
from display import Controller

_controller = Controller()
_wake = threading.Event()
_lock = threading.Lock()

# an explicit one-off render request from the UI (control confirm, draw push,
# manual refresh). Tuple of (image, source).
_pending: tuple[Image.Image, str] | None = None

_state = {
    "poster_last_switch": 0.0,
    "poster_shown_index": -1,
    "poster_generation": 0,
    "info_last_key": None,
    "active_mode": None,
    "asleep": False,
}
_generation = 0


def controller() -> Controller:
    return _controller


def wake():
    _wake.set()


def bump_generation():
    """Tell the worker that mode/playlist/settings changed and a redraw is due."""
    global _generation
    with _lock:
        _generation += 1
    _wake.set()


def request_show(img: Image.Image, source: str):
    global _pending
    with _lock:
        _pending = (img.copy(), source)
    _wake.set()


def poster_step(delta: int):
    """Move the poster playlist by `delta` and show that image now (board buttons)."""
    pl = config.get()["poster"]["playlist"]
    if not pl:
        config.save(lambda c: c.__setitem__("mode", "poster"))
        bump_generation()
        return

    def mut(c):
        n = len(c["poster"]["playlist"])
        c["poster"]["index"] = (int(c["poster"]["index"]) + delta) % n
        c["mode"] = "poster"
    config.save(mut)
    bump_generation()


def cycle_mode():
    order = list(config.MODES)
    cur = config.get()["mode"]
    nxt = order[(order.index(cur) + 1) % len(order)] if cur in order else order[0]
    config.save(lambda c: c.__setitem__("mode", nxt))
    bump_generation()


def status() -> dict:
    cfg = config.get()
    c = _controller
    pl = cfg["poster"]["playlist"]
    idx = int(cfg["poster"]["index"]) % len(pl) if pl else 0
    return {
        "mode": cfg["mode"],
        "device": c.kind,
        "resolution": list(c.resolution),
        "busy": c.busy,
        "error": c.error,
        "last_source": c.last_source,
        "last_shown_at": c.last_shown_at,
        "poster_index": idx,
        "poster_count": len(pl),
        "poster_current": pl[idx]["name"] if pl else None,
        "asleep": _state["asleep"],
    }


def _upload_path(name: str) -> str:
    return os.path.join(config.UPLOAD_DIR, name)


def _show_saturation(cfg) -> float:
    try:
        return max(0.0, min(1.0, float(cfg["display"]["saturation"])))
    except (KeyError, TypeError, ValueError):
        return 0.5


def _display_cfg_for(cfg, *, rotation=None, fit=None) -> dict:
    d = dict(cfg["display"])
    if rotation is not None:
        d["rotation"] = int(rotation) % 360
    if fit in ("cover", "contain"):
        d["fit"] = fit
    return d


def _load_upload(name: str) -> Image.Image | None:
    if not name:
        return None
    path = _upload_path(name)
    if not os.path.exists(path):
        return None
    try:
        return Image.open(path)
    except OSError:
        return None


def _push(img: Image.Image, source: str, cfg) -> None:
    _controller.push(img, source, _show_saturation(cfg))
    gc.collect()  # keep RSS down on the 512 MB Pi Zero


# --------------------------------------------------------------------------- #
# scheduled sleep (blank panel overnight)
# --------------------------------------------------------------------------- #
def _in_sleep_window(cfg, now: _dt.datetime | None = None) -> bool:
    s = cfg.get("schedule", {})
    if not s.get("sleep_enabled"):
        return False
    now = now or _dt.datetime.now()

    def _parse(hm, default):
        try:
            h, m = hm.split(":")
            return int(h) * 60 + int(m)
        except (ValueError, AttributeError):
            return default

    start = _parse(s.get("sleep_start"), 23 * 60)
    end = _parse(s.get("sleep_end"), 7 * 60)
    cur = now.hour * 60 + now.minute
    return start <= cur < end if start <= end else (cur >= start or cur < end)


# --------------------------------------------------------------------------- #
# per-mode handlers
# --------------------------------------------------------------------------- #
def _handle_pending(cfg) -> bool:
    global _pending
    with _lock:
        item = _pending
        _pending = None
    if not item:
        return False
    img, source = item
    prepared = render.prepare_image(img, cfg["display"])
    _push(prepared, source, cfg)
    with _lock:
        _state["active_mode"] = cfg["mode"]
        _state["poster_generation"] = _generation
        if cfg["mode"] == "info":
            _state["info_last_key"] = render.info_key(cfg["info"])
    return True


def _handle_poster(cfg, gen: int):
    playlist = list(cfg["poster"]["playlist"])
    if not playlist:
        if _state["info_last_key"] != "poster-empty" or gen != _state["poster_generation"]:
            _push(render.placeholder("Poster mode: add images"), "poster:empty", cfg)
            _state["info_last_key"] = "poster-empty"
            _state["poster_generation"] = gen
        return

    interval = max(1, int(cfg["poster"]["interval_minutes"])) * 60
    now = time.time()
    changed_config = gen != _state["poster_generation"]
    index = int(cfg["poster"]["index"]) % len(playlist)

    due = (now - _state["poster_last_switch"]) >= interval
    first_paint = _state["poster_shown_index"] != index or changed_config

    if due and not first_paint:
        if cfg["poster"]["shuffle"] and len(playlist) > 1:
            index = random.choice([i for i in range(len(playlist)) if i != index])
        else:
            index = (index + 1) % len(playlist)
        config.save(lambda c: c["poster"].__setitem__("index", index))
        first_paint = True

    if first_paint:
        entry = playlist[index]
        img = _load_upload(entry["name"])
        if img is None:
            config.save(lambda c: c["poster"].__setitem__(
                "playlist", [e for e in c["poster"]["playlist"] if e["name"] != entry["name"]]))
            bump_generation()
            return
        dcfg = _display_cfg_for(cfg, rotation=entry.get("rotation", 0), fit=entry.get("fit"))
        _push(render.prepare_image(img, dcfg), f"poster:{entry['name']}", cfg)
        _state["poster_last_switch"] = now
        _state["poster_shown_index"] = index
        _state["poster_generation"] = gen


def _handle_info(cfg, gen: int):
    key = render.info_key(cfg["info"])
    if key == _state["info_last_key"] and gen == _state["poster_generation"]:
        return
    _push(render.render_info(cfg["info"]), "info", cfg)
    _state["info_last_key"] = key
    _state["poster_generation"] = gen


def _handle_static(cfg, gen: int, mode: str):
    """control / draw: only repaint on an explicit request or a fresh switch."""
    if gen == _state["poster_generation"] and _state["active_mode"] == mode:
        return
    name = cfg[mode].get("current" if mode == "control" else "last")
    img = _load_upload(name)
    if img is None:
        _push(render.placeholder(
            "Control mode: upload an image" if mode == "control"
            else "Draw mode: sketch, then Push to display"), f"{mode}:empty", cfg)
    else:
        _push(render.prepare_image(img, cfg["display"]), f"{mode}:{name}", cfg)
    _state["poster_generation"] = gen


def _tick():
    global _generation
    with _lock:
        gen = _generation
    cfg = config.get()
    mode = cfg["mode"]

    if _handle_pending(cfg):
        return

    # scheduled sleep overrides everything
    if _in_sleep_window(cfg):
        if not _state["asleep"]:
            white = Image.new("RGB", tuple(_controller.resolution), (255, 255, 255))
            _push(white, "sleep", cfg)
            _state["asleep"] = True
        return
    if _state["asleep"]:
        _state["asleep"] = False
        _state["poster_shown_index"] = -1
        _state["info_last_key"] = None
        bump_generation()
        with _lock:
            gen = _generation

    if mode != _state["active_mode"]:
        _state["active_mode"] = mode
        _state["poster_shown_index"] = -1
        _state["info_last_key"] = None
        bump_generation()
        with _lock:
            gen = _generation

    if mode == "poster":
        _handle_poster(cfg, gen)
    elif mode == "info":
        _handle_info(cfg, gen)
    else:
        _handle_static(cfg, gen, mode)


def _run():
    time.sleep(2)  # first paint shortly after boot
    while True:
        try:
            _tick()
        except Exception as exc:  # noqa: BLE001 - keep the loop alive
            print(f"[worker] tick error: {exc!r}")
        _wake.wait(timeout=15)
        _wake.clear()


def start():
    t = threading.Thread(target=_run, name="lifeposter-worker", daemon=True)
    t.start()
    return t

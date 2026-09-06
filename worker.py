"""Background worker: owns the display, reacts to config + explicit requests.

Web handlers change config.py and call `wake()` / `request_show(...)`. They never
block on an e-ink refresh - this thread does.
"""
from __future__ import annotations

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

# an explicit one-off render request from the UI (control upload, draw push,
# manual refresh). Tuple of (image, source).
_pending: tuple[Image.Image, str] | None = None

_state = {
    "poster_last_switch": 0.0,
    "poster_shown_index": -1,
    "poster_generation": 0,
    "info_last_key": None,
    "active_mode": None,
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


def status() -> dict:
    cfg = config.get()
    c = _controller
    return {
        "mode": cfg["mode"],
        "device": c.kind,
        "resolution": list(c.resolution),
        "busy": c.busy,
        "error": c.error,
        "last_source": c.last_source,
        "last_shown_at": c.last_shown_at,
        "poster_index": cfg["poster"]["index"],
        "poster_count": len(cfg["poster"]["playlist"]),
    }


def _upload_path(name: str) -> str:
    return os.path.join(config.UPLOAD_DIR, name)


def _show_saturation(cfg) -> float:
    try:
        return max(0.0, min(1.0, float(cfg["display"]["saturation"])))
    except (KeyError, TypeError, ValueError):
        return 0.5


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


def _handle_pending(cfg) -> bool:
    global _pending
    with _lock:
        item = _pending
        _pending = None
    if not item:
        return False
    img, source = item
    prepared = render.prepare_image(img, cfg["display"])
    _controller.push(prepared, source, _show_saturation(cfg))
    # this explicit push already reflects the current mode/config, so sync
    # worker state to stop a mode-switch/generation repaint on the next tick.
    with _lock:
        _state["active_mode"] = cfg["mode"]
        _state["poster_generation"] = _generation
        _state["info_last_key"] = render.info_key(cfg["info"]) if cfg["mode"] == "info" else _state["info_last_key"]
    return True


def _handle_poster(cfg, gen: int):
    playlist = list(cfg["poster"]["playlist"])
    if not playlist:
        if _state["info_last_key"] != "poster-empty" or gen != _state["poster_generation"]:
            _controller.push(render.placeholder("Poster mode: add images"),
                             "poster:empty", _show_saturation(cfg))
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
            choices = [i for i in range(len(playlist)) if i != index]
            index = random.choice(choices)
        else:
            index = (index + 1) % len(playlist)
        config.save(lambda c: c["poster"].__setitem__("index", index))
        first_paint = True

    if first_paint:
        img = _load_upload(playlist[index])
        if img is None:
            # drop the missing file and retry next tick
            config.save(lambda c: c["poster"].__setitem__(
                "playlist", [p for p in c["poster"]["playlist"] if p != playlist[index]]))
            bump_generation()
            return
        prepared = render.prepare_image(img, cfg["display"])
        _controller.push(prepared, f"poster:{playlist[index]}", _show_saturation(cfg))
        _state["poster_last_switch"] = now
        _state["poster_shown_index"] = index
        _state["poster_generation"] = gen


def _handle_info(cfg, gen: int):
    key = render.info_key(cfg["info"])
    if key == _state["info_last_key"] and gen == _state["poster_generation"]:
        return
    _controller.push(render.render_info(cfg["info"]), "info", _show_saturation(cfg))
    _state["info_last_key"] = key
    _state["poster_generation"] = gen


def _handle_static(cfg, gen: int, mode: str):
    """control / draw: only repaint on an explicit request or a fresh switch."""
    if gen == _state["poster_generation"] and _state["active_mode"] == mode:
        return
    name = cfg[mode].get("current" if mode == "control" else "last")
    img = _load_upload(name)
    if img is None:
        _controller.push(render.placeholder(
            "Control mode: upload an image" if mode == "control"
            else "Draw mode: sketch, then Push to display"),
            f"{mode}:empty", _show_saturation(cfg))
    else:
        prepared = render.prepare_image(img, cfg["display"])
        _controller.push(prepared, f"{mode}:{name}", _show_saturation(cfg))
    _state["poster_generation"] = gen


def _tick():
    global _generation
    with _lock:
        gen = _generation
    cfg = config.get()
    mode = cfg["mode"]

    if _handle_pending(cfg):
        return

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
    # first paint shortly after boot
    time.sleep(2)
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

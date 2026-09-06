"""Device layer: wraps the Inky panel, with a file-only mock fallback.

The panel and the SPI bus are single-owner: only the worker thread calls
`show()`. HTTP handlers never touch this module directly.
"""
from __future__ import annotations

import os
import threading
import time

from PIL import Image

import config

PREVIEW_PATH = os.path.join(config.PREVIEW_DIR, "current.png")


class BaseDisplay:
    resolution = (config.PANEL_W, config.PANEL_H)
    kind = "mock"

    def show_image(self, img: Image.Image, saturation: float) -> None:
        raise NotImplementedError


class MockDisplay(BaseDisplay):
    kind = "mock"

    def show_image(self, img: Image.Image, saturation: float) -> None:
        # emulate the ~35s full refresh so timings feel real in dev
        time.sleep(1.0)


class InkyDisplay(BaseDisplay):
    def __init__(self, inky):
        self._inky = inky
        self.resolution = tuple(inky.resolution)
        self.kind = type(inky).__module__.split(".")[-1]

    def show_image(self, img: Image.Image, saturation: float) -> None:
        if img.size != self.resolution:
            img = img.resize(self.resolution, Image.LANCZOS)
        try:
            self._inky.set_image(img, saturation=saturation)
        except TypeError:
            self._inky.set_image(img)
        self._inky.show()


def _make_device() -> BaseDisplay:
    if os.environ.get("LIFEPOSTER_MOCK") == "1":
        return MockDisplay()
    try:
        from inky.auto import auto
        return InkyDisplay(auto(ask_user=False, verbose=False))
    except Exception as exc:  # noqa: BLE001 - any failure -> mock so the UI still works
        print(f"[display] Inky not available ({exc!r}); using mock display")
        return MockDisplay()


class Controller:
    def __init__(self):
        self._device = _make_device()
        self._lock = threading.Lock()
        self.busy = False
        self.last_source = None
        self.last_shown_at = 0.0
        self.error = None

    @property
    def kind(self) -> str:
        return self._device.kind

    @property
    def resolution(self):
        return self._device.resolution

    def push(self, img: Image.Image, source: str, saturation: float) -> None:
        with self._lock:
            self.busy = True
            self.error = None
            try:
                rgb = img.convert("RGB")
                rgb.save(PREVIEW_PATH)
                self._device.show_image(rgb, saturation)
                self.last_source = source
                self.last_shown_at = time.time()
            except Exception as exc:  # noqa: BLE001
                self.error = repr(exc)
                print(f"[display] push failed: {exc!r}")
            finally:
                self.busy = False

"""Physical buttons on the Inky Impression board.

The 7.3" Impression (both the 2022 7-colour and the 2024 Spectra 6) has four
tactile buttons wired to BCM GPIO 5 / 6 / 16 / 24, active-low with pull-ups.

  A (GPIO 5)  -> previous poster image
  B (GPIO 6)  -> next poster image
  C (GPIO 16) -> cycle display mode
  D (GPIO 24) -> re-send / refresh the current image

Everything here is best-effort: on a machine with no GPIO (dev laptop, or the
mock display) it logs one line and does nothing. It never raises into the app.
"""
from __future__ import annotations

import threading
import time

import config
import worker

# BCM pin -> label
PINS = {5: "A", 6: "B", 16: "C", 24: "D"}
_DEBOUNCE_S = 0.25
_last_fire: dict[str, float] = {}


def _dispatch(label: str) -> None:
    now = time.monotonic()
    if now - _last_fire.get(label, 0.0) < _DEBOUNCE_S:
        return
    _last_fire[label] = now
    try:
        if label == "A":
            worker.poster_step(-1)
        elif label == "B":
            worker.poster_step(+1)
        elif label == "C":
            worker.cycle_mode()
        elif label == "D":
            worker.bump_generation()
        print(f"[buttons] {label} pressed")
    except Exception as exc:  # noqa: BLE001
        print(f"[buttons] handler error on {label}: {exc!r}")


# --------------------------------------------------------------------------- #
# backend: libgpiod v2 (what current Raspberry Pi OS ships, and an inky dep)
# --------------------------------------------------------------------------- #
def _run_gpiod() -> bool:
    try:
        from datetime import timedelta

        import gpiod
        from gpiod.line import Bias, Edge
    except Exception:  # noqa: BLE001
        return False

    chip_path = None
    for cand in ("/dev/gpiochip0", "/dev/gpiochip4", "/dev/gpiochip1"):
        try:
            with gpiod.Chip(cand) as chip:
                info = chip.get_info()
                if info.num_lines >= 25:
                    chip_path = cand
                    break
        except Exception:  # noqa: BLE001
            continue
    if chip_path is None:
        return False

    settings = gpiod.LineSettings(
        edge_detection=Edge.FALLING,
        bias=Bias.PULL_UP,
        debounce_period=timedelta(milliseconds=40),
    )
    try:
        request = gpiod.request_lines(
            chip_path,
            consumer="lifeposter-buttons",
            config={tuple(PINS): settings},
        )
    except Exception as exc:  # noqa: BLE001
        print(f"[buttons] gpiod request failed: {exc!r}")
        return False

    print(f"[buttons] gpiod on {chip_path}: A/B step, C mode, D refresh")
    with request:
        while True:
            if request.wait_edge_events(timeout=None):
                for event in request.read_edge_events():
                    label = PINS.get(event.line_offset)
                    if label:
                        _dispatch(label)
    return True


# --------------------------------------------------------------------------- #
# backend: RPi.GPIO  (rpi-lgpio shim on Bookworm/Trixie provides this API)
# --------------------------------------------------------------------------- #
def _run_rpignpio() -> bool:
    try:
        import RPi.GPIO as GPIO
    except Exception:  # noqa: BLE001
        return False
    try:
        GPIO.setmode(GPIO.BCM)
        GPIO.setup(list(PINS), GPIO.IN, pull_up_down=GPIO.PUD_UP)
        for pin, label in PINS.items():
            GPIO.add_event_detect(
                pin, GPIO.FALLING,
                callback=lambda p, lbl=label: _dispatch(lbl),
                bouncetime=250,
            )
    except Exception as exc:  # noqa: BLE001
        print(f"[buttons] RPi.GPIO setup failed: {exc!r}")
        return False
    print("[buttons] RPi.GPIO: A/B step, C mode, D refresh")
    while True:
        time.sleep(3600)
    return True


def _run() -> None:
    if not config.get().get("buttons", {}).get("enabled", True):
        print("[buttons] disabled in settings")
        return
    for backend in (_run_gpiod, _run_rpignpio):
        try:
            if backend():
                return
        except Exception as exc:  # noqa: BLE001
            print(f"[buttons] {backend.__name__} crashed: {exc!r}")
    print("[buttons] no GPIO backend available - board buttons inactive")


def start() -> threading.Thread:
    t = threading.Thread(target=_run, name="lifeposter-buttons", daemon=True)
    t.start()
    return t

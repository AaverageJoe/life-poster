# Life Poster

A local web control panel for a **Pimoroni Inky Impression 7.3" (Spectra 6)**
on a **Raspberry Pi Zero W** running **Raspberry Pi OS 32-bit**.

Open `http://<pi>:8080/` on any device on your home network. No login (LAN only).

## Modes

| Mode | What it does |
|------|--------------|
| **Poster** | Rotate through a playlist of images on a timer (minutes per image, optional shuffle). |
| **Control** | Upload one image; it goes straight to the panel and stays. |
| **Info** | Big clock + day + date, optional headline strip. Redraws every _N_ minutes (or every few seconds if you enable seconds — hard on the panel). |
| **Draw** | Sketch on a browser canvas in the 6 panel colours. Live preview is in the browser; **Push to display** sends the final drawing (one ~35 s refresh). Optional server-side "preview as panel" shows the dithered result. |
| **Settings** | Rotation, cover/contain fit, letterbox colour, saturation, auto-enhance. Applied to every image before dithering. |

## How it works

- `serve.py` runs Flask under **waitress** on port 8080.
- A single background **worker thread** owns the SPI bus / panel. HTTP requests
  never block on a refresh — they update `data/settings.json` and wake the worker.
- If no Inky panel is detected the app runs in **mock mode**: the web UI and the
  "On the display" preview still work, nothing is sent to hardware.
- Uploaded images live in `data/uploads/` and are garbage-collected when no mode
  references them.

## Install on the Pi

Get this folder onto the Pi (git clone, or paste `deploy.sh` into the Pi Connect
shell), then:

```bash
cd ~/life-poster && bash install.sh
```

The installer:

- apt-installs `libopenblas0` / `libgfortran5` (the missing bit that breaks NumPy
  in pip venvs on Trixie), fonts and `i2c-tools`;
- enables SPI + I2C and adds you to the `spi` / `gpio` / `i2c` groups;
- **reuses an existing working `inky` venv** if it finds one (e.g. Pimoroni's
  `~/.virtualenvs/pimoroni`), only adding Flask + waitress to it; otherwise builds
  its own `.venv` with `--system-site-packages` and pip-installs `inky`;
- installs and starts the `lifeposter` systemd service on port 8080.

**Reboot once** afterwards if SPI/I2C were just enabled.

Regenerate `deploy.sh` after code changes with `python build_installer.py`.

## Run it manually / develop

```bash
# on the Pi
.venv/bin/python serve.py

# anywhere, no hardware (mock display):
LIFEPOSTER_MOCK=1 python app.py        # dev server on :8080
```

## Service management

```bash
journalctl -u lifeposter -f          # logs
sudo systemctl restart lifeposter
sudo systemctl disable --now lifeposter
```

## Notes & limits

- The Spectra 6 panel refreshes in ~30–40 s and is not meant for frequent
  updates. Ghosting builds up; a `Clear display` (white flush) helps.
- Panel palette is black / white / red / yellow / blue / green. Pick strong,
  saturated colours in Info mode; photos are auto-dithered.
- The Pi Zero W is single-core ARMv6 — page loads and image processing are
  unhurried. That's normal.

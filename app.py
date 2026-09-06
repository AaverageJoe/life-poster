"""Life Poster - local web control panel for an Inky Impression 7.3" display."""
from __future__ import annotations

import base64
import io
import os
import time
import uuid

from flask import (Flask, abort, jsonify, redirect, render_template, request,
                   send_file, send_from_directory, url_for)
from PIL import Image
from werkzeug.utils import secure_filename

import config
import render
import worker

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 24 * 1024 * 1024  # 24 MB uploads

ALLOWED = {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp"}
MODES = ("poster", "control", "info", "draw")


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #
def _save_upload(file_storage, prefix: str) -> str:
    ext = os.path.splitext(file_storage.filename or "")[1].lower()
    if ext not in ALLOWED:
        abort(400, f"Unsupported file type: {ext or '?'}")
    name = f"{prefix}-{int(time.time())}-{uuid.uuid4().hex[:8]}{ext}"
    name = secure_filename(name)
    path = os.path.join(config.UPLOAD_DIR, name)
    file_storage.save(path)
    try:
        Image.open(path).verify()
    except Exception:  # noqa: BLE001
        os.remove(path)
        abort(400, "That file is not a readable image")
    return name


def _save_pil(img: Image.Image, prefix: str) -> str:
    name = f"{prefix}-{int(time.time())}-{uuid.uuid4().hex[:8]}.png"
    img.convert("RGB").save(os.path.join(config.UPLOAD_DIR, name))
    return name


def _uploads_in_use() -> set[str]:
    cfg = config.get()
    used = set(cfg["poster"]["playlist"])
    used.add(cfg["control"].get("current"))
    used.add(cfg["draw"].get("last"))
    return {u for u in used if u}


def _gc_uploads():
    """Delete upload files no mode references any more (keeps the card small)."""
    keep = _uploads_in_use()
    for fn in os.listdir(config.UPLOAD_DIR):
        if fn not in keep:
            try:
                os.remove(os.path.join(config.UPLOAD_DIR, fn))
            except OSError:
                pass


# --------------------------------------------------------------------------- #
# pages
# --------------------------------------------------------------------------- #
@app.route("/")
def dashboard():
    return render_template("dashboard.html", cfg=config.get(), status=worker.status())


@app.route("/poster")
def poster_page():
    cfg = config.get()
    return render_template("poster.html", cfg=cfg, status=worker.status())


@app.route("/control")
def control_page():
    return render_template("control.html", cfg=config.get(), status=worker.status())


@app.route("/info")
def info_page():
    return render_template("info.html", cfg=config.get(), status=worker.status())


@app.route("/draw")
def draw_page():
    return render_template("draw.html", cfg=config.get(), status=worker.status())


@app.route("/settings")
def settings_page():
    return render_template("settings.html", cfg=config.get(), status=worker.status())


# --------------------------------------------------------------------------- #
# actions
# --------------------------------------------------------------------------- #
@app.post("/mode")
def set_mode():
    mode = request.form.get("mode", "")
    if mode not in MODES:
        abort(400, "unknown mode")
    config.save(lambda c: c.__setitem__("mode", mode))
    worker.bump_generation()
    return redirect(request.form.get("next") or url_for("dashboard"))


@app.post("/poster/upload")
def poster_upload():
    files = request.files.getlist("images")
    added = [_save_upload(f, "poster") for f in files if f and f.filename]
    if added:
        config.save(lambda c: c["poster"].__setitem__(
            "playlist", c["poster"]["playlist"] + added))
        worker.bump_generation()
    return redirect(url_for("poster_page"))


@app.post("/poster/save")
def poster_save():
    def mut(c):
        p = c["poster"]
        p["interval_minutes"] = max(1, int(request.form.get("interval_minutes", 60)))
        p["shuffle"] = request.form.get("shuffle") == "on"
        order = request.form.getlist("order")
        if order:
            current = set(p["playlist"])
            p["playlist"] = [n for n in order if n in current]
        p["index"] = 0
    config.save(mut)
    if request.form.get("activate") == "on":
        config.save(lambda c: c.__setitem__("mode", "poster"))
    worker.bump_generation()
    return redirect(url_for("poster_page"))


@app.post("/poster/remove")
def poster_remove():
    name = request.form.get("name", "")
    config.save(lambda c: c["poster"].__setitem__(
        "playlist", [n for n in c["poster"]["playlist"] if n != name]))
    _gc_uploads()
    worker.bump_generation()
    return redirect(url_for("poster_page"))


@app.post("/control/upload")
def control_upload():
    f = request.files.get("image")
    if not f or not f.filename:
        abort(400, "no image")
    name = _save_upload(f, "control")
    config.save(lambda c: (c["control"].__setitem__("current", name),
                           c.__setitem__("mode", "control")))
    _gc_uploads()
    worker.bump_generation()
    return redirect(url_for("control_page"))


@app.post("/info/save")
def info_save():
    def mut(c):
        i = c["info"]
        i["headline"] = request.form.get("headline", "").strip()[:120]
        i["show_seconds"] = request.form.get("show_seconds") == "on"
        i["time_format"] = "12h" if request.form.get("time_format") == "12h" else "24h"
        i["refresh_minutes"] = max(1, int(request.form.get("refresh_minutes", 10)))
        for key in ("bg", "fg", "accent"):
            val = request.form.get(key, "").strip()
            if val.startswith("#") and len(val) == 7:
                i[key] = val
    config.save(mut)
    if request.form.get("activate") == "on":
        config.save(lambda c: c.__setitem__("mode", "info"))
    worker.bump_generation()
    return redirect(url_for("info_page"))


@app.post("/draw/preview")
def draw_preview():
    """Render the drawing exactly as the panel will show it, for on-screen proof."""
    img = _decode_data_url(request.get_json(force=True).get("image", ""))
    prepared = render.prepare_image(img, config.get()["display"])
    buf = io.BytesIO()
    prepared.save(buf, format="PNG")
    buf.seek(0)
    return send_file(buf, mimetype="image/png")


@app.post("/draw/push")
def draw_push():
    img = _decode_data_url(request.get_json(force=True).get("image", ""))
    name = _save_pil(img, "draw")
    config.save(lambda c: (c["draw"].__setitem__("last", name),
                           c.__setitem__("mode", "draw")))
    _gc_uploads()
    prepared = render.prepare_image(img, config.get()["display"])
    worker.request_show(prepared, f"draw:{name}")
    return jsonify(ok=True)


@app.post("/settings/save")
def settings_save():
    def mut(c):
        d = c["display"]
        rot = int(request.form.get("rotation", 0))
        d["rotation"] = rot if rot in (0, 90, 180, 270) else 0
        d["saturation"] = max(0.0, min(1.0, float(request.form.get("saturation", 0.5))))
        d["fit"] = "contain" if request.form.get("fit") == "contain" else "cover"
        bg = request.form.get("background", "").strip()
        if bg.startswith("#") and len(bg) == 7:
            d["background"] = bg
        d["auto_enhance"] = request.form.get("auto_enhance") == "on"
    config.save(mut)
    worker.bump_generation()
    return redirect(url_for("settings_page"))


@app.post("/display/refresh")
def display_refresh():
    worker.bump_generation()
    return redirect(request.form.get("next") or url_for("dashboard"))


@app.post("/display/clear")
def display_clear():
    white = Image.new("RGB", tuple(worker.controller().resolution), (255, 255, 255))
    worker.request_show(white, "clear")
    return redirect(request.form.get("next") or url_for("dashboard"))


# --------------------------------------------------------------------------- #
# api / assets
# --------------------------------------------------------------------------- #
@app.get("/api/state")
def api_state():
    return jsonify(worker.status())


@app.get("/api/preview.png")
def api_preview():
    from display import PREVIEW_PATH
    if os.path.exists(PREVIEW_PATH):
        return send_file(PREVIEW_PATH, mimetype="image/png",
                         max_age=0, last_modified=os.path.getmtime(PREVIEW_PATH))
    buf = io.BytesIO()
    render.placeholder("Nothing shown yet").save(buf, format="PNG")
    buf.seek(0)
    return send_file(buf, mimetype="image/png")


@app.get("/uploads/<path:name>")
def uploads(name):
    return send_from_directory(config.UPLOAD_DIR, name, max_age=3600)


def _decode_data_url(data_url: str) -> Image.Image:
    if "," in data_url:
        data_url = data_url.split(",", 1)[1]
    try:
        raw = base64.b64decode(data_url)
        return Image.open(io.BytesIO(raw)).convert("RGB")
    except Exception:  # noqa: BLE001
        abort(400, "bad image data")


@app.errorhandler(400)
@app.errorhandler(404)
@app.errorhandler(413)
def _bad_request(err):
    code = getattr(err, "code", 400)
    return render_template("error.html", message=str(err),
                           cfg=config.get(), status=worker.status()), code


worker.start()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8080)), debug=True)

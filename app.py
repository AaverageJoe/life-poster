"""Life Poster - local web control panel for an Inky Impression 7.3" display."""
from __future__ import annotations

import base64
import io
import os
import time
import uuid

from flask import (Flask, abort, jsonify, redirect, render_template, request,
                   send_file, send_from_directory, url_for)
from PIL import Image, ImageOps
from werkzeug.utils import secure_filename

import buttons
import config
import render
import worker

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 24 * 1024 * 1024  # 24 MB uploads

ALLOWED = {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp"}
MODES = config.MODES
# Stored originals are capped to this on the long edge. A Pi Zero W runs out of
# RAM decoding/resizing full 12-24 MP phone photos while inky also holds buffers.
MAX_STORE_PX = 1600
ROTATIONS = (0, 90, 180, 270)


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #
def _shrink_in_place(path: str) -> None:
    try:
        with Image.open(path) as im:
            im.draft("RGB", (MAX_STORE_PX, MAX_STORE_PX))  # cheap JPEG downscale
            im = ImageOps.exif_transpose(im)
            if max(im.size) > MAX_STORE_PX:
                im.thumbnail((MAX_STORE_PX, MAX_STORE_PX), Image.LANCZOS)
            im.convert("RGB").save(path, format="JPEG", quality=88)
    except Exception as exc:  # noqa: BLE001
        print(f"[app] shrink failed for {path}: {exc!r}")


def _save_upload(file_storage, prefix: str) -> str:
    ext = os.path.splitext(file_storage.filename or "")[1].lower()
    if ext not in ALLOWED:
        abort(400, f"Unsupported file type: {ext or '?'}")
    name = secure_filename(f"{prefix}-{int(time.time())}-{uuid.uuid4().hex[:8]}.jpg")
    path = os.path.join(config.UPLOAD_DIR, name)
    file_storage.save(path)
    try:
        with Image.open(path) as probe:
            probe.verify()
    except Exception:  # noqa: BLE001
        os.remove(path)
        abort(400, "That file is not a readable image")
    _shrink_in_place(path)
    return name


def _save_pil(img: Image.Image, prefix: str) -> str:
    name = f"{prefix}-{int(time.time())}-{uuid.uuid4().hex[:8]}.png"
    img.convert("RGB").save(os.path.join(config.UPLOAD_DIR, name))
    return name


def _uploads_in_use() -> set[str]:
    cfg = config.get()
    used = {e["name"] for e in cfg["poster"]["playlist"]}
    used.add(cfg["control"].get("current"))
    used.add(cfg["control"].get("pending"))
    used.add(cfg["draw"].get("last"))
    return {u for u in used if u}


def _gc_uploads():
    keep = _uploads_in_use()
    for fn in os.listdir(config.UPLOAD_DIR):
        if fn not in keep:
            try:
                os.remove(os.path.join(config.UPLOAD_DIR, fn))
            except OSError:
                pass


def _render_png(img: Image.Image, display_cfg: dict) -> "io.BytesIO":
    buf = io.BytesIO()
    render.prepare_image(img, display_cfg).save(buf, format="PNG")
    buf.seek(0)
    return buf


def _decode_data_url(data_url: str) -> Image.Image:
    if "," in data_url:
        data_url = data_url.split(",", 1)[1]
    try:
        raw = base64.b64decode(data_url)
        return Image.open(io.BytesIO(raw)).convert("RGB")
    except Exception:  # noqa: BLE001
        abort(400, "bad image data")


# --------------------------------------------------------------------------- #
# pages
# --------------------------------------------------------------------------- #
def _page(name):
    return render_template(name, cfg=config.get(), status=worker.status(),
                           rotations=ROTATIONS)


@app.route("/")
def dashboard():
    return _page("dashboard.html")


@app.route("/poster")
def poster_page():
    return _page("poster.html")


@app.route("/control")
def control_page():
    return _page("control.html")


@app.route("/info")
def info_page():
    return _page("info.html")


@app.route("/draw")
def draw_page():
    return _page("draw.html")


@app.route("/settings")
def settings_page():
    return _page("settings.html")


# --------------------------------------------------------------------------- #
# mode + display actions
# --------------------------------------------------------------------------- #
@app.post("/mode")
def set_mode():
    mode = request.form.get("mode", "")
    if mode not in MODES:
        abort(400, "unknown mode")
    config.save(lambda c: c.__setitem__("mode", mode))
    worker.bump_generation()
    return redirect(request.form.get("next") or url_for("dashboard"))


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
# poster mode
# --------------------------------------------------------------------------- #
@app.post("/poster/upload")
def poster_upload():
    files = request.files.getlist("images")
    default_rot = int(config.get()["display"]["rotation"])
    added = [{"name": _save_upload(f, "poster"), "rotation": default_rot, "fit": None}
             for f in files if f and f.filename]
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
            by_name = {e["name"]: e for e in p["playlist"]}
            p["playlist"] = [by_name[n] for n in order if n in by_name]
    config.save(mut)
    if request.form.get("activate") == "on":
        config.save(lambda c: c.__setitem__("mode", "poster"))
    worker.bump_generation()
    return redirect(url_for("poster_page"))


@app.post("/poster/item")
def poster_item():
    """Update one playlist entry's rotation / fit."""
    name = request.form.get("name", "")
    rotation = int(request.form.get("rotation", 0))
    fit = request.form.get("fit", "")

    def mut(c):
        for e in c["poster"]["playlist"]:
            if e["name"] == name:
                e["rotation"] = rotation if rotation in ROTATIONS else 0
                e["fit"] = fit if fit in ("cover", "contain") else None
    config.save(mut)
    worker.bump_generation()
    return redirect(url_for("poster_page"))


@app.post("/poster/show")
def poster_show():
    """Jump the playlist to a specific image and display it now."""
    name = request.form.get("name", "")

    def mut(c):
        names = [e["name"] for e in c["poster"]["playlist"]]
        if name in names:
            c["poster"]["index"] = names.index(name)
            c["mode"] = "poster"
    config.save(mut)
    worker.bump_generation()
    return redirect(url_for("poster_page"))


@app.post("/poster/remove")
def poster_remove():
    name = request.form.get("name", "")
    config.save(lambda c: c["poster"].__setitem__(
        "playlist", [e for e in c["poster"]["playlist"] if e["name"] != name]))
    _gc_uploads()
    worker.bump_generation()
    return redirect(url_for("poster_page"))


# --------------------------------------------------------------------------- #
# control mode  (upload -> preview -> send)
# --------------------------------------------------------------------------- #
@app.post("/control/upload")
def control_upload():
    f = request.files.get("image")
    if not f or not f.filename:
        abort(400, "no image")
    name = _save_upload(f, "control")
    config.save(lambda c: c["control"].__setitem__("pending", name))
    _gc_uploads()
    return redirect(url_for("control_page"))


@app.post("/control/confirm")
def control_confirm():
    cfg = config.get()
    pending = cfg["control"].get("pending")
    if not pending:
        abort(400, "nothing staged")
    config.save(lambda c: (c["control"].__setitem__("current", pending),
                           c["control"].__setitem__("pending", None),
                           c.__setitem__("mode", "control")))
    _gc_uploads()
    worker.bump_generation()
    return redirect(url_for("control_page"))


@app.post("/control/discard")
def control_discard():
    config.save(lambda c: c["control"].__setitem__("pending", None))
    _gc_uploads()
    return redirect(url_for("control_page"))


# --------------------------------------------------------------------------- #
# info mode
# --------------------------------------------------------------------------- #
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


# --------------------------------------------------------------------------- #
# draw mode
# --------------------------------------------------------------------------- #
@app.post("/draw/preview")
def draw_preview():
    img = _decode_data_url(request.get_json(force=True).get("image", ""))
    return send_file(_render_png(img, config.get()["display"]), mimetype="image/png")


@app.post("/draw/push")
def draw_push():
    img = _decode_data_url(request.get_json(force=True).get("image", ""))
    name = _save_pil(img, "draw")
    config.save(lambda c: (c["draw"].__setitem__("last", name),
                           c.__setitem__("mode", "draw")))
    _gc_uploads()
    worker.request_show(render.prepare_image(img, config.get()["display"]), f"draw:{name}")
    return jsonify(ok=True)


# --------------------------------------------------------------------------- #
# settings
# --------------------------------------------------------------------------- #
@app.post("/settings/save")
def settings_save():
    def mut(c):
        d = c["display"]
        rot = int(request.form.get("rotation", 0))
        d["rotation"] = rot if rot in ROTATIONS else 0
        d["saturation"] = max(0.0, min(1.0, float(request.form.get("saturation", 0.5))))
        d["fit"] = "contain" if request.form.get("fit") == "contain" else "cover"
        bg = request.form.get("background", "").strip()
        if bg.startswith("#") and len(bg) == 7:
            d["background"] = bg
        d["auto_enhance"] = request.form.get("auto_enhance") == "on"

        bm = request.form.get("boot_mode", "poster")
        c["boot_mode"] = bm if bm in ("last", *MODES) else "poster"

        c["buttons"]["enabled"] = request.form.get("buttons_enabled") == "on"

        s = c["schedule"]
        s["sleep_enabled"] = request.form.get("sleep_enabled") == "on"
        for key in ("sleep_start", "sleep_end"):
            v = request.form.get(key, "").strip()
            if len(v) == 5 and v[2] == ":":
                s[key] = v
    config.save(mut)
    worker.bump_generation()
    return redirect(url_for("settings_page"))


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


@app.get("/api/render/<path:name>")
def api_render(name):
    """800x480 proof of how `name` will look with the given rotation/fit."""
    path = os.path.join(config.UPLOAD_DIR, secure_filename(name))
    if not os.path.exists(path):
        abort(404, "no such image")
    d = dict(config.get()["display"])
    try:
        rot = int(request.args.get("rotation", d["rotation"]))
        d["rotation"] = rot if rot in ROTATIONS else 0
    except ValueError:
        pass
    if request.args.get("fit") in ("cover", "contain"):
        d["fit"] = request.args["fit"]
    with Image.open(path) as im:
        return send_file(_render_png(im, d), mimetype="image/png", max_age=0)


@app.get("/uploads/<path:name>")
def uploads(name):
    return send_from_directory(config.UPLOAD_DIR, name, max_age=3600)


@app.errorhandler(400)
@app.errorhandler(404)
@app.errorhandler(413)
def _bad_request(err):
    code = getattr(err, "code", 400)
    return render_template("error.html", message=str(err),
                           cfg=config.get(), status=worker.status()), code


# --------------------------------------------------------------------------- #
# startup: honour boot_mode, then start the worker
# --------------------------------------------------------------------------- #
def _apply_boot_mode():
    bm = config.get().get("boot_mode", "poster")
    if bm != "last":
        config.save(lambda c: c.__setitem__("mode", bm))
        # a staged control upload shouldn't linger across reboots
        config.save(lambda c: c["control"].__setitem__("pending", None))


_apply_boot_mode()
worker.start()
buttons.start()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8080)), debug=True)

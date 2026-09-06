"""Image preparation and Info-mode rendering.

Everything here returns a plain RGB PIL image sized exactly PANEL_W x PANEL_H,
ready to hand to the display layer (which does the 6/7-colour dithering).
"""
from __future__ import annotations

import datetime as _dt
import os

from PIL import Image, ImageDraw, ImageEnhance, ImageFont, ImageOps

import config

_FONT_DIRS = [
    "/usr/share/fonts/truetype/dejavu",
    "/usr/share/fonts/truetype/freefont",
    "/Library/Fonts",
    "C:/Windows/Fonts",
]


def _font(names, size):
    for base in _FONT_DIRS:
        for name in names:
            path = os.path.join(base, name)
            if os.path.exists(path):
                try:
                    return ImageFont.truetype(path, size)
                except OSError:
                    pass
    return ImageFont.load_default()


def font_bold(size):
    return _font(["DejaVuSans-Bold.ttf", "FreeSansBold.ttf", "arialbd.ttf"], size)


def font_regular(size):
    return _font(["DejaVuSans.ttf", "FreeSans.ttf", "arial.ttf"], size)


def _hex(value, fallback=(255, 255, 255)):
    try:
        value = value.lstrip("#")
        return tuple(int(value[i:i + 2], 16) for i in (0, 2, 4))
    except (ValueError, AttributeError, IndexError):
        return fallback


def prepare_image(src: Image.Image, display_cfg: dict) -> Image.Image:
    """Fit `src` onto the panel per the display settings."""
    img = ImageOps.exif_transpose(src).convert("RGB")

    rotation = int(display_cfg.get("rotation", 0)) % 360
    if rotation:
        # expand so nothing is clipped; we re-fit to the panel afterwards
        img = img.rotate(-rotation, expand=True, fillcolor=_hex(display_cfg.get("background")))

    if display_cfg.get("auto_enhance"):
        img = ImageEnhance.Contrast(img).enhance(1.12)
        img = ImageEnhance.Sharpness(img).enhance(1.15)
        img = ImageEnhance.Color(img).enhance(1.05)

    target = (config.PANEL_W, config.PANEL_H)
    fit = display_cfg.get("fit", "cover")
    if fit == "contain":
        canvas = Image.new("RGB", target, _hex(display_cfg.get("background")))
        fitted = ImageOps.contain(img, target, Image.LANCZOS)
        canvas.paste(fitted, ((target[0] - fitted.width) // 2,
                              (target[1] - fitted.height) // 2))
        return canvas
    # cover (default): fill the panel, centre-crop the overflow
    return ImageOps.fit(img, target, Image.LANCZOS, centering=(0.5, 0.5))


def info_key(info_cfg: dict, now: _dt.datetime | None = None) -> str:
    """A string that changes only when the Info screen needs a redraw."""
    now = now or _dt.datetime.now()
    bucket = max(1, int(info_cfg.get("refresh_minutes", 10)))
    if info_cfg.get("show_seconds"):
        stamp = now.strftime("%Y%m%d%H%M%S")
    else:
        minutes = (now.hour * 60 + now.minute) // bucket
        stamp = f"{now.strftime('%Y%m%d')}-{minutes}"
    return "|".join([stamp, str(info_cfg.get("headline", "")),
                     str(info_cfg.get("time_format")), str(info_cfg.get("bg")),
                     str(info_cfg.get("fg")), str(info_cfg.get("accent"))])


def render_info(info_cfg: dict, now: _dt.datetime | None = None) -> Image.Image:
    now = now or _dt.datetime.now()
    bg = _hex(info_cfg.get("bg"), (255, 255, 255))
    fg = _hex(info_cfg.get("fg"), (0, 0, 0))
    accent = _hex(info_cfg.get("accent"), (212, 0, 26))

    img = Image.new("RGB", (config.PANEL_W, config.PANEL_H), bg)
    d = ImageDraw.Draw(img)

    if info_cfg.get("time_format") == "12h":
        time_str = now.strftime("%I:%M").lstrip("0")
        suffix = now.strftime(" %p")
    else:
        time_str = now.strftime("%H:%M")
        suffix = ""
    if info_cfg.get("show_seconds"):
        time_str += now.strftime(":%S")

    date_str = now.strftime("%A")
    date_sub = now.strftime("%d %B %Y")

    tf = font_bold(200)
    box = d.textbbox((0, 0), time_str, font=tf)
    tw, th = box[2] - box[0], box[3] - box[1]
    tx = (config.PANEL_W - tw) // 2 - box[0]
    ty = 60
    d.text((tx, ty), time_str, font=tf, fill=fg)
    if suffix:
        sf = font_bold(48)
        d.text((tx + tw + 12, ty + th - 54), suffix.strip(), font=sf, fill=accent)

    df = font_bold(60)
    dbox = d.textbbox((0, 0), date_str, font=df)
    d.text(((config.PANEL_W - (dbox[2] - dbox[0])) // 2 - dbox[0], 300),
           date_str, font=df, fill=accent)

    sf = font_regular(38)
    sbox = d.textbbox((0, 0), date_sub, font=sf)
    d.text(((config.PANEL_W - (sbox[2] - sbox[0])) // 2 - sbox[0], 372),
           date_sub, font=sf, fill=fg)

    headline = (info_cfg.get("headline") or "").strip()
    if headline:
        hf = font_regular(30)
        hbox = d.textbbox((0, 0), headline, font=hf)
        hw = hbox[2] - hbox[0]
        if hw > config.PANEL_W - 40:
            hf = font_regular(24)
            hbox = d.textbbox((0, 0), headline, font=hf)
            hw = hbox[2] - hbox[0]
        d.rectangle([0, 430, config.PANEL_W, config.PANEL_H], fill=accent)
        d.text(((config.PANEL_W - hw) // 2 - hbox[0], 438), headline,
               font=hf, fill=bg)

    return img


def placeholder(text: str) -> Image.Image:
    img = Image.new("RGB", (config.PANEL_W, config.PANEL_H), (255, 255, 255))
    d = ImageDraw.Draw(img)
    f = font_bold(44)
    box = d.textbbox((0, 0), text, font=f)
    d.text(((config.PANEL_W - (box[2] - box[0])) // 2, (config.PANEL_H - 44) // 2),
           text, font=f, fill=(0, 0, 0))
    return img

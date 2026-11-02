"""Карточка статистики для «Поделиться» — порт ShareCardRenderer (QPainter) с десктопа на Pillow.

Раскладка та же: проектная сетка 3840x2160, один коэффициент масштаба, поэтому карточка
выглядит одинаково при любом размере холста. На телефоне по умолчанию рисуем 2560x1440 (2K):
это резко и не съедает память (4K = 33 МБ на каждый слой).

Данные собирает collect_share_data() — тот же набор полей, что и на десктопе
(профиль, панели пулов с тремя счётчиками и полосами гаранта, состав стандартного пула,
«Все выпадения S»).
"""
import colorsys
import math
import random
import re
from datetime import datetime

import numpy as np
from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont

import imgutil
import nte_core as C

LANCZOS = imgutil.LANCZOS
DW, DH, MARGIN = 3840, 2160, 110
SHARE_SIZE = (2560, 1440)
GOLD = (255, 215, 64)
WHITE = (255, 255, 255)
MUTED = (255, 255, 255, 185)
CARD_TITLES = ("Всего круток", "Всего S", "Средний гарант (S)")
CARD_ACCENTS = ("#8ab4ff", "#ffd740", "#7be0a8")
PANEL_TOP, PANEL_H, PANEL_GAP, PANEL_PAD = 320, 1120, 50, 50


# ----------------------------------------------------------------------------
# цвета
# ----------------------------------------------------------------------------
def _rgb(c):
    if isinstance(c, (tuple, list)):
        return tuple(int(v) for v in c[:3])
    c = str(c).lstrip("#")
    return int(c[0:2], 16), int(c[2:4], 16), int(c[4:6], 16)


def _rgba(c, a=255):
    if isinstance(c, (tuple, list)) and len(c) == 4:
        return tuple(int(v) for v in c)
    return (*_rgb(c), a)


def pity_rgb(pulls, hard=C.PITY_CHAR_HARD):
    """1 крутка — зелёный, середина — жёлтый/оранжевый, hard — красный (как pity_color на десктопе)."""
    t = 0.0 if hard <= 1 else (pulls - 1) / (hard - 1)
    t = min(max(t, 0.0), 1.0)
    r, g, b = colorsys.hsv_to_rgb((1.0 - t) / 3.0, 0.80, 0.95)
    return int(r * 255), int(g * 255), int(b * 255)


def _alpha_lut(a):
    return [v * a // 255 for v in range(256)]


# ----------------------------------------------------------------------------
# рендерер
# ----------------------------------------------------------------------------
class ShareRenderer:
    def __init__(self, data, icon_path, font_regular=None, font_bold=None, size=SHARE_SIZE):
        self.data = data or {}
        self.icon_path = icon_path                      # (name, aliases, rarity) -> путь к файлу или None
        self.fr, self.fb = font_regular, font_bold
        self.W = max(640, int(size[0]))
        self.k = self.W / DW
        self.H = round(DH * self.k)
        self.img = Image.new("RGB", (self.W, self.H), (8, 10, 22))
        self._fonts, self._masks = {}, {}
        self._pools_bottom = PANEL_TOP + PANEL_H

    # ---------- главный метод ----------
    def render(self) -> Image.Image:
        self._background()
        self._header()
        self._pools()
        self._recent()
        self._footer()
        return self.img

    # ---------- низкоуровневые примитивы ----------
    def _px(self, rect):
        x, y, w, h = rect
        k = self.k
        x0, y0, x1, y1 = round(x * k), round(y * k), round((x + w) * k), round((y + h) * k)
        return x0, y0, max(1, x1 - x0), max(1, y1 - y0)

    def _paste(self, src, mask, x, y, alpha=255):
        """src: RGB-картинка или цвет (r, g, b); mask: 'L'. Вставка с обрезкой по холсту."""
        w, h = mask.size
        x0, y0, x1, y1 = max(0, x), max(0, y), min(self.W, x + w), min(self.H, y + h)
        if x1 <= x0 or y1 <= y0 or alpha <= 0:
            return
        if (x0, y0, x1, y1) != (x, y, x + w, y + h):
            box = (x0 - x, y0 - y, x1 - x, y1 - y)
            mask = mask.crop(box)
            if isinstance(src, Image.Image):
                src = src.crop(box)
        if alpha < 255:
            mask = mask.point(_alpha_lut(alpha))
        self.img.paste(src, (x0, y0, x1, y1), mask)

    def _paste_color(self, mask, x, y, rgba):
        r, g, b, a = _rgba(rgba)
        self._paste((r, g, b), mask, x, y, a)

    def _rr_mask(self, w, h, r, ss=3):
        key = ("f", w, h, round(r, 1))
        if key not in self._masks:
            m = Image.new("L", (w * ss, h * ss), 0)
            ImageDraw.Draw(m).rounded_rectangle((0, 0, w * ss - 1, h * ss - 1), radius=r * ss, fill=255)
            self._masks[key] = m.resize((w, h), LANCZOS)
        return self._masks[key]

    def _stroke_mask(self, w, h, r, width, ss=3):
        """Обводка по контуру прямоугольника (линия идёт по краю, как перо QPainter).
        Возвращает (маска, отступ): маска больше прямоугольника на pad с каждой стороны."""
        pad = int(math.ceil(width / 2.0)) + 2
        key = ("s", w, h, round(r, 1), round(width, 1))
        if key not in self._masks:
            half = width / 2.0
            m = Image.new("L", ((w + 2 * pad) * ss, (h + 2 * pad) * ss), 0)
            box = ((pad - half) * ss, (pad - half) * ss,
                   (pad + w + half) * ss - 1, (pad + h + half) * ss - 1)
            ImageDraw.Draw(m).rounded_rectangle(box, radius=(r + half) * ss, outline=255,
                                                width=max(1, round(width * ss)))
            self._masks[key] = m.resize((w + 2 * pad, h + 2 * pad), LANCZOS)
        return self._masks[key], pad

    def _fill_rr(self, rect, radius, rgba):
        x, y, w, h = self._px(rect)
        self._paste_color(self._rr_mask(w, h, radius * self.k), x, y, rgba)

    def _stroke_rr(self, rect, radius, width, rgba, blur=0.0):
        x, y, w, h = self._px(rect)
        m, pad = self._stroke_mask(w, h, radius * self.k, max(1.0, width * self.k))
        if blur > 0:
            m = m.filter(ImageFilter.GaussianBlur(blur * self.k))
        self._paste_color(m, x - pad, y - pad, rgba)

    def _glow_rr(self, rect, radius, color, width, strength=1.0):
        """Мягкое свечение вокруг рамки: размытая широкая обводка + обводка поуже."""
        c = _rgb(color)
        self._stroke_rr(rect, radius, width * 7, (*c, int(52 * strength)), blur=width * 2.6)
        self._stroke_rr(rect, radius, width * 3, (*c, int(70 * strength)), blur=width * 1.1)

    def _lin_gradient(self, w, h, stops, p0=None, p1=None):
        """stops: [(позиция, (r, g, b, a)), ...]; QLinearGradient от p0 к p1 (по умолчанию —
        левый верх -> правый низ). Возвращает (RGB-картинка, маска альфа 'L')."""
        p0 = p0 or (0.0, 0.0)
        p1 = p1 or (float(w), float(h))
        ys, xs = np.mgrid[0:h, 0:w].astype(np.float32)
        vx, vy = p1[0] - p0[0], p1[1] - p0[1]
        d = max(1e-6, vx * vx + vy * vy)
        t = ((xs - p0[0]) * vx + (ys - p0[1]) * vy) / d
        pos = [s[0] for s in stops]
        chans = [np.interp(t, pos, [s[1][i] for s in stops]) for i in range(4)]
        rgb = np.stack(chans[:3], axis=-1).clip(0, 255).astype(np.uint8)
        alpha = chans[3].clip(0, 255).astype(np.uint8)
        return Image.fromarray(rgb, "RGB"), Image.fromarray(alpha, "L")

    # ---------- шрифты и текст ----------
    def _font(self, px, bold=False):
        size = max(1, int(round(px * self.k)))
        key = (size, bool(bold))
        if key not in self._fonts:
            path = self.fb if bold else self.fr
            try:
                self._fonts[key] = ImageFont.truetype(path, size) if path else ImageFont.load_default()
            except OSError:
                self._fonts[key] = ImageFont.load_default()
        return self._fonts[key]

    @staticmethod
    def _elide(font, text, max_w):
        if font.getlength(text) <= max_w:
            return text
        while text and font.getlength(text + "…") > max_w:
            text = text[:-1]
        return text + "…" if text else ""

    def _text(self, rect, text, px, color, bold=False, align="l", shadow=True, elide=True):
        x, y, w, h = rect
        k = self.k
        font = self._font(px, bold)
        text = str(text)
        if not text:
            return
        if elide:
            text = self._elide(font, text, w * k)
        anchor = {"l": "lm", "c": "mm", "r": "rm"}[align]
        ax = {"l": x, "c": x + w / 2.0, "r": x + w}[align] * k
        ay = (y + h / 2.0) * k
        bb = font.getbbox(text, anchor=anchor)
        pad = 3
        mw, mh = bb[2] - bb[0] + 2 * pad, bb[3] - bb[1] + 2 * pad
        m = Image.new("L", (mw, mh), 0)
        ImageDraw.Draw(m).text((pad - bb[0], pad - bb[1]), text, font=font, fill=255, anchor=anchor)
        ox, oy = round(ax + bb[0]) - pad, round(ay + bb[1]) - pad
        if shadow:
            self._paste_color(m, ox + round(px * 0.04 * k), oy + round(px * 0.05 * k), (0, 0, 0, 170))
        self._paste_color(m, ox, oy, _rgba(color))

    def _text_width(self, text, px, bold=False):
        return self._font(px, bold).getlength(str(text)) / self.k

    # ---------- стеклянная панель ----------
    def _glass(self, rect, radius=44, depth=1.0, glow=None):
        k = self.k
        x, y, w, h = self._px(rect)
        r = radius * k
        # мягкая тень
        pad = int(60 * k * depth) + 2
        sh = Image.new("L", (w + 2 * pad, h + 2 * pad), 0)
        dy = int(14 * depth * k)
        ImageDraw.Draw(sh).rounded_rectangle((pad, pad + dy, pad + w, pad + h + dy), radius=r, fill=255)
        sh = sh.filter(ImageFilter.GaussianBlur(max(1.0, 22 * k * depth)))
        self._paste_color(sh, x - pad, y - pad, (0, 0, 0, 120))
        base = self._rr_mask(w, h, r)
        self._paste_color(base, x, y, (10, 13, 28, 150))
        self._paste_color(base, x, y, (255, 255, 255, 26))
        _rgb_img, sheen_a = self._lin_gradient(
            w, h, [(0.0, (255, 255, 255, 56)), (0.4, (255, 255, 255, 10)), (1.0, (255, 255, 255, 0))])
        self._paste_color(ImageChops.multiply(base, sheen_a), x, y, (255, 255, 255, 255))
        if glow is not None:
            self._glow_rr(rect, radius, glow, 2.5 * 1.0)
        self._stroke_rr(rect, radius, 2.5, (255, 255, 255, 80))

    # ---------- картинки ----------
    def _cover(self, img, tw, th):
        """«cover»: пропорции сохраняются, лишнее обрезается по центру."""
        s = max(tw / img.width, th / img.height)
        nw, nh = max(tw, round(img.width * s)), max(th, round(img.height * s))
        img = img.resize((nw, nh), LANCZOS)
        left, top = (nw - tw) // 2, (nh - th) // 2
        return img.crop((left, top, left + tw, top + th))

    def _icon(self, rect, name, rarity, aliases=(), dim=False, glow=True):
        """Миниатюра персонажа/дуги: скругление, блик и светящаяся рамка цвета ранга."""
        x, y, s = rect[0], rect[1], rect[2]
        k = self.k
        X, Y, Z, _h = self._px((x, y, s, s))
        radius = s * 0.22
        color = _rgb(C.RARITY_COLORS.get(rarity, C.RARITY_COLORS[3]))
        bw = max(3.0, s * 0.03)
        inset = (x + bw / 2, y + bw / 2, s - bw, s - bw)
        if glow and not dim:
            self._glow_rr(inset, radius - bw / 2, color, bw)
        layer = Image.new("RGBA", (Z, Z), (20, 23, 38, 235))
        src = None
        try:
            path = self.icon_path(name, tuple(aliases or ()), rarity) if (name or aliases) else None
            src = imgutil.load_pil(path) if path else None
        except Exception:  # noqa: BLE001
            src = None
        if src is not None:
            art = self._cover(src, Z, Z)
            if dim:
                a = art.getchannel("A").point(_alpha_lut(82))      # 0.32
                art.putalpha(a)
            layer.alpha_composite(art)
        else:
            layer.alpha_composite(Image.new("RGBA", (Z, Z), (*color, 70)))
        _rgb_img, sheen_a = self._lin_gradient(
            Z, Z, [(0.0, (255, 255, 255, 70)), (0.45, (255, 255, 255, 18)), (1.0, (255, 255, 255, 0))])
        sheen = Image.new("RGBA", (Z, Z), (255, 255, 255, 0))
        sheen.putalpha(sheen_a)
        layer.alpha_composite(sheen)
        layer.putalpha(ImageChops.multiply(layer.getchannel("A"), self._rr_mask(Z, Z, radius * k)))
        self._paste(layer.convert("RGB"), layer.getchannel("A"), X, Y)
        if src is None:
            label = C._initials(name or next(iter(aliases or ()), ""))        # noqa: SLF001
            self._text((x, y, s, s), label, s * 0.38, (*color, 255), True, "c", shadow=False)
        self._stroke_rr(inset, radius - bw / 2, bw, (*color, 110 if dim else 235))

    # ---------- логотип ----------
    def _logo(self, x, y, s):
        k, ss = self.k, 3
        X, Y, S, _h = self._px((x, y, s, s))
        pad = int(S * 0.3)
        A = S + 2 * pad

        def hexagon(scale):
            c, r = A * ss / 2.0, S * ss / 2.0 * scale
            return [(c + r * math.cos(math.radians(-90 + 60 * i)), c + r * math.sin(math.radians(-90 + 60 * i)))
                    for i in range(6)]

        def outline(pts, width):
            m = Image.new("L", (A * ss, A * ss), 0)
            ImageDraw.Draw(m).line(pts + [pts[0], pts[1]], fill=255, width=max(1, int(width * k * ss)),
                                   joint="curve")
            return m.resize((A, A), LANCZOS)

        outer = hexagon(1.0)
        glow = outline(outer, 16).filter(ImageFilter.GaussianBlur(max(1.0, 7 * k)))
        self._paste_color(glow, X - pad, Y - pad, (150, 110, 255, 120))
        body = Image.new("L", (A * ss, A * ss), 0)
        ImageDraw.Draw(body).polygon(outer, fill=255)
        body = body.resize((A, A), LANCZOS)
        grad, _a = self._lin_gradient(A, A, [(0.0, (130, 90, 255, 255)), (1.0, (0, 200, 230, 255))],
                                      p0=(pad, pad), p1=(pad + S, pad + S))
        self._paste(grad, body, X - pad, Y - pad)
        self._paste_color(outline(outer, 5), X - pad, Y - pad, (255, 255, 255, 210))
        self._paste_color(outline(hexagon(0.78), 2.5), X - pad, Y - pad, (255, 255, 255, 90))
        self._text((x, y, s, s), "NTE", s / 2 * 0.62, WHITE, True, "c")

    # ---------- фон: тёмный город ----------
    def _background(self):
        W, H, k = self.W, self.H, self.k
        lw, lh = max(64, W // 4), max(36, H // 4)                 # гладкие слои считаем в малом размере
        ys = np.linspace(0, 1, lh, dtype=np.float32)[:, None]
        stops = [(0.0, (9, 11, 30)), (0.45, (26, 17, 60)), (0.80, (18, 24, 66)), (1.0, (6, 20, 36))]
        pos = [s[0] for s in stops]
        col = np.stack([np.interp(ys[:, 0], pos, [s[1][i] for s in stops]) for i in range(3)], axis=-1)
        arr = np.repeat(col[:, None, :], lw, axis=1).astype(np.float32)
        gy, gx = np.mgrid[0:lh, 0:lw].astype(np.float32)
        gx, gy = gx / lw * DW, gy / lh * DH                       # координаты проектной сетки
        for fx, fy, fr, color in ((0.10, 0.10, 0.50, (120, 80, 255, 100)),
                                  (0.92, 0.28, 0.42, (255, 190, 60, 60)),
                                  (0.50, 1.00, 0.55, (0, 170, 200, 80))):
            dist = np.sqrt((gx - DW * fx) ** 2 + (gy - DH * fy) ** 2) / (max(DW, DH) * fr)
            a = (np.clip(1.0 - dist, 0, 1) * color[3] / 255.0)[..., None]
            arr = arr * (1 - a) + np.array(color[:3], dtype=np.float32) * a
        self.img = Image.fromarray(arr.clip(0, 255).astype(np.uint8), "RGB").resize((W, H), Image.BICUBIC)
        d = ImageDraw.Draw(self.img, "RGBA")
        rnd = random.Random(20261022)                             # то же зерно, что на десктопе
        for _ in range(260):                                      # далёкие огни / звёзды
            a = rnd.randint(30, 120)
            r = rnd.uniform(1.2, 3.4) * k
            cx, cy = rnd.uniform(0, DW) * k, rnd.uniform(0, DH * 0.55) * k
            d.ellipse((cx - r, cy - r, cx + r, cy + r), fill=(255, 255, 255, a))
        layers = ((300, 820, (30, 28, 70), 90, 220, 0),
                  (240, 700, (20, 20, 52), 80, 200, 70),
                  (160, 520, (12, 13, 34), 70, 180, 110))
        for hmin, hmax, color, wmin, wmax, win_alpha in layers:
            x = -40
            while x < DW:
                bw, bh = rnd.randint(wmin, wmax), rnd.randint(hmin, hmax)
                d.rectangle((x * k, (DH - bh) * k, (x + bw) * k, H), fill=(*color, 255))
                if rnd.random() < 0.25:                           # антенна
                    d.rectangle(((x + bw / 2 - 3) * k, (DH - bh - 70) * k, (x + bw / 2 + 3) * k,
                                 (DH - bh) * k), fill=(*color, 255))
                if win_alpha:
                    for row in range(int(bh // 46)):
                        for cl in range(int(bw // 34)):
                            if rnd.random() < 0.18:
                                warm = rnd.random() < 0.6
                                wc = (255, 200, 110, win_alpha) if warm else (110, 220, 255, win_alpha)
                                wx, wy = x + 14 + cl * 34, DH - bh + 20 + row * 46
                                d.rectangle((wx * k, wy * k, (wx + 14) * k, (wy + 20) * k), fill=wc)
                x += bw + rnd.randint(0, 14)
        # виньетка (малый размер -> растянуть) и лёгкое затемнение под текст
        dist = np.sqrt((gx - DW / 2) ** 2 + (gy - DH / 2) ** 2) / (DW * 0.72)
        vig = (np.clip((dist - 0.55) / 0.45, 0, 1) * 150).astype(np.uint8)
        vig = Image.fromarray(vig, "L").resize((W, H), Image.BICUBIC)
        self._paste((0, 0, 0), vig, 0, 0)
        self._paste((6, 8, 20), Image.new("L", (W, H), 255), 0, 0, 70)

    # ---------- шапка ----------
    def _header(self):
        M = MARGIN
        self._logo(M, 70, 190)
        tx = M + 190 + 50
        self._text((tx, 62, 2000, 124), "Статистика круток", 108, WHITE, True)
        self._text((tx, 188, 2200, 64), "Neverness to Everness", 42, MUTED)
        profile = self.data.get("profile") or ""
        if profile:
            text = f"Профиль: {profile}"
            w = min(1500.0, self._text_width(text, 60, True) + 100)
            pill = (DW - M - w, 74, w, 108)
            self._glass(pill, radius=54, depth=0.5, glow=GOLD)
            self._text(pill, text, 60, GOLD, True, "c")

    # ---------- панели пулов ----------
    def _pools(self):
        pools = self.data.get("pools") or []
        if not pools:
            return
        n = len(pools)
        pw = (DW - 2 * MARGIN - PANEL_GAP * (n - 1)) / n
        ph = PANEL_H if (n > 1 or any(p.get("roster") for p in pools)) else 640
        self._pools_bottom = PANEL_TOP + ph
        for i, pool in enumerate(pools):
            self._pool((MARGIN + i * (pw + PANEL_GAP), PANEL_TOP, pw, ph), pool)

    def _pool(self, r, pool):
        accent = _rgb(pool.get("accent", "#8ab4ff"))
        self._glass(r, glow=accent)
        x0, w = r[0] + PANEL_PAD, r[2] - 2 * PANEL_PAD
        top = r[1]
        self._fill_rr((x0, top + 44, 14, 78), 7, (*accent, 255))
        self._text((x0 + 38, top + 34, w - 38, 98), pool.get("title", ""), 66, WHITE, True)
        gap = 24
        bw = (w - 2 * gap) / 3
        for j, (label, value, color) in enumerate(pool.get("stats", [])[:3]):
            br = (x0 + j * (bw + gap), top + 160, bw, 220)
            self._fill_rr(br, 28, (255, 255, 255, 16))
            self._stroke_rr(br, 28, 2, (255, 255, 255, 44))
            self._text((br[0] + 20, br[1] + 18, br[2] - 40, 50), label, 28, MUTED, False, shadow=False)
            self._text((br[0] + 20, br[1] + 72, br[2] - 40, 130), value, 96, _rgba(color), True)
        y = top + 430
        for bar in pool.get("bars", []):
            self._pity_bar(x0, y, w, bar)
            y += 130
        if pool.get("soft_active"):
            self._text((x0, y - 34, w, 44), "Мягкий гарант активен", 30, (255, 169, 77), True)
        section = top + 730
        if pool.get("roster"):
            self._roster(x0, section, w, pool["roster"], wide=r[2] > 2000)

    def _pity_bar(self, x, y, w, bar):
        cur, mx = int(bar.get("cur", 0)), max(1, int(bar.get("max", 1)))
        self._text((x, y, w * 0.62, 50), bar.get("label", ""), 34, WHITE, True)
        self._text((x + w * 0.55, y, w * 0.45, 50), bar.get("right", ""), 30, MUTED, False, "r", shadow=False)
        track = (x, y + 60, w, 34)
        tx, ty, tw, th = self._px(track)
        rad = 17 * self.k
        m = self._rr_mask(tw, th, rad)
        self._paste_color(m, tx, ty, (255, 255, 255, 32))
        if cur > 0:
            fill_w = max(34.0, w * min(1.0, cur / mx))
            fw = max(1, round(fill_w * self.k))
            c0, c1 = np.array(pity_rgb(1, mx), dtype=np.float32), np.array(pity_rgb(cur, mx), dtype=np.float32)
            t = np.linspace(0, 1, fw, dtype=np.float32)[None, :, None]
            row = (c0 * (1 - t) + c1 * t).astype(np.uint8)
            grad = Image.fromarray(np.repeat(row, th, axis=0), "RGB")
            self._paste(grad, self._rr_mask(fw, th, rad), tx, ty)
        soft = bar.get("soft")
        if soft:                                                   # отметка мягкого гаранта
            sx = (x + w * soft / mx) * self.k
            d = ImageDraw.Draw(self.img, "RGBA")
            d.line((sx, ty - 8 * self.k, sx, ty + th + 8 * self.k), fill=(255, 255, 255, 170),
                   width=max(2, round(3 * self.k)))
        self._stroke_rr(track, 17, 2, (255, 255, 255, 70))

    def _roster(self, x, y, w, roster, wide=False):
        self._text((x, y, w, 50), roster.get("s_title", ""), 34, WHITE, True)
        size, per_row = 150.0, 6
        gap = min(40.0, (w - per_row * size) / (per_row - 1))
        for i, (name, count) in enumerate(roster.get("s", [])[:per_row]):
            tx, ty = x + i * (size + gap), y + 62
            self._icon((tx, ty, size), name, 5, (), dim=not count, glow=bool(count))
            label = f"×{count}" if count else "—"
            color = C.RARITY_COLORS[5] if count else "#b4b9cc"
            self._text((tx - 10, ty + size + 4, size + 20, 42), label, 32, _rgba(color), True, "c")
        if wide:                                                   # на всю ширину: состав A справа
            ax = x + w / 2
            self._text((ax, y, w / 2, 50), roster.get("a_text", ""), 34, WHITE, True)
            for i, (name, count) in enumerate(roster.get("a", [])[:per_row]):
                tx, ty = ax + i * (size + gap), y + 62
                self._icon((tx, ty, size), name, 4, (), dim=not count, glow=bool(count))
                self._text((tx - 10, ty + size + 4, size + 20, 42), f"×{count}" if count else "—", 32,
                           _rgba(C.RARITY_COLORS[4] if count else "#b4b9cc"), True, "c")
            return
        self._text((x, y + 282, w, 44), roster.get("a_text", ""), 30, MUTED, False, shadow=False)

    # ---------- все выпадения S ----------
    def _recent(self):
        top = self._pools_bottom + 40
        rect = (MARGIN, top, DW - 2 * MARGIN, 2010 - top)
        self._glass(rect, glow=GOLD)
        self._text((rect[0] + 60, rect[1] + 28, 1700, 84), "Все выпадения S", 58, GOLD, True)
        self._text((rect[0] + rect[2] - 1060, rect[1] + 28, 1000, 84),
                   f"Всего S: {self.data.get('total_s', 0)}", 40, MUTED, False, "r")
        items = self.data.get("recent") or []
        if not items:
            self._text((rect[0], rect[1] + 150, rect[2], 200), "Пока нет выпадений S ранга", 52, MUTED,
                       False, "c")
            return
        avail_w, avail_h = rect[2] - 120, rect[3] - 130 - 30
        tile_w, tile_h = 350.0, 370.0
        best = None
        for cols in range(5, 41):                                  # все выпадения должны поместиться
            q = min(1.0, avail_w / cols / tile_w)
            rows = -(-len(items) // cols)
            if rows * tile_h * q <= avail_h and (best is None or q > best[0]):
                best = (q, cols)
        if best is None:
            best = (min(1.0, avail_w / 40 / tile_w), 40)
        q, cols = best
        slot, th = avail_w / cols, tile_h * q
        rows = -(-len(items) // cols)
        y0 = rect[1] + 120 + max(0.0, (avail_h - rows * th) / 2)
        for i, it in enumerate(items):
            row, col = divmod(i, cols)
            n_in_row = min(cols, len(items) - row * cols)
            start = rect[0] + (rect[2] - slot * n_in_row) / 2
            cx = start + slot * (col + 0.5)
            ty = y0 + row * th
            col_l, col_w = cx - slot / 2 + 4, slot - 8
            if it.get("event"):                                    # золотая плашка ивентовой дуги
                plate = (col_l + 2, ty - 12 * q, col_w - 4, 364 * q)
                pr = 34 * q
                px_, py_, pw_, ph_ = self._px(plate)
                fill, fill_a = self._lin_gradient(
                    pw_, ph_, [(0.0, (255, 193, 7, 80)), (0.55, (140, 100, 30, 70)), (1.0, (255, 160, 0, 40))])
                self._paste(fill, ImageChops.multiply(self._rr_mask(pw_, ph_, pr * self.k), fill_a), px_, py_)
                self._glow_rr(plate, pr, (255, 213, 79), max(1.0, 3.0 * q), 0.9)
                self._stroke_rr(plate, pr, max(2.0, 5 * q), (255, 213, 79, 235))
            self._icon((cx - 100 * q, ty, 200 * q), it["name"], it.get("rarity", 5), it.get("aliases", ()))
            self._text((col_l, ty + 212 * q, col_w, 46 * q), it.get("label") or it["name"], 36 * q, WHITE,
                       True, "c")
            pity = int(it.get("pity", 0))
            self._text((col_l, ty + 258 * q, col_w, 54 * q), f"{pity}", 42 * q,
                       (*pity_rgb(pity, it.get("hard", C.PITY_CHAR_HARD)), 255), True, "c")
            self._text((col_l, ty + 314 * q, col_w, 34 * q), it.get("date", ""), 26 * q, MUTED, False, "c",
                       shadow=False)

    # ---------- подвал ----------
    def _footer(self):
        d = ImageDraw.Draw(self.img, "RGBA")
        k = self.k
        d.line((MARGIN * k, 2042 * k, (DW - MARGIN) * k, 2042 * k), fill=(255, 255, 255, 55),
               width=max(1, round(2 * k)))
        self._logo(MARGIN, 2056, 70)
        self._text((MARGIN + 92, 2054, 1800, 74), self.data.get("watermark") or C.SHARE_WATERMARK, 38,
                   (255, 255, 255, 215), True)


# ----------------------------------------------------------------------------
# сбор данных (аналог collect_share_data с десктопа; виджеты не нужны — только данные)
# ----------------------------------------------------------------------------
def _share_date(text) -> str:
    m = re.match(r"\s*(\d{4})-(\d{2})-(\d{2})", str(text or ""))
    return f"{m.group(3)}.{m.group(2)}.{m.group(1)}" if m else str(text or "")


def _current_entry(tracker, key):
    """Запись текущего баннера из banners.json (как в Tracker.banner_cards) или None."""
    info = tracker.banner_info
    if not info:
        return None
    if key == C.ARC_BANNER:
        return dict(info["arc"]) if info.get("arc") else None
    if key == C.EVENT_BANNER and info.get("name"):
        return {"name": info["name"], "start": info.get("start"), "end": info.get("end"),
                "activated": info.get("activated")}
    return None


def _pool_data(tracker, key, history, hide_std_arcs):
    s = tracker.stats[key]
    values = (s["total"], s["r5"], C.fmt_avg(s["pities"]))
    if key == C.ARC_BANNER and hide_std_arcs:
        n_ev, avg_ev = C.arc_event_only_stats(history)
        values = (s["total"], n_ev, avg_ev)
    pool = {"key": key, "title": C.POOL_TITLES[key], "accent": C.SHARE_POOL_ACCENTS.get(key, "#8ab4ff"),
            "stats": [(title, str(v), color) for title, color, v in zip(CARD_TITLES, CARD_ACCENTS, values)],
            "bars": [], "soft_active": False, "roster": None}
    current = _current_entry(tracker, key)
    if key == C.ARC_BANNER:
        std, ev = s["counter_std"], s["counter_ev"]
        if current:
            lo, hi = C.banner_pull_window(current)
            st = C.arc_period_stats(history, lo, hi)
            std, ev = st["std"], st["ev"]
        for title, cur, target in (("Стандартная S дуга", std, C.PITY_ARC_STD),
                                   ("Ивентовая S дуга", ev, C.PITY_ARC_EVENT)):
            pool["bars"].append({"label": f"{title}: {cur}/{target}", "cur": cur, "max": target, "soft": None,
                                 "right": f"До гаранта: {max(0, target - cur)}"})
    else:
        c = s["counter"]
        if key == C.EVENT_BANNER and current:
            lo, hi = C.banner_pull_window(current)
            c = C.banner_period_stats(history, C.EVENT_BANNER, lo, hi)["pity"]
        c = min(c, C.PITY_CHAR_HARD)
        label = f"До гаранта: {c}/{C.PITY_CHAR_HARD}" if key == C.EVENT_BANNER \
            else f"Текущий: {c}/{C.PITY_CHAR_HARD}"
        pool["bars"].append({"label": label, "cur": c, "max": C.PITY_CHAR_HARD, "soft": C.PITY_CHAR_SOFT,
                             "right": f"До жёсткого гаранта: {max(0, C.PITY_CHAR_HARD - c)}"})
        pool["soft_active"] = c + 1 >= C.PITY_CHAR_SOFT
    if key == C.STANDARD_BANNER and key in C.POOL_ROSTERS:
        counts = C.roster_counts(history, key)
        parts = {}
        for title, rarity, roster in C.POOL_ROSTERS[key]:
            tiles = [(n, counts.get((rarity, C.roster_key(n)), (n, 0))[1]) for n in roster]
            owned = sum(1 for _n, cnt in tiles if cnt)
            parts[rarity] = (f"{title} — получено {owned} из {len(roster)}", tiles)
        pool["roster"] = {"s_title": parts[5][0], "s": parts[5][1], "a_text": parts[4][0], "a": parts[4][1]}
    return pool


def collect_share_data(tracker, only_key=None) -> dict:
    """only_key — ключ пула открытой вкладки «Стафф»; None — карточка со всеми тремя пулами."""
    now = datetime.now()
    history = list(tracker.history)
    prof = tracker.db.active_profile() if tracker.has_profile else None
    keys = [only_key] if only_key in C.POOL_TITLES else list(C.POOL_TITLES)
    try:
        hide_std = tracker.db.get_setting("arc_hide_standard", "0", scoped=True) == "1"
    except Exception:  # noqa: BLE001
        hide_std = False
    pools = [_pool_data(tracker, key, history, hide_std) for key in keys]
    recent, hidden_s = [], 0
    for e in history:                                              # history — «новые сверху»
        if e["kind"] != "main" or e["rarity"] != 5 or e["banner"] not in keys:
            continue
        is_arc = e["banner"] == C.ARC_BANNER
        name = e["name"] or ""
        ev = bool(is_arc and C.arc_kind_by_name(name, e.get("arc_kind") or "") == "event")
        if is_arc and hide_std and not ev:
            hidden_s += 1
            continue
        pity = int((e["ce"] if ev else e["cs"]) if is_arc else e["p5"] or 0)
        recent.append({"name": name, "label": C.arc_short_name(name) if is_arc else name, "rarity": 5,
                       "pity": pity,
                       "hard": (C.PITY_ARC_EVENT if ev else C.PITY_ARC_STD) if is_arc else C.PITY_CHAR_HARD,
                       "date": _share_date(e["date"]), "aliases": tuple(e["aliases"]), "event": ev})
    recent.reverse()                                               # от старых к новым, как в приложении
    return {"profile": prof["name"] if prof else "", "generated": now, "pools": pools, "recent": recent,
            "total_s": sum(tracker.stats[k]["r5"] for k in keys) - hidden_s,
            "watermark": C.SHARE_WATERMARK}


def render_share_card(tracker, out_path: str, font_regular: str = None, font_bold: str = None,
                      only_key: str = None, size=SHARE_SIZE) -> str:
    """Рисует карточку и сохраняет PNG. Возвращает out_path."""
    data = collect_share_data(tracker, only_key)
    img = ShareRenderer(data, tracker.icon, font_regular, font_bold, size).render()
    img.save(out_path, "PNG", optimize=False)
    return out_path

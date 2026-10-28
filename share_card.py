"""Карточка статистики для «Поделиться» (замена ShareCardRenderer на QPainter): Pillow, 1080x1350."""
from PIL import Image, ImageDraw, ImageFont

import nte_core as C

BG, PANEL, TEXT, MUTED = (13, 15, 29), (30, 33, 52), (230, 230, 234), (150, 154, 175)
RANK = {5: (255, 215, 64), 4: (214, 160, 224), 3: (144, 202, 249)}


def _font(path, size):
    try:
        return ImageFont.truetype(path, size) if path else ImageFont.load_default()
    except OSError:
        return ImageFont.load_default()


def _bar(d, x, y, w, h, value, maximum, color):
    d.rounded_rectangle((x, y, x + w, y + h), radius=h // 2, fill=(45, 48, 70))
    fill = int(w * min(1.0, value / maximum)) if maximum else 0
    if fill > h:
        d.rounded_rectangle((x, y, x + fill, y + h), radius=h // 2, fill=color)


def render_share_card(tracker, out_path: str, font_regular: str = None, font_bold: str = None) -> str:
    W, H = 1080, 1350
    img = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(img, "RGBA")
    f_title, f_h, f_txt, f_small = (_font(font_bold, 56), _font(font_bold, 40),
                                    _font(font_regular, 34), _font(font_regular, 28))
    f_tiny = _font(font_regular, 24)
    prof = tracker.db.active_profile() or {"name": ""}
    d.text((60, 50), "NTE Gacha Tracker", font=f_title, fill=RANK[5])
    d.text((60, 125), f"Профиль: {prof['name']}", font=f_txt, fill=MUTED)

    total_all = sum(tracker.stats[b]["total"] for b in C.BANNERS)
    s_all = sum(tracker.stats[b]["r5"] for b in C.BANNERS)
    pities = [p for b in C.BANNERS for p in tracker.stats[b]["pities"]]
    avg = f"{sum(pities) / len(pities):.1f}" if pities else "—"
    for i, (label, value) in enumerate((("Всего круток", str(total_all)), ("Всего S", str(s_all)),
                                        ("Средний гарант (S)", avg))):
        x = 60 + i * 330
        d.rounded_rectangle((x, 200, x + 300, 360), radius=24, fill=PANEL + (230,),
                            outline=(255, 255, 255, 40), width=2)
        d.text((x + 24, 224), label, font=f_tiny, fill=MUTED)
        d.text((x + 24, 280), value, font=f_h, fill=RANK[5])

    y = 400
    for banner in C.BANNERS:
        s = tracker.pool_summary(banner)
        d.rounded_rectangle((60, y, W - 60, y + 275), radius=24, fill=PANEL + (230,),
                            outline=(255, 255, 255, 40), width=2)
        d.text((90, y + 20), s["title"], font=f_h, fill=TEXT)
        d.text((90, y + 80), f"Круток: {s['total']}   S: {s['s']}   A: {s['a']}   B: {s['b']}",
               font=f_txt, fill=TEXT)
        if banner == C.ARC_BANNER:
            d.text((90, y + 128), f"Стандартная S дуга: {s['counter_std']}/{C.PITY_ARC_STD}", font=f_small, fill=MUTED)
            _bar(d, 90, y + 168, 900, 22, s["counter_std"], C.PITY_ARC_STD, RANK[4])
            d.text((90, y + 200), f"Ивентовая S дуга: {s['counter_ev']}/{C.PITY_ARC_EVENT}", font=f_small, fill=MUTED)
            _bar(d, 90, y + 238, 900, 18, s["counter_ev"], C.PITY_ARC_EVENT, RANK[5])
        else:
            d.text((90, y + 128), f"До гаранта: {s['counter']}/{C.PITY_CHAR_HARD}   (мягкий: {C.PITY_CHAR_SOFT})",
                   font=f_small, fill=MUTED)
            _bar(d, 90, y + 180, 900, 26, s["counter"], C.PITY_CHAR_HARD, RANK[5])
            d.text((90, y + 214), f"Средний гарант (S): {s['avg_pity'] or '—'}", font=f_small, fill=MUTED)
        y += 300
    img.save(out_path, "PNG")
    return out_path

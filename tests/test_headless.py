"""Запуск: python -m pytest tests -q  (или python tests/test_headless.py). Без Android и Qt."""
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import nte_core as C                      # noqa: E402
import ocr_android as OA                  # noqa: E402
import services as S                      # noqa: E402


def make_tracker():
    d = tempfile.mkdtemp()
    t = S.Tracker(os.path.join(d, "nte_wishes.db"))
    t.create_profile("Тест")
    return t, d


def test_dates():
    assert C.parse_russian_datetime("30 апр. 2026 г. 12:03:36") == "2026-04-30 12:03:36"
    assert C.parse_russian_datetime("1 мая 2026 г. 09:05:01") == "2026-05-01 09:05:01"


def test_parse_russian_rows():
    t, _ = make_tracker()
    text = ("Здесь отображаются записи о ваших бросках кубика за последние полгода.\n"
            "Хотори 30 апр. 2026 г. 12:03:36\nАдлер 30 апр. 2026 г. 12:03:30\n"
            "Потерянный фрагмент 30 30 апр. 2026 г. 12:03:20\nТвердый кубик 1 30 апр. 2026 г. 12:03:10")
    pulls, skipped, _rows = C.parse_screenshot_text_ex(text, t.known, None, None, "character", None)
    names = [(p["loot"], p["name"]) for p in pulls]
    assert ("character", "Хотори") in names and ("character", "Адлер") in names
    assert not any(p["name"] == "Твердый кубик (1 шт)" and p["loot"] == "character" for p in pulls)
    assert len(pulls) == 5      # две строки фрагмента и кубик + 2 персонажа (как в десктопе)


def test_session_commit_and_pity():
    t, _ = make_tracker()
    shots = []
    for i in range(2):
        f = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
        f.write(b"x")
        f.close()
        os.utime(f.name, (1_700_000_000 + i * 60, 1_700_000_000 + i * 60))
        shots.append(f.name)
    texts = {shots[0]: "Адлер 30 апр. 2026 г. 12:03:30\nХотори 30 апр. 2026 г. 12:03:36",
             shots[1]: "Адлер 30 апр. 2026 г. 12:10:30\nХотори 30 апр. 2026 г. 12:10:36"}

    def fake_pipeline(path):
        txt = texts[path]
        return {"lines": [], "text": txt, "ranks": [None, None], "glob": None, "page": None,
                "confs": [90, 90]}
    old = C.run_ocr_pipeline
    C.run_ocr_pipeline = fake_pipeline
    try:
        s = S.ScanSession(t, shots, C.EVENT_BANNER)
        s.scan()
        s.build()
        assert len(s.found) == 4
        w, r = s.commit(s.found)
    finally:
        C.run_ocr_pipeline = old
    assert w + r == 4
    st = t.pool_summary(C.EVENT_BANNER)
    assert st["total"] == w
    assert [h["date"] for h in reversed(t.history)] == sorted(h["date"] for h in t.history)


def test_pity_rules():
    t, _ = make_tracker()
    base = "2026-05-01 10:00:"
    for i in range(69):
        t.db.add_many([{"banner": C.EVENT_BANNER, "rarity": 3, "name": "Мусор", "pulled_at": f"{base}{i:02d}",
                        "is_bonus": 0, "arc_kind": "", "cashback": ""}])
    t.db.add_many([{"banner": C.EVENT_BANNER, "rarity": 4, "name": "Бонус", "pulled_at": "2026-05-01 11:00:00",
                    "is_bonus": 1, "arc_kind": "", "cashback": ""}])
    t.refresh()
    s = t.pool_summary(C.EVENT_BANNER)
    assert s["counter"] == 69 and s["bonus"] == 1        # бонус не двигает гарант
    assert (C.PITY_CHAR_SOFT, C.PITY_CHAR_HARD) == (70, 90)


class FakeBackend:
    """Имитирует JavaTessBackend: отдаёт слова в том же формате."""
    def __init__(self):
        self.calls = []

    def languages(self):
        return ["eng", "rus"]

    def recognize(self, png, lang, psm, oem, variables):
        assert os.path.isfile(png)
        self.calls.append((lang, psm, oem, dict(variables)))
        return [("Хотори", 91.0, 10, 10, 90, 30, 1, 1, 1, 1),
                ("30", 88.0, 100, 10, 120, 30, 1, 1, 1, 2)]


def test_ocr_shim_contract():
    from PIL import Image
    b = FakeBackend()
    shim = OA.AndroidTesseract(b)
    cfg = f"--psm 6 {C.OCR_BASE_CONFIG}"
    data = shim.image_to_data(Image.new("RGB", (50, 20)), lang="rus+eng", config=cfg,
                              output_type=shim.Output.DICT)
    assert b.calls[0] == ("rus+eng", 6, 1, {"preserve_interword_spaces": "1", "user_defined_dpi": "300"})
    words = C._extract_words(data, 1.0)             # реальная функция конвейера из main.py
    assert [w["text"] for w in words] == ["Хотори", "30"]
    assert words[0]["box"] == (10, 10, 90, 30)
    assert shim.image_to_string(Image.new("L", (5, 5)), lang="eng", config="--psm 7") == "Хотори 30"
    assert "rus" in shim.get_languages()


def test_installed_shim_drives_core():
    """nte_core.ocr_image -> конвейер -> shim: слова доходят до строк без исключений."""
    from PIL import Image, ImageDraw
    img = Image.new("RGB", (1280, 720), (20, 22, 35))
    ImageDraw.Draw(img).text((200, 300), "Test 30", fill=(255, 255, 255))
    path = os.path.join(tempfile.mkdtemp(), "shot.png")
    img.save(path)
    OA.install(C, "/nonexistent")
    C.pytesseract.backend = FakeBackend()
    lines = C.ocr_image(path, roi=None)
    assert isinstance(lines, list)


def test_manual_add_all_types():
    t, _ = make_tracker()
    t.add_manual("character", C.EVENT_BANNER, 5, "Хотори", "2026-05-01 10:00:00")
    t.add_manual("solid5", C.EVENT_BANNER, 4, "", "2026-05-01 10:01:00", qty="5")
    assert t.pool_summary(C.EVENT_BANNER)["s"] == 1 and len(t.rewards) == 1
    try:
        t.add_manual("character", C.EVENT_BANNER, 3, "X", "не дата")
        assert False
    except ValueError:
        pass


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("OK ", name)

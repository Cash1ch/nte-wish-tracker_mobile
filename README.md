# NTE Wish Tracker → Android

Russian UI, Russian OCR (`rus+eng`), SQLite, multi-profile, pity logic — ported from your
22 036-line PyQt6 `main.py` without rewriting the logic.

## 1. Framework decision

| Option | Verdict |
|---|---|
| **Kivy + Buildozer / python-for-android** | **Chosen.** Pure Python on-device, recipes for `numpy`, `pillow`, `opencv`, `pyjnius`; touch-first; Roboto (bundled) covers Cyrillic; free drawing API for the glass cards. |
| BeeWare (Toga + Briefcase/Chaquopy) | Native widgets can't do glassmorphism; custom drawing is limited. |
| PySide6 for Android | Would let you reuse widgets, but your UI is desktop-style (tables, dialogs, 15k lines of QPainter), and NumPy/OpenCV wheels for that toolchain are the hard part anyway. |
| Kotlin/Compose + Chaquopy | Best native UX, but means rewriting the whole UI in Kotlin. |

**Why not ML Kit for OCR:** Google's on-device text recognizer has no Cyrillic model. Tesseract is the
right engine, and your pipeline is tuned for it.

## 2. Architecture

```
main.py              Kivy UI (5 tabs: Стафф, История, Скриншоты, Добавить, Настройки)
services.py          Qt-free orchestration: Tracker (refresh/stats/banners), ScanSession (OCR batch)
nte_core.py          GENERATED from your desktop main.py (775 of 871 top-level nodes, ~10.7k lines)
qt_shim.py           QDateTime / QColor stand-ins (the parsers pass QDateTime objects around)
ocr_android.py       pytesseract-compatible object backed by Tesseract4Android (pyjnius)
platform_android.py  paths, tessdata copy, gallery picker, camera, share sheet
share_card.py        Pillow replacement for ShareCardRenderer (QPainter)
tools/extract_core.py   main.py -> nte_core.py (AST-based, re-run after every desktop change)
tools/fetch_tessdata.py rus/eng.traineddata downloader
tests/test_headless.py  runs without Android or Qt
```

**Key idea — the core is generated, not rewritten.** `tools/extract_core.py` keeps every top-level
node that doesn't touch Qt (constants, Russian date parsing, `difflib` roster matching, the whole
OCR pipeline, `Database` with migrations, `compute_stats`, banner JSON parsing, batch ordering) and
drops widgets/painters/threads and anything that references them. Fix an OCR rule in the desktop
`main.py`, re-run the script, rebuild the APK — both apps stay in sync.

**OCR on Android.** Your pipeline calls only `pytesseract.image_to_data(..., output_type=DICT)`,
`image_to_string`, `get_languages` and the two exception classes. `ocr_android.AndroidTesseract`
implements exactly that on top of `TessBaseAPI` + `ResultIterator`, so the two-pass logic, line
grouping, Cyrillic fuzzy matching, `Хотори`/`Минт` fixes, date parsing, etc. run unchanged.

## 3. Build, step by step

Use Ubuntu 22.04/24.04 or WSL2 (Buildozer does not build on Windows natively).

```bash
# 0. system packages
sudo apt update && sudo apt install -y git zip unzip openjdk-17-jdk python3-pip \
    autoconf libtool pkg-config zlib1g-dev libncurses5-dev libncursesw5-dev libtinfo6 \
    cmake libffi-dev libssl-dev
pip install --user buildozer cython==0.29.36 virtualenv

# 1. put this folder next to your desktop main.py, then generate the core
cd nte_android
python3 tools/extract_core.py ../main.py nte_core.py      # prints what was dropped; must end with "неопределённых имён нет"

# 2. language data (same variant as your desktop Tesseract: fast ≈ 4 MB, best ≈ 15 MB)
python3 tools/fetch_tessdata.py            # or: --best

# 3. assets (optional, same names as on desktop)
mkdir -p assets/icons assets/audio
cp -r ../assets/* assets/ 2>/dev/null       # character/arc icons, backgrounds
cp ../assets/audio/bgm.mp3 assets/audio/ 2>/dev/null

# 4. debug APK (first build downloads SDK/NDK, ~20-40 min)
buildozer android debug

# 5. install and watch logs
adb install -r bin/ntewishtracker-0.1.0-arm64-v8a-debug.apk
adb logcat -s python:* *:E
```

Release: `buildozer android release`, then sign with `apksigner` (or use an AAB:
`android.release_artifact = aab` in the spec).

## 4. Test before you build

```bash
pip install -r requirements-dev.txt
python3 tests/test_headless.py        # dates, DB, pity, batch import, OCR adapter contract
python3 main.py                       # the same Kivy UI on desktop, real pytesseract with rus installed
NTE_TEST_IMAGES="/path/a.png:/path/b.png" python3 main.py   # feeds the "Галерея" button on desktop
```

What the tests cover: Russian date formats (`30 апр. 2026 г. 12:03:36`), the UI-note filter,
no `Твердый кубик (1 шт)` → character leaks, bonus rows not moving pity, chronological
`import_batch`, manual add of every loot type, and the adapter's output being accepted by your real
`_extract_words`.

## 5. Feature coverage

| Area | Status |
|---|---|
| SQLite schema, auto-migrations, `profile_id`, `seq`, `batch_id`, settings | Reused as is (`Database`) |
| Pity: char soft 70 / hard 90, arcs std 60 / event 80, bonus & non-pity rules | Reused (`compute_stats`) |
| Banner cards, period-only counters, live countdown, `banners.json` (first launch included) | `Tracker.banner_cards`, 1 s ticker |
| Staff tab, history, manual add, profiles, music + volume, JSON import/export, DB backup/restore | Implemented in `main.py` |
| Share card (Russian labels) | Pillow, shared via Android share sheet |
| Gallery / camera, batch OCR, page ordering, chronology repair, review editor, bulk import | `ScanSession` + scan tab |
| Russian OCR (`rus+eng`), Cyrillic fuzzy matching, date repair | Unchanged code via adapter |
| **Not ported** (desktop-only, outside your list) | mini-games, fortune wheel, constellation tab, falling-particle background, achievements UI, **map overlay** (needs desktop screen capture — impossible on Android) |

Achievement/profile-summary *logic* is already in `nte_core` (`achievement_metrics`, `AchievementManager`);
only the widgets are missing.

## 6. Not verified here — check these on a device

I could run the core, DB, OCR-adapter contract and share card headlessly. I could **not** run Kivy or
build an APK in this environment, and the sandbox only had `eng` Tesseract data, so:

1. **Tesseract4Android calls** (`getResultIterator`, `isAtBeginningOf`, `getBoundingRect`, `confidence`)
   follow the tess-two/Tesseract4Android API as I know it; confirm in `adb logcat` on first scan.
   Version pinned to 4.9.0 — verify it resolves from Maven Central/JitPack.
2. **`androidstorage4kivy`** (`Chooser`, `SharedStorage.copy_from_shared`, `ShareSheet`) — API names from memory.
3. **Camera** uses `MediaStore.insert` + `ACTION_IMAGE_CAPTURE` (no FileProvider). Phone-screen photos OCR
   much worse than screenshots; prefer screenshots.
4. **Screenshot order** relies on file dates. The picker copies files and restores `last_modified`;
   if your gallery app strips it, batch order falls back to page numbers `N/M` and timestamps.
5. **OpenCV recipe** may need a pinned p4a branch; without it the Pillow fallback pipeline is used.
6. Speed: a 200-screenshot batch on a phone is minutes, not seconds — the screen stays awake during OCR.
7. `rus` accuracy differs between `tessdata_fast` and `tessdata_best`; match your desktop install.

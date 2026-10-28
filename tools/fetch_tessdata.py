#!/usr/bin/env python3
"""Скачивает rus.traineddata и eng.traineddata в ./tessdata (кладутся в APK).
   python tools/fetch_tessdata.py          # tessdata_fast  (~4 МБ rus, быстрее)
   python tools/fetch_tessdata.py --best   # tessdata_best  (~15 МБ rus, точнее, медленнее)
Берите ТОТ ЖЕ вариант, что стоит у вас в десктопном Tesseract: пороги уверенности в
OCR-конвейере подбирались под его выдачу."""
import sys
import urllib.request
from pathlib import Path

variant = "tessdata_best" if "--best" in sys.argv else "tessdata_fast"
out = Path(__file__).resolve().parent.parent / "tessdata"
out.mkdir(exist_ok=True)
for lang in ("rus", "eng"):
    url = f"https://raw.githubusercontent.com/tesseract-ocr/{variant}/main/{lang}.traineddata"
    dst = out / f"{lang}.traineddata"
    print("скачиваю", url)
    urllib.request.urlretrieve(url, dst)
    print(f"  -> {dst} ({dst.stat().st_size // 1024} КБ)")

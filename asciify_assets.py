#!/usr/bin/env python3
"""Переименовывает файлы с не-ASCII именами в assets/ в u_<hex>.<ext> (hex = UTF-8 имени).
Запускается в CI перед buildozer; приложение декодирует имена обратно (assets_ascii.py).
   python tools/asciify_assets.py assets"""
import sys
import unicodedata
from pathlib import Path

root = Path(sys.argv[1] if len(sys.argv) > 1 else "assets")
n = 0
for p in sorted(root.rglob("*")):
    if p.is_file() and not p.name.isascii():
        stem = unicodedata.normalize("NFC", p.stem)
        new = p.with_name("u_" + stem.encode("utf-8").hex() + p.suffix.lower())
        p.rename(new)
        n += 1
print(f"переименовано файлов: {n} (в {root})")

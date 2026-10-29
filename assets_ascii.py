"""Иконки с русскими именами файлов на Android.

Файлы вроде «Хотори.png» не доезжают до APK / не читаются python-for-android. Перед сборкой
tools/asciify_assets.py переименовывает их в u_<hex>.png (hex = UTF-8 имени без расширения).
Здесь поиск иконок и арта в nte_core учится декодировать такие имена обратно, так что
остальной код (find_icon_path, баннеры) работает без изменений. Обычные имена тоже находятся."""
import unicodedata
from pathlib import Path

import nte_core as C

_INDEX = {}


def decode_stem(stem: str) -> str:
    if stem.startswith("u_"):
        try:
            return bytes.fromhex(stem[2:]).decode("utf-8")
        except ValueError:
            pass
    return stem


def norm(text: str) -> str:
    return unicodedata.normalize("NFC", str(text)).strip().lower().replace("ё", "е")


def _dir_index(folder: Path) -> dict:
    key = str(folder)
    if key not in _INDEX:
        idx = {}
        try:
            for p in sorted(folder.iterdir()):
                if p.is_file() and p.suffix.lower() in C.ICON_EXTS:
                    idx.setdefault(norm(decode_stem(p.stem)), p)
        except OSError:
            pass
        _INDEX[key] = idx
    return _INDEX[key]


def _lookup(folders, variants):
    keys = [norm(v) for v in variants]
    for folder in folders:
        if not folder.is_dir():
            continue
        idx = _dir_index(folder)
        for k in keys:
            if k in idx:
                return idx[k]
    return None


def search_icon(name: str):
    return _lookup(C.asset_dirs(), C._name_variants(name))          # noqa: SLF001


def find_art(variants: list):
    return _lookup(C._banner_art_folders(), variants)               # noqa: SLF001


def install() -> None:
    """Подменяет поиск иконок и арта в nte_core."""
    C._search_icon = search_icon                                     # noqa: SLF001
    C._find_art = find_art                                           # noqa: SLF001
    C._PATH_CACHE.clear()                                            # noqa: SLF001
    _INDEX.clear()

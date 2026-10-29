"""Иконки с русскими именами файлов на Android.

Файлы вроде «Хотори.png» не доезжают до APK / не читаются python-for-android. Перед сборкой
tools/asciify_assets.py переименовывает их в u_<hex>.png (hex = UTF-8 имени без расширения).
Здесь поиск иконок и арта в nte_core учится декодировать такие имена обратно, так что
остальной код (find_icon_path, баннеры) работает без изменений. Обычные имена тоже находятся."""
import hashlib
import os
import shutil
import tempfile
import unicodedata
from pathlib import Path

import nte_core as C

_INDEX = {}


def fixed_stem(stem: str) -> str:
    """Имя файла в нормальном виде. На некоторых Android Python читает кириллические имена как
    последовательность «суррогатов» (по одному на байт UTF-8); возвращаем исходные байты и
    декодируем их как UTF-8."""
    try:
        raw = os.fsencode(stem)
    except UnicodeEncodeError:
        raw = stem.encode("utf-8", "surrogateescape")
    return raw.decode("utf-8", "replace")


def _cache_dir() -> Path:
    base = getattr(C, "_DATA_DIR", None)
    d = (Path(base) if base else Path(tempfile.gettempdir())) / "assets_cache"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _safe_path(p: Path) -> Path:
    """Kivy/SDL не умеют открывать пути с суррогатами. Для таких файлов делаем ASCII-копию в кэше."""
    if str(p).isascii():
        return p
    try:
        key = hashlib.md5(os.fsencode(str(p))).hexdigest()
        dst = _cache_dir() / f"{key}{p.suffix.lower()}"
        if not dst.is_file() or dst.stat().st_size != p.stat().st_size:
            shutil.copyfile(p, dst)
        return dst
    except OSError:
        return p


def decode_stem(stem: str) -> str:
    stem = fixed_stem(stem)
    if stem.startswith("u_"):
        try:
            return bytes.fromhex(stem[2:]).decode("utf-8")
        except ValueError:
            pass
    return stem


def norm(text: str) -> str:
    return unicodedata.normalize("NFC", str(text)).strip().lower().replace("ё", "е")


BUILD_MARK = "icons-v3 (bytes API)"


def _mojibake(name: str):
    """'Ð¥Ð¾Ñ‚Ð¾Ñ€Ð¸' -> 'Хотори': UTF-8, прочитанный как Latin-1."""
    if any(ch in name for ch in "ÐÑ"):
        try:
            return name.encode("latin-1").decode("utf-8")
        except (UnicodeEncodeError, UnicodeDecodeError):
            pass
    return None


def _raw_files(folder: Path):
    """Файлы папки как БАЙТЫ: так имена не зависят от того, как Python декодирует файловую систему."""
    base = os.fsencode(str(folder))
    try:
        names = os.listdir(base)
    except OSError:
        return []
    out = []
    for raw in sorted(names):
        full = base + b"/" + raw
        stem, ext = os.path.splitext(raw)
        if os.path.isfile(full) and ext.decode("ascii", "ignore").lower() in C.ICON_EXTS:
            out.append((raw, stem, ext.decode("ascii", "ignore").lower(), full))
    return out


def _cached_copy(full: bytes, ext: str) -> Path:
    dst = _cache_dir() / f"{hashlib.md5(full).hexdigest()}{ext}"
    try:
        size = os.stat(full).st_size
        if not dst.is_file() or dst.stat().st_size != size:
            with open(full, "rb") as src, open(dst, "wb") as out:
                shutil.copyfileobj(src, out)
        return dst
    except OSError:
        return Path(full.decode("utf-8", "replace"))


def _dir_index(folder: Path) -> dict:
    key = str(folder)
    if key not in _INDEX:
        idx = {}
        for raw, stem, ext, full in _raw_files(folder):
            name = stem.decode("utf-8", "replace")
            path = Path(full.decode("ascii")) if raw.isascii() else _cached_copy(full, ext)
            for variant in (decode_stem(name), _mojibake(name)):
                if variant:
                    idx.setdefault(norm(variant), path)
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


_TR = dict(zip("абвгдеёжзийклмнопрстуфхцчшщъыьэюя",
               ["a", "b", "v", "g", "d", "e", "e", "zh", "z", "i", "y", "k", "l", "m", "n", "o", "p", "r", "s",
                "t", "u", "f", "h", "ts", "ch", "sh", "sch", "", "y", "", "e", "yu", "ya"]))


def translit(text: str) -> str:
    """Хотори -> hotori: на случай, если иконки лежат под латинскими именами."""
    return "".join(_TR.get(ch, ch) for ch in norm(text))


def search_icon(name: str):
    """Сначала русские имена (в том числе u_<hex>), затем латиница: Хотори -> hotori / Hotori."""
    variants = list(C._name_variants(name))                          # noqa: SLF001
    found = _lookup(C.asset_dirs(), variants)
    if found is None:
        extra = []
        for v in variants:
            t = translit(v)
            extra += [t, t.replace(" ", "_"), t.replace(" ", "-"), t.replace(" ", "")]
        found = _lookup(C.asset_dirs(), extra)
    return found


def describe() -> str:
    """Что реально лежит в assets/ на устройстве (для диагностики)."""
    import sys
    lines = [f"Поиск иконок: {BUILD_MARK}; кодировка ФС: {sys.getfilesystemencoding()}"]
    for folder in C.asset_dirs():
        if not folder.is_dir():
            continue
        files = _raw_files(folder)
        names = []
        for _raw, stem, _ext, _full in files[:4]:
            name = stem.decode("utf-8", "replace")
            names.append(decode_stem(name))
        lines.append(f"{folder.name}/: {len(files)} шт. " + (("— " + ", ".join(names)) if names else ""))
    bad = next(((r, s) for r, s, _e, _f in (x for f in C.asset_dirs() if f.is_dir() for x in _raw_files(f))
                if not r.isascii()), None)
    if bad:
        lines.append(f"Пример сырого имени: {ascii(bad[0])[:70]}")
    return "\n".join(lines) or "Папка assets/ с иконками на устройстве не найдена."


def find_art(variants: list):
    return _lookup(C._banner_art_folders(), variants)               # noqa: SLF001


def install() -> None:
    """Подменяет поиск иконок и арта в nte_core."""
    C._search_icon = search_icon                                     # noqa: SLF001
    C._find_art = find_art                                           # noqa: SLF001
    C._PATH_CACHE.clear()                                            # noqa: SLF001
    _INDEX.clear()

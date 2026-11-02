"""Работа с картинками: надёжная загрузка (Pillow, а если он не читает webp — декодер Kivy)
и заранее уменьшенные миниатюры.

Зачем миниатюры: иконки дуг/персонажей бывают 1000x1000, а на плитке показываются ~70 dp.
Kivy уменьшает такие текстуры без сглаживания (mipmap на GLES2 требует степени двойки),
поэтому картинка получается «рваной». Уменьшенная копия 256x256 (LANCZOS) выглядит чисто.
"""
import hashlib
import os
import tempfile
from pathlib import Path

from PIL import Image

_RES = getattr(Image, "Resampling", Image)
LANCZOS = _RES.LANCZOS

THUMB_PX = 256
_PIL_CACHE = {}


def _kivy_decode(path):
    """Запасной путь: SDL2_image внутри Kivy читает webp, даже если в Pillow его нет.
    ImageLoader.load не создаёт текстуру (OpenGL не нужен), поэтому можно из любого потока."""
    try:
        from kivy.core.image import ImageLoader
        loader = ImageLoader.load(str(path))
        data = loader._data[0]                                   # noqa: SLF001
        fmt = str(data.fmt).lower()
        if fmt not in ("rgba", "rgb"):
            return None
        img = Image.frombytes(fmt.upper(), tuple(data.size), bytes(data.data))
        return img.convert("RGBA")
    except Exception:  # noqa: BLE001
        return None


def load_pil(path, max_side=512):
    """Картинка как RGBA (не больше max_side по большей стороне) или None."""
    if not path:
        return None
    key = str(path)
    if key in _PIL_CACHE:
        return _PIL_CACHE[key]
    img = None
    try:
        img = Image.open(path)
        img.load()
        img = img.convert("RGBA")
    except Exception:  # noqa: BLE001
        img = _kivy_decode(path)
    if img is not None and max(img.size) > max_side:
        k = max_side / max(img.size)
        img = img.resize((max(1, round(img.width * k)), max(1, round(img.height * k))), LANCZOS)
    _PIL_CACHE[key] = img
    return img


def _cache_dir() -> Path:
    try:
        import nte_core as C
        base = getattr(C, "_DATA_DIR", None)
    except Exception:  # noqa: BLE001
        base = None
    d = (Path(base) if base else Path(tempfile.gettempdir())) / "icon_cache"
    d.mkdir(parents=True, exist_ok=True)
    return d


def thumb(path, px: int = THUMB_PX) -> str:
    """Путь к квадратной PNG-миниатюре не больше px (кэшируется). При любой ошибке — исходный путь."""
    if not path:
        return path
    try:
        src = Path(path)
        st = src.stat()
        sig = os.fsencode(str(src)) + f"|{st.st_size}|{int(st.st_mtime)}|{px}".encode()
        out = _cache_dir() / f"t{px}_{hashlib.md5(sig).hexdigest()}.png"
        if out.is_file():
            return str(out)
        img = load_pil(src, max_side=1024)
        if img is None:
            return str(path)
        if max(img.size) > px:
            k = px / max(img.size)
            img = img.resize((max(1, round(img.width * k)), max(1, round(img.height * k))), LANCZOS)
        img.save(out, "PNG")
        return str(out)
    except Exception:  # noqa: BLE001
        return str(path)

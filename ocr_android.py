"""Замена модуля pytesseract для Android (Tesseract4Android через pyjnius).

Весь OCR-конвейер из main.py вызывает только:
    pytesseract.image_to_data(img, lang, config, output_type=Output.DICT)
    pytesseract.image_to_string(img, lang, config)
    pytesseract.get_languages(config="")  + исключения TesseractError / TesseractNotFoundError
Этот модуль предоставляет объект с тем же интерфейсом, поэтому двухпроходная логика,
группировка строк, чтение дат и сопоставление русских названий НЕ меняются.

install(core, tessdata_parent) подставляет объект в nte_core.pytesseract.
"""
import os
import re
import tempfile
import threading
from types import SimpleNamespace

RIL_WORD = 3          # TessBaseAPI.PageIteratorLevel.RIL_WORD


class TesseractError(RuntimeError):
    pass


class TesseractNotFoundError(RuntimeError):
    pass


class Output:
    DICT = "dict"
    STRING = "string"


def parse_config(config: str) -> dict:
    """'--psm 6 --oem 1 -c a=b -c c=d' -> {'psm': 6, 'oem': 1, 'vars': {'a': 'b', 'c': 'd'}}"""
    psm = re.search(r"--psm\s+(\d+)", config or "")
    oem = re.search(r"--oem\s+(\d+)", config or "")
    variables = dict(re.findall(r"-c\s+([\w.]+)=(\S+)", config or ""))
    return {"psm": int(psm.group(1)) if psm else 3,
            "oem": int(oem.group(1)) if oem else 1, "vars": variables}


def _to_pil(img):
    from PIL import Image
    if isinstance(img, Image.Image):
        return img
    import numpy as np
    arr = np.asarray(img)
    if arr.ndim == 3 and arr.shape[2] == 3:
        arr = arr[:, :, ::-1]                       # BGR (OpenCV) -> RGB
    return Image.fromarray(arr)


def words_to_dict(words: list) -> dict:
    """words: [(text, conf, left, top, right, bottom, block, para, line, word_no), ...]
    -> словарь в формате pytesseract.Output.DICT (достаточно полей, что читает конвейер)."""
    keys = ("level", "page_num", "block_num", "par_num", "line_num", "word_num",
            "left", "top", "width", "height", "conf", "text")
    out = {k: [] for k in keys}
    for text, conf, l, t, r, b, blk, par, line, wn in words:
        out["level"].append(5)
        out["page_num"].append(1)
        out["block_num"].append(blk)
        out["par_num"].append(par)
        out["line_num"].append(line)
        out["word_num"].append(wn)
        out["left"].append(int(l))
        out["top"].append(int(t))
        out["width"].append(int(r - l))
        out["height"].append(int(b - t))
        out["conf"].append(float(conf))
        out["text"].append(text)
    return out


class AndroidTesseract:
    """Интерфейс pytesseract поверх backend.recognize(png_path, lang, psm, oem, vars) -> words."""

    TesseractError = TesseractError
    TesseractNotFoundError = TesseractNotFoundError
    Output = Output
    pytesseract = SimpleNamespace(tesseract_cmd="")

    def __init__(self, backend):
        self.backend = backend
        self._lock = threading.Lock()               # TessBaseAPI не потокобезопасен

    def get_languages(self, config: str = ""):
        return self.backend.languages()

    def _prepare(self, img) -> str:
        fd, path = tempfile.mkstemp(suffix=".png", prefix="ocr_")
        os.close(fd)
        _to_pil(img).save(path, format="PNG")
        return path

    def _run(self, img, lang, config):
        opts = parse_config(config)
        path = self._prepare(img)
        try:
            with self._lock:
                return self.backend.recognize(path, lang, opts["psm"], opts["oem"], opts["vars"])
        finally:
            try:
                os.remove(path)
            except OSError:
                pass

    def image_to_data(self, img, lang="eng", config="", output_type=Output.DICT, **_kw):
        return words_to_dict(self._run(img, lang, config))

    def image_to_string(self, img, lang="eng", config="", **_kw):
        words = self._run(img, lang, config)
        lines, last = [], None
        for text, _c, _l, _t, _r, _b, blk, par, line, _w in words:
            if (blk, par, line) != last:
                lines.append([])
                last = (blk, par, line)
            lines[-1].append(text)
        return "\n".join(" ".join(ws) for ws in lines)


_JAVA = {}      # кэш Java-классов: заполняется из ГЛАВНОГО потока (см. preload_java)

JAVA_CLASSES = ("com.googlecode.tesseract.android.TessBaseAPI",
                "com.googlecode.tesseract.android.ResultIterator",
                "com.googlecode.tesseract.android.PageIterator",
                "java.io.File")


def preload_java() -> None:
    """Загружает Java-классы Tesseract4Android ИЗ ГЛАВНОГО ПОТОКА.

    Python-потоки на Android ищут классы системным загрузчиком, который не видит классы
    приложения (ClassNotFoundException ... DexPathList[[directory "."]]). Главный поток видит
    их, а pyjnius кэширует найденные классы, поэтому потом они доступны и из потока OCR.
    Бросает исключение, если класса нет в APK вообще."""
    from jnius import autoclass
    for name in JAVA_CLASSES:
        _JAVA[name] = autoclass(name)


def _jclass(name: str):
    if name in _JAVA:
        return _JAVA[name]
    from jnius import autoclass
    _JAVA[name] = autoclass(name)
    return _JAVA[name]


class JavaTessBackend:
    """Tesseract4Android: com.googlecode.tesseract.android.TessBaseAPI (через pyjnius).

    tessdata_parent — папка, ВНУТРИ которой лежит каталог tessdata/ с rus.traineddata и
    eng.traineddata (требование Tesseract: путь указывает на родителя tessdata)."""

    def __init__(self, tessdata_parent: str):
        self.parent = tessdata_parent
        self._apis = {}                              # (lang, oem) -> (api, переменные, что выставлено)

    def languages(self):
        d = os.path.join(self.parent, "tessdata")
        try:
            return sorted(f[:-12] for f in os.listdir(d) if f.endswith(".traineddata"))
        except OSError:
            return []

    def _api(self, lang: str, oem: int):
        key = (lang, oem)
        if key not in self._apis:
            have = set(self.languages())
            need = set(lang.split("+"))
            if not need <= have:
                raise TesseractError(f"нет языковых файлов: {sorted(need - have)}")
            api = _jclass("com.googlecode.tesseract.android.TessBaseAPI")()
            if not api.init(self.parent, lang, oem):
                api.recycle()
                raise TesseractError(f"Tesseract не инициализировался для {lang}")
            self._apis[key] = (api, {})
        return self._apis[key]

    def recognize(self, png_path, lang, psm, oem, variables):
        File = _jclass("java.io.File")
        api, applied = self._api(lang, oem)
        for k in list(applied):                       # сбрасываем переменные прошлого запуска
            if k not in variables:
                api.setVariable(k, "")
                del applied[k]
        for k, v in variables.items():
            if applied.get(k) != v:
                api.setVariable(k, v)
                applied[k] = v
        api.setPageSegMode(psm)
        api.setImage(File(png_path))
        api.getUTF8Text()                             # запускает распознавание
        it = api.getResultIterator()
        words = []
        if it is not None:
            it.begin()
            blk = par = line = wn = 0
            while True:
                if it.isAtBeginningOf(0):
                    blk += 1
                    par = line = 0
                if it.isAtBeginningOf(1):
                    par += 1
                if it.isAtBeginningOf(2):
                    line += 1
                    wn = 0
                text = it.getUTF8Text(RIL_WORD)
                if text:
                    r = it.getBoundingRect(RIL_WORD)
                    wn += 1
                    words.append((text, it.confidence(RIL_WORD), r.left, r.top, r.right, r.bottom,
                                  blk, par, line, wn))
                if not it.next(RIL_WORD):
                    break
            it.delete()
        api.clear()
        return words


def install(core, tessdata_parent: str) -> AndroidTesseract:
    """Подменяет pytesseract внутри nte_core."""
    shim = AndroidTesseract(JavaTessBackend(tessdata_parent))
    core.pytesseract = shim
    core._ocr_langs_cache = None                     # список языков перечитается через shim
    return shim

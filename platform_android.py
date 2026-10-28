"""Платформенный слой: пути, разрешения, tessdata, выбор фото, камера, шеринг.

На Android — pyjnius / androidstorage4kivy. На десктопе (разработка и отладка) те же
функции работают через переменные окружения и обычные пути, поэтому `python main.py`
запускается и без телефона (там используется настоящий pytesseract).
"""
import os
import shutil
import sys
import time
from pathlib import Path

ON_ANDROID = "ANDROID_ARGUMENT" in os.environ or hasattr(sys, "getandroidapilevel")
APP_DIR = Path(__file__).resolve().parent


def user_data_dir() -> Path:
    if ON_ANDROID:
        from android.storage import app_storage_path            # type: ignore
        base = Path(app_storage_path())
    else:
        base = Path.home() / ".nte_wish_tracker_dev"
    base.mkdir(parents=True, exist_ok=True)
    return base


def cache_dir() -> Path:
    d = user_data_dir() / "shots"
    d.mkdir(parents=True, exist_ok=True)
    return d


def ensure_tessdata() -> Path:
    """Возвращает ПАПКУ-РОДИТЕЛЬ каталога tessdata (так просит TessBaseAPI.init).
    Файлы rus/eng.traineddata лежат в <проект>/tessdata и попадают в APK как обычные
    файлы (source.include_exts содержит traineddata). Если каталог приложения недоступен
    для чтения нативным кодом, файлы копируются в user_data_dir."""
    src = APP_DIR / "tessdata"
    if not src.is_dir():
        raise FileNotFoundError("в проекте нет папки tessdata/ с rus.traineddata и eng.traineddata "
                                "(скрипт tools/fetch_tessdata.py скачает их)")
    dst = user_data_dir() / "tessdata"
    dst.mkdir(parents=True, exist_ok=True)
    for f in src.glob("*.traineddata"):
        target = dst / f.name
        if not target.exists() or target.stat().st_size != f.stat().st_size:
            shutil.copy2(f, target)
    return user_data_dir()


def request_permissions(callback=None) -> None:
    """Намеренно пусто. Приложение целится в Android 10+ (minapi 29): выбор файлов идёт через
    системный SAF-диалог, снимок камеры пишется в MediaStore, поэтому разрешения на хранилище и
    CAMERA не нужны (а объявленное, но не выданное CAMERA ломает ACTION_IMAGE_CAPTURE).
    Нужен доступ к более старым Android — добавьте здесь запрос READ/WRITE_EXTERNAL_STORAGE."""
    if callback:
        callback()


# ---------------------------------------------------------------------------
# Время создания: десктопный конвейер упорядочивает снимки по mass_sort_key (дата файла),
# а копия из галереи получает «сегодняшнюю» дату. Возвращаем исходную.
# ---------------------------------------------------------------------------
def _uri_last_modified_ms(uri) -> int:
    try:
        from jnius import autoclass                                           # type: ignore
        activity = autoclass("org.kivy.android.PythonActivity").mActivity
        cur = activity.getContentResolver().query(uri, None, None, None, None)
        if cur is None:
            return 0
        try:
            for col in ("last_modified", "datetaken", "date_added"):
                idx = cur.getColumnIndex(col)
                if idx >= 0 and cur.moveToFirst():
                    v = cur.getLong(idx)
                    return v * 1000 if col == "date_added" else v
        finally:
            cur.close()
    except Exception:
        pass
    return 0


def _import_uris(uris) -> list:
    """content:// -> файлы в cache_dir() с сохранением даты. Возвращает список путей."""
    from androidstorage4kivy import SharedStorage                             # type: ignore
    storage, out = SharedStorage(), []
    for uri in uris or []:
        try:
            path = storage.copy_from_shared(uri)          # uri — объект android.net.Uri
        except Exception:
            continue
        if not path:
            continue
        dst = cache_dir() / f"{int(time.time() * 1000)}_{Path(path).name}"
        shutil.move(path, dst)
        ms = _uri_last_modified_ms(uri)
        if ms:
            os.utime(dst, (ms / 1000, ms / 1000))
        out.append(str(dst))
    return out


def pick_images(callback, multiple: bool = True, mime: str = "image/*") -> None:
    """Системный выбор файлов (SAF, без разрешений на всё хранилище). callback(list[str])."""
    if not ON_ANDROID:
        paths = [p for p in os.environ.get("NTE_TEST_IMAGES", "").split(os.pathsep) if p]
        callback(paths)
        return
    from androidstorage4kivy import Chooser                                   # type: ignore
    from kivy.clock import Clock

    def done(uris):
        paths = _import_uris(uris) if mime.startswith("image") else _import_plain(uris)
        Clock.schedule_once(lambda _dt: callback(paths), 0)
    Chooser(done).choose_content(mime, multiple=multiple)


def _import_plain(uris) -> list:
    return _import_uris(uris)


def take_photo(callback) -> None:
    """Камера: снимок сохраняется в MediaStore (Pictures/NTE) без FileProvider; затем копируется
    в cache_dir(). callback(list[str])."""
    if not ON_ANDROID:
        callback([])
        return
    from android import activity                                              # type: ignore
    from jnius import autoclass                                               # type: ignore
    from kivy.clock import Clock
    Intent = autoclass("android.content.Intent")
    MediaStore = autoclass("android.provider.MediaStore")
    ContentValues = autoclass("android.content.ContentValues")
    PythonActivity = autoclass("org.kivy.android.PythonActivity")
    act = PythonActivity.mActivity
    values = ContentValues()
    values.put("_display_name", f"nte_{int(time.time())}.jpg")
    values.put("mime_type", "image/jpeg")
    values.put("relative_path", "Pictures/NTE")
    uri = act.getContentResolver().insert(MediaStore.Images.Media.EXTERNAL_CONTENT_URI, values)
    code = 7301

    def on_result(request, result, _intent):
        if request != code:
            return
        activity.unbind(on_activity_result=on_result)
        paths = _import_uris([uri]) if result == -1 else []
        Clock.schedule_once(lambda _dt: callback(paths), 0)

    activity.bind(on_activity_result=on_result)
    intent = Intent(MediaStore.ACTION_IMAGE_CAPTURE)
    intent.putExtra(MediaStore.EXTRA_OUTPUT, uri)
    act.startActivityForResult(intent, code)


def share_file(path: str, title: str = "Поделиться") -> None:
    if not ON_ANDROID:
        print("share:", path)
        return
    from androidstorage4kivy import ShareSheet                                # type: ignore
    ShareSheet().share_file(path)


def keep_screen_on(flag: bool = True) -> None:
    """Экран не гаснет во время долгого пакетного OCR."""
    if not ON_ANDROID:
        return
    from android.runnable import run_on_ui_thread                             # type: ignore
    from jnius import autoclass                                               # type: ignore

    @run_on_ui_thread
    def _apply():
        act = autoclass("org.kivy.android.PythonActivity").mActivity
        LP = autoclass("android.view.WindowManager$LayoutParams")
        w = act.getWindow()
        (w.addFlags if flag else w.clearFlags)(LP.FLAG_KEEP_SCREEN_ON)
    _apply()

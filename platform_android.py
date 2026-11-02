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
    Файлы копируются без переноса прав доступа: исходники в APK read-only,
    а копия должна оставаться перезаписываемой."""
    src = APP_DIR / "tessdata"
    if not src.is_dir():
        raise FileNotFoundError("в проекте нет папки tessdata/ с rus.traineddata и eng.traineddata "
                                "(скрипт tools/fetch_tessdata.py скачает их)")
    dst = user_data_dir() / "tessdata"
    dst.mkdir(parents=True, exist_ok=True)
    for f in src.glob("*.traineddata"):
        target = dst / f.name
        if target.exists() and target.stat().st_size == f.stat().st_size:
            continue
        if target.exists():                       # остался от прошлой версии, возможно read-only
            try:
                os.chmod(target, 0o644)
                target.unlink()
            except OSError:
                pass
        shutil.copyfile(f, target)                # copyfile не копирует права
        os.chmod(target, 0o644)
    return user_data_dir()


def request_permissions(callback=None) -> None:
    """Намеренно пусто. Приложение целится в Android 10+ (minapi 29): выбор файлов идёт через
    системный SAF-диалог, снимок камеры пишется в MediaStore, поэтому разрешения на хранилище и
    CAMERA не нужны (а объявленное, но не выданное CAMERA ломает ACTION_IMAGE_CAPTURE).
    Нужен доступ к более старым Android — добавьте здесь запрос READ/WRITE_EXTERNAL_STORAGE."""
    if callback:
        callback()


# ---------------------------------------------------------------------------
# Выбор файлов (системный SAF-диалог) и камера — своя реализация на pyjnius, без сторонних
# библиотек: ошибки не глотаются, а показываются окном и пишутся в logcat (тег python).
# ---------------------------------------------------------------------------
def _show_error(text: str, title: str = "Выбор файла") -> None:
    print("NTE picker error:", text)
    try:
        from kivy.clock import Clock
        from kivy.metrics import dp
        from kivy.uix.label import Label
        from kivy.uix.popup import Popup

        def show(_dt):
            lbl = Label(text=text, halign="left", valign="top")
            lbl.bind(size=lambda w, s: setattr(w, "text_size", (s[0] - dp(12), None)))
            Popup(title=title, content=lbl, size_hint=(0.92, 0.5)).open()
        Clock.schedule_once(show, 0)
    except Exception:
        pass


def _display_name(resolver, uri) -> str:
    try:
        cur = resolver.query(uri, None, None, None, None)
        if cur is not None:
            try:
                idx = cur.getColumnIndex("_display_name")
                if idx >= 0 and cur.moveToFirst():
                    return cur.getString(idx) or ""
            finally:
                cur.close()
    except Exception:
        pass
    return ""


def _uri_last_modified_ms(resolver, uri) -> int:
    """Время создания: конвейер упорядочивает снимки по дате файла, а копия из галереи
    получает «сегодняшнюю» дату. Возвращаем исходную."""
    try:
        cur = resolver.query(uri, None, None, None, None)
        if cur is None:
            return 0
        try:
            for col in ("last_modified", "datetaken", "date_added"):
                idx = cur.getColumnIndex(col)
                if idx >= 0 and cur.moveToFirst():
                    v = cur.getLong(idx)
                    if v:
                        return v * 1000 if col == "date_added" else v
        finally:
            cur.close()
    except Exception:
        pass
    return 0


def _copy_uri(uri) -> str:
    """content:// -> файл в cache_dir() с сохранением даты. Бросает исключение при сбое."""
    from jnius import autoclass                                               # type: ignore
    act = autoclass("org.kivy.android.PythonActivity").mActivity
    FileOutputStream = autoclass("java.io.FileOutputStream")
    FileUtils = autoclass("android.os.FileUtils")                             # API 29+
    resolver = act.getContentResolver()
    name = _display_name(resolver, uri) or "shot.png"
    safe = "".join(ch if ch.isalnum() or ch in "._-" else "_" for ch in name)
    dst = cache_dir() / f"{int(time.time() * 1000)}_{safe}"
    ins = resolver.openInputStream(uri)
    if ins is None:
        raise OSError("не удалось открыть файл: " + str(uri.toString()))
    outs = FileOutputStream(str(dst))
    try:
        FileUtils.copy(ins, outs)
    finally:
        ins.close()
        outs.close()
    ms = _uri_last_modified_ms(resolver, uri)
    if ms:
        os.utime(dst, (ms / 1000, ms / 1000))
    return str(dst)


def _uris_from_intent(intent) -> list:
    uris = []
    clip = intent.getClipData()
    if clip is not None:
        for i in range(clip.getItemCount()):
            uris.append(clip.getItemAt(i).getUri())
    else:
        data = intent.getData()
        if data is not None:
            uris.append(data)
    return uris


def _finish(callback, uris) -> None:
    """Копирование в фоне, результат — в главный поток Kivy."""
    import threading
    from kivy.clock import Clock

    def work():
        paths, errors = [], []
        for u in uris:
            try:
                paths.append(_copy_uri(u))
            except Exception as e:  # noqa: BLE001
                errors.append(f"{type(e).__name__}: {e}")
        if errors:
            _show_error("Не удалось прочитать файлы:\n" + "\n".join(errors[:3]))
        Clock.schedule_once(lambda _dt: callback(paths), 0)
    threading.Thread(target=work, daemon=True).start()


def pick_images(callback, multiple: bool = True, mime: str = "image/*") -> None:
    """Системный выбор файлов (ACTION_OPEN_DOCUMENT, разрешения на хранилище не нужны).
    callback(list[str]) вызывается в главном потоке; при отмене — с пустым списком."""
    if not ON_ANDROID:
        paths = [p for p in os.environ.get("NTE_TEST_IMAGES", "").split(os.pathsep) if p]
        callback(paths)
        return
    from android import activity                                              # type: ignore
    from jnius import autoclass                                               # type: ignore
    from kivy.clock import Clock
    Intent = autoclass("android.content.Intent")
    act = autoclass("org.kivy.android.PythonActivity").mActivity
    code = 7302

    def on_result(request, result, intent):
        if request != code:
            return
        activity.unbind(on_activity_result=on_result)
        try:
            if result != -1 or intent is None:               # отмена
                Clock.schedule_once(lambda _dt: callback([]), 0)
                return
            _finish(callback, _uris_from_intent(intent))
        except Exception as e:  # noqa: BLE001
            _show_error(f"{type(e).__name__}: {e}")
            Clock.schedule_once(lambda _dt: callback([]), 0)

    activity.bind(on_activity_result=on_result)
    try:
        intent = Intent(Intent.ACTION_OPEN_DOCUMENT)
        intent.addCategory(Intent.CATEGORY_OPENABLE)
        intent.setType(mime)
        if multiple:
            intent.putExtra(Intent.EXTRA_ALLOW_MULTIPLE, True)
        act.startActivityForResult(intent, code)
    except Exception as e:  # noqa: BLE001
        activity.unbind(on_activity_result=on_result)
        _show_error(f"Не удалось открыть выбор файлов:\n{type(e).__name__}: {e}")


def take_photo(callback) -> None:
    """Камера: снимок пишется в MediaStore (Pictures/NTE) без FileProvider, затем копируется
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
    act = autoclass("org.kivy.android.PythonActivity").mActivity
    code = 7301
    try:
        values = ContentValues()
        values.put("_display_name", f"nte_{int(time.time())}.jpg")
        values.put("mime_type", "image/jpeg")
        values.put("relative_path", "Pictures/NTE")
        uri = act.getContentResolver().insert(MediaStore.Images.Media.EXTERNAL_CONTENT_URI, values)
    except Exception as e:  # noqa: BLE001
        _show_error(f"Камера недоступна:\n{type(e).__name__}: {e}")
        callback([])
        return

    def on_result(request, result, _intent):
        if request != code:
            return
        activity.unbind(on_activity_result=on_result)
        if result == -1:
            _finish(callback, [uri])
        else:
            Clock.schedule_once(lambda _dt: callback([]), 0)

    activity.bind(on_activity_result=on_result)
    try:
        intent = Intent(MediaStore.ACTION_IMAGE_CAPTURE)
        intent.putExtra(MediaStore.EXTRA_OUTPUT, uri)
        act.startActivityForResult(intent, code)
    except Exception as e:  # noqa: BLE001
        activity.unbind(on_activity_result=on_result)
        _show_error(f"Не удалось открыть камеру:\n{type(e).__name__}: {e}")


def _mime_for(path: str) -> str:
    import mimetypes
    return mimetypes.guess_type(str(path))[0] or "application/octet-stream"


def _media_insert(path: str, mime: str = None, folder: str = "NTE"):
    """Копирует файл в общее хранилище через MediaStore и возвращает content:// Uri.

    Картинки попадают в Pictures/<folder> (видны в галерее), остальное — в Download/<folder>.
    FileProvider и разрешения на хранилище не нужны (Android 10+, как и камера выше).
    Именно из-за отсутствия FileProvider в сборке не работал androidstorage4kivy.ShareSheet."""
    from jnius import autoclass                                               # type: ignore
    act = autoclass("org.kivy.android.PythonActivity").mActivity
    ContentValues = autoclass("android.content.ContentValues")
    FileInputStream = autoclass("java.io.FileInputStream")
    FileUtils = autoclass("android.os.FileUtils")                             # API 29+
    resolver = act.getContentResolver()
    mime = mime or _mime_for(path)
    values = ContentValues()
    values.put("_display_name", Path(path).name)
    values.put("mime_type", mime)
    if mime.startswith("image/"):
        collection = autoclass("android.provider.MediaStore$Images$Media").EXTERNAL_CONTENT_URI
        values.put("relative_path", f"Pictures/{folder}")
    else:
        collection = autoclass("android.provider.MediaStore$Downloads").EXTERNAL_CONTENT_URI
        values.put("relative_path", f"Download/{folder}")
    uri = resolver.insert(collection, values)
    if uri is None:
        raise OSError("MediaStore не создал запись для файла")
    ins = FileInputStream(str(path))
    outs = resolver.openOutputStream(uri)
    try:
        FileUtils.copy(ins, outs)
    finally:
        ins.close()
        outs.close()
    return uri


def save_to_gallery(path: str) -> str:
    """Сохраняет картинку в Pictures/NTE. Возвращает человекочитаемое место или бросает исключение."""
    if not ON_ANDROID:
        print("save:", path)
        return str(path)
    _media_insert(path, _mime_for(path))
    return "Pictures/NTE"


def share_file(path: str, title: str = "Поделиться", mime: str = None) -> None:
    """Системное окно «Поделиться» (ACTION_SEND) для файла: картинки, JSON, копия базы."""
    if not ON_ANDROID:
        print("share:", path)
        return
    try:
        from jnius import autoclass, cast                                     # type: ignore
        Intent = autoclass("android.content.Intent")
        String = autoclass("java.lang.String")
        act = autoclass("org.kivy.android.PythonActivity").mActivity
        mime = mime or _mime_for(path)
        uri = _media_insert(path, mime)
        intent = Intent(Intent.ACTION_SEND)
        intent.setType(mime)
        intent.putExtra(Intent.EXTRA_STREAM, cast("android.os.Parcelable", uri))
        intent.addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
        chooser = Intent.createChooser(intent, cast("java.lang.CharSequence", String(title)))
        act.startActivity(chooser)
    except Exception as e:  # noqa: BLE001
        _show_error(f"Не удалось поделиться файлом:\n{type(e).__name__}: {e}", "Поделиться")


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

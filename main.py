"""NTE Wish Tracker — Android (Kivy). Отладка на ПК: python main.py (нужен Tesseract с rus).

Вся логика (OCR-разбор, русские даты, гаранты, БД, баннеры) — в nte_core.py, который
генерируется из десктопного main.py (tools/extract_core.py). Здесь только интерфейс.
"""
import os
import threading
from datetime import datetime
from pathlib import Path

os.environ.setdefault("KIVY_NO_ARGS", "1")
try:                                    # корневые сертификаты для https (banners.json с GitHub)
    import certifi
    os.environ.setdefault("SSL_CERT_FILE", certifi.where())
except ImportError:
    pass

from kivy.app import App                                                    # noqa: E402
from kivy.clock import Clock                                                # noqa: E402
from kivy.core.audio import SoundLoader                                     # noqa: E402
from kivy.core.window import Window                                         # noqa: E402
from kivy.lang import Builder                                               # noqa: E402
from kivy.metrics import dp                                                 # noqa: E402
from kivy.properties import BooleanProperty, ListProperty, NumericProperty, ObjectProperty, StringProperty  # noqa: E402,E501
from kivy.resources import resource_find                                    # noqa: E402
from kivy.uix.boxlayout import BoxLayout                                    # noqa: E402
from kivy.uix.button import Button                                          # noqa: E402
from kivy.uix.label import Label                                            # noqa: E402
from kivy.uix.popup import Popup                                            # noqa: E402
from kivy.uix.progressbar import ProgressBar                                # noqa: E402
from kivy.uix.recycleboxlayout import RecycleBoxLayout                      # noqa: E402
from kivy.uix.recycleview import RecycleView                                # noqa: E402
from kivy.uix.recycleview.views import RecycleDataViewBehavior              # noqa: E402
from kivy.uix.scrollview import ScrollView                                  # noqa: E402
from kivy.uix.slider import Slider                                          # noqa: E402
from kivy.uix.spinner import Spinner                                        # noqa: E402
from kivy.uix.switch import Switch                                          # noqa: E402
from kivy.uix.textinput import TextInput                                    # noqa: E402
from kivy.uix.togglebutton import ToggleButton                              # noqa: E402

import nte_core as C                                                        # noqa: E402
import ocr_android                                                          # noqa: E402
import platform_android as P                                                # noqa: E402
import services as S                                                        # noqa: E402
from share_card import render_share_card                                    # noqa: E402

RANK_COLOR = {5: "ffd740", 4: "d6a0e0", 3: "90caf9"}        # S золотой, A фиолетовый, B синий
MUTED = "9a9eb0"
POOLS = [(C.EVENT_BANNER, "Ивентовые персонажи"), (C.STANDARD_BANNER, "Стандартные персонажи"),
         (C.ARC_BANNER, "Дуги")]
POOL_BY_TITLE = {t: k for k, t in POOLS}

KV = """
#:import dp kivy.metrics.dp
<Glass>:
    orientation: 'vertical'
    padding: dp(12)
    spacing: dp(6)
    size_hint_y: None
    height: self.minimum_height
    canvas.before:
        Color:
            rgba: 1, 1, 1, 0.07
        RoundedRectangle:
            pos: self.pos
            size: self.size
            radius: [dp(14)]
        Color:
            rgba: 1, 1, 1, 0.16
        Line:
            rounded_rectangle: (self.x, self.y, self.width, self.height, dp(14))
            width: 1
<GBtn>:
    background_normal: ''
    background_color: 1, 1, 1, 0.14
    color: 0.93, 0.93, 0.96, 1
    size_hint_y: None
    height: dp(46)
<ResRow>:
    orientation: 'horizontal'
    size_hint_y: None
    height: dp(58)
    spacing: dp(6)
    CheckBox:
        size_hint_x: None
        width: dp(44)
        active: root.checked
        on_active: root.on_check(self.active)
    Button:
        text: root.text
        markup: True
        halign: 'left'
        valign: 'middle'
        text_size: (self.width - dp(12), self.height)
        background_normal: ''
        background_color: root.bg
        on_release: root.on_edit()
<HistRow>:
    background_normal: ''
    background_color: 1, 1, 1, 0.05
    markup: True
    halign: 'left'
    valign: 'middle'
    text_size: (self.width - dp(12), self.height)
"""


class Glass(BoxLayout):
    """Карточка в стиле «стекло»: полупрозрачная заливка, скругление, светлая рамка."""


class GBtn(Button):
    pass


class WLabel(Label):
    """Переносимая по ширине подпись с авто-высотой."""
    def __init__(self, **kw):
        kw.setdefault("size_hint_y", None)
        kw.setdefault("markup", True)
        kw.setdefault("halign", "left")
        super().__init__(**kw)
        self.bind(width=lambda *_: setattr(self, "text_size", (self.width, None)))
        self.bind(texture_size=lambda *_: setattr(self, "height", self.texture_size[1] + dp(4)))


class HistRow(Button):
    entry = ObjectProperty(None, allownone=True)

    def on_release(self):
        App.get_running_app().open_history_entry(self.entry)


class ResRow(RecycleDataViewBehavior, BoxLayout):
    index = NumericProperty(0)
    text = StringProperty("")
    checked = BooleanProperty(True)
    bg = ListProperty([1, 1, 1, 0.06])

    def on_check(self, active):
        App.get_running_app().scan_toggle(self.index, active)

    def on_edit(self):
        App.get_running_app().scan_edit(self.index)

    def refresh_view_attrs(self, rv, index, data):
        self.index = index
        return super().refresh_view_attrs(rv, index, data)


def make_rv(viewclass: str, item_height: float) -> RecycleView:
    rv = RecycleView()
    rv.viewclass = viewclass
    layout = RecycleBoxLayout(default_size=(None, dp(item_height)), default_size_hint=(1, None),
                              size_hint_y=None, orientation="vertical", spacing=dp(4))
    layout.bind(minimum_height=layout.setter("height"))
    rv.add_widget(layout)
    return rv


def column() -> BoxLayout:
    return BoxLayout(orientation="vertical", size_hint_y=None, spacing=dp(10), padding=dp(10))


def scrolled(content: BoxLayout) -> ScrollView:
    content.bind(minimum_height=content.setter("height"))
    sv = ScrollView(do_scroll_x=False)
    sv.add_widget(content)
    return sv


def pity_hex(value: int, hard: int) -> str:
    """Цвет гаранта: зелёный -> красный (замена pity_color, которая зависела от QColor)."""
    k = max(0.0, min(1.0, value / float(hard or 1)))
    return "%02x%02x%02x" % (int(80 + 175 * k), int(220 - 150 * k), 90)


def bar(value, maximum, color="ffd740"):
    pb = ProgressBar(max=maximum, value=min(value, maximum), size_hint_y=None, height=dp(10))
    return pb


class Music:
    """Фоновая музыка: громкость и «выключено» хранятся в SQLite (те же ключи, что в десктопе)."""

    def __init__(self, db):
        self.db = db
        path = C.find_music_file()
        self.sound = SoundLoader.load(str(path)) if path else None
        self.volume = int(db.get_setting(C.MUSIC_VOLUME_KEY, str(C.MUSIC_DEFAULT_VOLUME)) or 30)
        self.muted = db.get_setting(C.MUSIC_MUTED_KEY, "0") == "1"
        if self.sound:
            self.sound.loop = True
            self._apply()
            if not self.muted:
                self.sound.play()

    def _apply(self):
        if self.sound:
            self.sound.volume = 0 if self.muted else (self.volume / 100.0) ** 2   # «естественная» шкала

    def set_volume(self, pct: int):
        self.volume = int(pct)
        self.db.set_setting(C.MUSIC_VOLUME_KEY, str(self.volume))
        self._apply()

    def set_muted(self, muted: bool):
        self.muted = muted
        self.db.set_setting(C.MUSIC_MUTED_KEY, "1" if muted else "0")
        if self.sound:
            self._apply()
            if not muted and self.sound.state != "play":
                self.sound.play()

    def pause(self):
        if self.sound and self.sound.state == "play":
            self.sound.stop()

    def resume(self):
        if self.sound and not self.muted and self.sound.state != "play":
            self.sound.play()


class NteApp(App):
    title = "NTE Wish Tracker"

    # ------------------------------------------------------------------ запуск
    def build(self):
        Window.clearcolor = (0.05, 0.06, 0.11, 1)
        Builder.load_string(KV)
        C._DATA_DIR = str(P.user_data_dir())
        self.t = S.Tracker(P.user_data_dir() / C.DB_NAME)
        self.music = Music(self.t.db)
        self.session = None
        self.checked = set()
        self.cancel = False
        self.ocr_ready = not P.ON_ANDROID                  # на ПК работает обычный pytesseract
        self.countdowns = []                               # (Label, entry) — живые таймеры баннеров
        self.pool = C.EVENT_BANNER

        root = BoxLayout(orientation="vertical")
        self.pages = BoxLayout()
        root.add_widget(self.pages)
        nav = BoxLayout(size_hint_y=None, height=dp(54))
        self.screens, self.nav_buttons = {}, {}
        for key, title, builder in (("staff", "Стафф", self._build_staff),
                                    ("history", "История", self._build_history),
                                    ("scan", "Скриншоты", self._build_scan),
                                    ("add", "Добавить", self._build_add),
                                    ("settings", "Настройки", self._build_settings)):
            self.screens[key] = builder()
            btn = ToggleButton(text=title, group="nav", allow_no_selection=False,
                               background_normal="", background_down="",
                               background_color=(1, 1, 1, 0.08), font_size=dp(13))
            btn.bind(on_release=lambda b, k=key: self.show(k))
            self.nav_buttons[key] = btn
            nav.add_widget(btn)
        root.add_widget(nav)
        self.show("staff")
        Window.bind(on_keyboard=self._on_key)
        Clock.schedule_interval(self._tick, 1)
        Clock.schedule_once(lambda _dt: self._startup(), 0.2)
        return root

    def _startup(self):
        P.request_permissions()
        if P.ON_ANDROID:
            threading.Thread(target=self._prepare_ocr, daemon=True).start()
        if not self.t.has_profile:
            self._ask_nickname()
        else:
            self.refresh_all()
        self.load_banners()

    def _prepare_ocr(self):
        try:
            parent = P.ensure_tessdata()
            ocr_android.install(C, str(parent))
            self.ocr_ready = True
        except Exception as e:  # noqa: BLE001
            msg = f"Распознавание недоступно:\n{e}"
            Clock.schedule_once(lambda _dt: self.msg("OCR", msg), 0)

    def show(self, key: str):
        self.pages.clear_widgets()
        self.pages.add_widget(self.screens[key])
        self.nav_buttons[key].state = "down"
        self.current = key

    def _on_key(self, _w, key, *_a):
        if key == 27:                                       # кнопка «Назад»
            if self.current != "staff":
                self.show("staff")
                return True
        return False

    def on_pause(self):
        self.music.pause()
        return True

    def on_resume(self):
        self.music.resume()
        self.load_banners()

    # ------------------------------------------------------------------ диалоги
    def msg(self, title, text):
        box = BoxLayout(orientation="vertical", padding=dp(10), spacing=dp(10))
        sv = ScrollView()
        sv.add_widget(WLabel(text=text))
        box.add_widget(sv)
        ok = GBtn(text="OK")
        box.add_widget(ok)
        pop = Popup(title=title, content=box, size_hint=(0.92, 0.6))
        ok.bind(on_release=pop.dismiss)
        pop.open()

    def ask(self, title, text, on_yes, yes="Да", no="Нет"):
        box = BoxLayout(orientation="vertical", padding=dp(10), spacing=dp(10))
        sv = ScrollView()
        sv.add_widget(WLabel(text=text))
        box.add_widget(sv)
        row = BoxLayout(size_hint_y=None, height=dp(46), spacing=dp(8))
        b_no, b_yes = GBtn(text=no), GBtn(text=yes)
        row.add_widget(b_no)
        row.add_widget(b_yes)
        box.add_widget(row)
        pop = Popup(title=title, content=box, size_hint=(0.92, 0.7), auto_dismiss=False)
        b_no.bind(on_release=pop.dismiss)
        b_yes.bind(on_release=lambda *_: (pop.dismiss(), on_yes()))
        pop.open()

    def prompt(self, title, label, on_ok, initial="", modal=False):
        box = BoxLayout(orientation="vertical", padding=dp(10), spacing=dp(10))
        box.add_widget(WLabel(text=label))
        inp = TextInput(text=initial, multiline=False, size_hint_y=None, height=dp(44))
        box.add_widget(inp)
        ok = GBtn(text="OK")
        box.add_widget(ok)
        pop = Popup(title=title, content=box, size_hint=(0.92, None), height=dp(260),
                    auto_dismiss=not modal)

        def done(*_):
            try:
                on_ok(inp.text)
            except Exception as e:  # noqa: BLE001 — DatabaseError с понятным русским текстом
                self.msg("Ошибка", str(e))
                return
            pop.dismiss()
        ok.bind(on_release=done)
        pop.open()

    def _ask_nickname(self):
        def create(name):
            self.t.create_profile(name)
            self.music.db = self.t.db
            self.refresh_all()
            self.load_banners()
        self.prompt("Первый запуск", "Введите ваш никнейм", create, modal=True)

    # ------------------------------------------------------------------ баннеры
    def load_banners(self):
        def work():
            self.t.fetch_banners()
            Clock.schedule_once(lambda _dt: self.refresh_staff(), 0)
        threading.Thread(target=work, daemon=True).start()

    def _tick(self, _dt):
        """Живой отсчёт: раз в секунду пересчитываем текст по окончанию баннера."""
        now = datetime.now()
        for lbl, entry in self.countdowns:
            text, hint, _kind = C.banner_countdown(entry, now)
            lbl.text = text

    # ------------------------------------------------------------------ обновление
    def refresh_all(self):
        self.t.refresh()
        self.refresh_staff()
        self.refresh_history()
        self.refresh_settings()

    # ------------------------------------------------------------------ «Стафф»
    def _build_staff(self):
        box = BoxLayout(orientation="vertical")
        self.pool_spin = Spinner(text=POOLS[0][1], values=[t for _k, t in POOLS],
                                 size_hint_y=None, height=dp(46))
        self.pool_spin.bind(text=lambda _s, v: self._set_pool(POOL_BY_TITLE[v]))
        self.nick_lbl = Label(text="", size_hint_y=None, height=dp(30), color=(1, 0.84, 0.25, 1))
        box.add_widget(self.nick_lbl)
        box.add_widget(self.pool_spin)
        self.staff_col = column()
        box.add_widget(scrolled(self.staff_col))
        return box

    def _set_pool(self, key):
        self.pool = key
        self.refresh_staff()

    def refresh_staff(self):
        if not self.t.has_profile:
            return
        prof = self.t.db.active_profile() or {"name": ""}
        self.nick_lbl.text = prof["name"]
        col = self.staff_col
        col.clear_widgets()
        self.countdowns = []
        s = self.t.pool_summary(self.pool)

        stats = BoxLayout(size_hint_y=None, height=dp(86), spacing=dp(8))
        for title, value in (("Всего круток", s["total"]), ("Всего S", s["s"]),
                             ("Средний гарант (S)", s["avg_pity"] or "—")):
            card = Glass()
            card.add_widget(WLabel(text=f"[color={MUTED}]{title}[/color]", font_size=dp(11)))
            card.add_widget(WLabel(text=f"[b][color={RANK_COLOR[5]}]{value}[/color][/b]", font_size=dp(22)))
            stats.add_widget(card)
        col.add_widget(stats)

        cards = self.t.banner_cards()
        shown = {C.EVENT_BANNER: cards[0:2], C.ARC_BANNER: cards[2:4], C.STANDARD_BANNER: []}[self.pool]
        for c in shown:
            col.add_widget(self._banner_card(c))
        offline = all(c["kind"] == "none" for c in shown)       # banners.json недоступен — счётчики пула
        if self.pool == C.ARC_BANNER:
            if offline:
                col.add_widget(self._pity_card("Стандартная S дуга", s["counter_std"], C.PITY_ARC_STD))
                col.add_widget(self._pity_card("Ивентовая S дуга", s["counter_ev"], C.PITY_ARC_EVENT))
        else:
            title = "Ивентовый S персонаж" if self.pool == C.EVENT_BANNER else "Стандартный S персонаж"
            if offline or self.pool == C.STANDARD_BANNER:
                col.add_widget(self._pity_card(title, s["counter"], C.PITY_CHAR_HARD, soft=C.PITY_CHAR_SOFT))
        col.add_widget(WLabel(text=f"[color={MUTED}]A: {s['a']}   B: {s['b']}   "
                                   f"Бонусная добыча: {s['bonus']}[/color]"))

    def _pity_card(self, title, value, maximum, soft=None):
        g = Glass()
        extra = f"  (мягкий {soft})" if soft else ""
        g.add_widget(WLabel(text=f"{title}: [b][color={pity_hex(value, maximum)}]{value}/{maximum}[/color][/b]{extra}"))
        g.add_widget(bar(value, maximum))
        return g

    def _banner_card(self, c):
        g = Glass()
        g.add_widget(WLabel(text=f"[color={MUTED}]{c['title']}[/color]", font_size=dp(12)))
        g.add_widget(WLabel(text=f"[b]{c['name']}[/b]", font_size=dp(18)))
        timer = WLabel(text=c["countdown"], font_size=dp(13), color=(0.56, 0.79, 0.98, 1))
        g.add_widget(timer)
        if c.get("entry"):
            self.countdowns.append((timer, c["entry"]))
        if c["name"] in ("Не определён", "Не объявлена"):
            return g
        g.add_widget(WLabel(text=f"Круток за период: [b]{c['pulls']}[/b]   из них S: [b]{c['s']}[/b]"))
        if "pity" in c:
            g.add_widget(self._inline_pity("До гаранта", c["pity"], C.PITY_CHAR_HARD))
        else:
            g.add_widget(self._inline_pity("Стандартная S дуга", c["std"], C.PITY_ARC_STD))
            g.add_widget(self._inline_pity("Ивентовая S дуга", c["ev"], C.PITY_ARC_EVENT))
        return g

    def _inline_pity(self, label, value, maximum):
        box = BoxLayout(orientation="vertical", size_hint_y=None, height=dp(44))
        box.add_widget(WLabel(text=f"{label}: [b][color={pity_hex(value, maximum)}]{value}/{maximum}[/color][/b]"))
        box.add_widget(bar(value, maximum))
        return box

    # ------------------------------------------------------------------ «История»
    def _build_history(self):
        box = BoxLayout(orientation="vertical", padding=dp(8), spacing=dp(6))
        self.hist_filter = Spinner(text="Все пулы", values=["Все пулы"] + [t for _k, t in POOLS],
                                   size_hint_y=None, height=dp(44))
        self.hist_filter.bind(text=lambda *_: self.refresh_history())
        box.add_widget(self.hist_filter)
        self.hist_rv = make_rv("HistRow", 56)
        box.add_widget(self.hist_rv)
        return box

    def refresh_history(self):
        flt = self.hist_filter.text
        key = POOL_BY_TITLE.get(flt)
        data = []
        for e in self.t.history:
            if key and e["banner"] != key:
                continue
            col = RANK_COLOR.get(e["rarity"], RANK_COLOR[3])
            letter = C.rank_letter(e["rarity"])
            data.append({"entry": e, "text": (
                f"[b][color={col}]{letter}[/color][/b]  {e['name']}   "
                f"[size=12sp][color={MUTED}]{e['type']}[/color][/size]\n"
                f"[size=12sp][color={MUTED}]{e['date']} · № {e['n']} · гарант {e['pity']}[/color][/size]")})
        self.hist_rv.data = data

    def open_history_entry(self, e):
        if e:
            self.ask("Запись", f"{e['name']}\n{e['date']}\n\nУдалить запись?",
                     lambda: (self.t.delete_history_item(e), self.refresh_all()), "Удалить", "Отмена")

    # ------------------------------------------------------------------ «Скриншоты»
    def _build_scan(self):
        box = BoxLayout(orientation="vertical", padding=dp(8), spacing=dp(6))
        self.scan_banner = Spinner(text=POOLS[0][1], values=[t for _k, t in POOLS],
                                   size_hint_y=None, height=dp(44))
        self.scan_arc_kind = Spinner(text=C.ARC_KINDS["standard"], values=list(C.ARC_KINDS.values()),
                                     size_hint_y=None, height=dp(44))
        box.add_widget(WLabel(text="Баннер (пул) для найденных записей:"))
        box.add_widget(self.scan_banner)
        box.add_widget(WLabel(text="Тип S дуги (если встретится):"))
        box.add_widget(self.scan_arc_kind)
        row = BoxLayout(size_hint_y=None, height=dp(46), spacing=dp(8))
        b1, b2 = GBtn(text="Галерея"), GBtn(text="Камера")
        b1.bind(on_release=lambda *_: self._need_ocr(lambda: P.pick_images(self._scan_start)))
        b2.bind(on_release=lambda *_: self._need_ocr(lambda: P.take_photo(self._scan_start)))
        row.add_widget(b1)
        row.add_widget(b2)
        box.add_widget(row)
        self.scan_status = WLabel(text=f"[color={MUTED}]Выберите один или несколько скриншотов "
                                       f"истории бросков (порядок определяется автоматически).[/color]")
        box.add_widget(self.scan_status)
        self.scan_progress = ProgressBar(max=1, value=0, size_hint_y=None, height=dp(8))
        box.add_widget(self.scan_progress)
        self.scan_rv = make_rv("ResRow", 58)
        box.add_widget(self.scan_rv)
        row2 = BoxLayout(size_hint_y=None, height=dp(46), spacing=dp(8))
        self.scan_cancel = GBtn(text="Отменить")
        self.scan_cancel.bind(on_release=lambda *_: setattr(self, "cancel", True))
        self.scan_add = GBtn(text="Добавить выбранные (0)")
        self.scan_add.bind(on_release=lambda *_: self.scan_commit())
        row2.add_widget(self.scan_cancel)
        row2.add_widget(self.scan_add)
        box.add_widget(row2)
        return box

    def _need_ocr(self, fn):
        if not self.t.has_profile:
            return self.msg("Профиль", "Сначала создайте профиль.")
        if not self.ocr_ready:
            return self.msg("OCR", "Распознавание ещё готовится (копируются языковые файлы). Повторите через несколько секунд.")
        fn()

    def _scan_start(self, paths):
        if not paths:
            return
        banner = POOL_BY_TITLE[self.scan_banner.text]
        arc_kind = next((k for k, v in C.ARC_KINDS.items() if v == self.scan_arc_kind.text), "standard")
        self.session = S.ScanSession(self.t, paths, banner, arc_kind)
        self.cancel = False
        self.scan_rv.data = []
        P.keep_screen_on(True)
        threading.Thread(target=self._scan_worker, args=(self.session,), daemon=True).start()

    def _scan_worker(self, session):
        def progress(i, total, name):
            Clock.schedule_once(lambda _dt: self._progress(i, total, name), 0)
        try:
            session.scan(progress=progress, cancelled=lambda: self.cancel)
            session.build()                                  # разбор, порядок снимков, хронология
        except Exception as e:  # noqa: BLE001
            err = f"Ошибка обработки:\n{e}"
            Clock.schedule_once(lambda _dt: self.msg("Ошибка", err), 0)
        Clock.schedule_once(lambda _dt: self._scan_done(session), 0)

    def _progress(self, i, total, name):
        self.scan_progress.max, self.scan_progress.value = total, i
        self.scan_status.text = f"Обработано {i} из {total}: {name}"

    def _scan_done(self, session):
        P.keep_screen_on(False)
        self.scan_progress.value = self.scan_progress.max
        if session is not self.session:
            return
        self.checked = set(range(len(session.found)))
        self._fill_scan()
        errs = "\n".join(f"{Path(p).name}: {m}" for p, m in session.errors.items())
        status = f"Найдено записей: {len(session.found)}. Строк для проверки: {session.review_count()}."
        if session.warnings:
            status += "\n⚠ " + "\n⚠ ".join(session.warnings[:6])
        if errs:
            status += "\n" + errs
        self.scan_status.text = status

    def _row_text(self, p):
        col = RANK_COLOR.get(p.get("rarity"), RANK_COLOR[3])
        warn = f"[b][color=ffab40]![/color][/b] " if p.get("needs_review") else ""
        when = p["timestamp"].toString(C.QT_DATE_FMT) if p.get("has_time") else "нет времени"
        name = p.get("display_name") or p.get("name") or p.get("type_text", "")
        return (f"{warn}[b][color={col}]{C.rank_letter(p.get('rarity', 3))}[/color][/b]  {name}\n"
                f"[size=12sp][color={MUTED}]{p.get('type_text', '')} · {when}[/color][/size]")

    def _fill_scan(self):
        found = self.session.found if self.session else []
        self.scan_rv.data = [{"text": self._row_text(p), "checked": i in self.checked,
                              "bg": [1, 0.67, 0.25, 0.22] if p.get("needs_review") else [1, 1, 1, 0.06]}
                             for i, p in enumerate(found)]
        self.scan_add.text = f"Добавить выбранные ({len(self.checked)})"

    def scan_toggle(self, idx, active):
        (self.checked.add if active else self.checked.discard)(idx)
        self.scan_add.text = f"Добавить выбранные ({len(self.checked)})"

    def scan_edit(self, idx):
        """Редактор строки: тип, название, количество, ранг, время (как RowEditorDialog)."""
        p = self.session.found[idx]
        keys = list(C.LOOT_TYPES)
        labels = [C.LOOT_TYPES[k]["label"] for k in keys]
        box = BoxLayout(orientation="vertical", padding=dp(10), spacing=dp(6))
        box.add_widget(WLabel(text=f"[color={MUTED}]Файл: {p.get('file', '')}[/color]"))
        loot = Spinner(text=C.LOOT_TYPES[p["loot"]]["label"], values=labels, size_hint_y=None, height=dp(44))
        name = TextInput(text=p.get("name", ""), multiline=False, size_hint_y=None, height=dp(44),
                         hint_text="Название")
        qty = TextInput(text=str(p.get("qty") or ""), multiline=False, size_hint_y=None, height=dp(44),
                        hint_text="Количество", input_filter="int")
        rank = Spinner(text=C.rank_letter(p.get("rarity", 3)), values=["S", "A", "B"],
                       size_hint_y=None, height=dp(44))
        ts = TextInput(text=p["timestamp"].toString(C.QT_DATE_FMT) if p.get("has_time") else
                       datetime.now().strftime(C.DATE_FMT), multiline=False, size_hint_y=None, height=dp(44))
        incl_row = BoxLayout(size_hint_y=None, height=dp(40))
        incl = Switch(active=True)
        incl_row.add_widget(WLabel(text="Учитывать строку"))
        incl_row.add_widget(incl)
        for w in (loot, name, qty, rank, ts, incl_row):
            box.add_widget(w)
        ok = GBtn(text="Применить")
        box.add_widget(ok)
        pop = Popup(title="Править строку", content=box, size_hint=(0.94, 0.9))

        def apply(*_):
            key = keys[labels.index(loot.text)]
            when = C.QDateTime.fromString(ts.text.strip(), C.QT_DATE_FMT)
            if not when.isValid():
                return self.msg("Время", "Формат: ГГГГ-ММ-ДД ЧЧ:ММ:СС")
            self.session.set_edit(p["path"], p["line"], {
                "loot": key, "name": name.text, "qty": qty.text.strip() or None,
                "rank": {"S": 5, "A": 4, "B": 3}[rank.text], "ts": ts.text.strip(),
                "include": incl.active})
            pop.dismiss()
            self.session.build()
            self.checked = set(range(len(self.session.found)))
            self._fill_scan()
        ok.bind(on_release=apply)
        pop.open()

    def scan_commit(self):
        if not self.session or not self.checked:
            return self.msg("Скриншоты", "Нет отмеченных записей.")
        picked = [self.session.found[i] for i in sorted(self.checked)]
        wishes, rewards = self.session.to_records(picked)
        text = (f"Будет добавлено записей: {len(picked)} (круток: {len(wishes)}, предметов: {len(rewards)}).\n"
                f"Баннер (пул): {C.BANNERS[self.session.banner]}.")
        bonus = sum(1 for r in wishes if r["is_bonus"])
        if bonus:
            text += f"\nБонусная добыча («Подарок за очки»): {bonus} — гарант не меняет."
        no_time = sum(1 for p in picked if not p.get("has_time"))
        if no_time:
            text += f"\n⚠ Время не найдено у записей: {no_time} — будет подставлено текущее."
        already = self.session.already_in_db(wishes, rewards)
        if already:
            text += f"\n⚠ Уже есть в базе с тем же названием и временем: {already}. Возможно, снимок уже добавлялся."
        text += "\n\nДобавить?"

        def go():
            try:
                w, r = self.session.commit(picked)
            except Exception as e:  # noqa: BLE001
                return self.msg("Ошибка", str(e))
            self.session = None
            self.scan_rv.data = []
            self.scan_add.text = "Добавить выбранные (0)"
            self.scan_status.text = f"Добавлено круток: {w}, предметов: {r}"
            self.refresh_all()
        self.ask("Добавить в базу", text, go, "Добавить", "Отмена")

    # ------------------------------------------------------------------ «Добавить» (вручную)
    def _build_add(self):
        col = column()
        self.add_keys = list(C.LOOT_TYPES)
        self.add_labels = [C.LOOT_TYPES[k]["label"] for k in self.add_keys]
        col.add_widget(WLabel(text="Что получено"))
        self.add_loot = Spinner(text=self.add_labels[0], values=self.add_labels, size_hint_y=None, height=dp(46))
        col.add_widget(self.add_loot)
        col.add_widget(WLabel(text="Баннер (пул)"))      # выбор «Дуга» в «Что получено» баннер НЕ меняет
        self.add_banner = Spinner(text=POOLS[0][1], values=[t for _k, t in POOLS], size_hint_y=None, height=dp(46))
        col.add_widget(self.add_banner)
        self.add_name = TextInput(hint_text="Название (необязательно)", multiline=False, size_hint_y=None, height=dp(46))
        self.add_qty = TextInput(hint_text="Количество (для кубиков и фрагментов)", multiline=False,
                                 input_filter="int", size_hint_y=None, height=dp(46))
        self.add_rank = Spinner(text="S", values=["S", "A", "B"], size_hint_y=None, height=dp(46))
        self.add_arc = Spinner(text=C.ARC_KINDS["standard"], values=list(C.ARC_KINDS.values()),
                               size_hint_y=None, height=dp(46))
        self.add_time = TextInput(text=datetime.now().strftime(C.DATE_FMT), multiline=False,
                                  size_hint_y=None, height=dp(46))
        brow = BoxLayout(size_hint_y=None, height=dp(40))
        self.add_bonus = Switch(active=False)
        brow.add_widget(WLabel(text="Бонус (Подарок за очки)"))
        brow.add_widget(self.add_bonus)
        for lbl, w in (("Название", self.add_name), ("Количество", self.add_qty), ("Ранг", self.add_rank),
                       ("Тип S дуги", self.add_arc), ("Время", self.add_time)):
            col.add_widget(WLabel(text=lbl))
            col.add_widget(w)
        col.add_widget(brow)
        btn = GBtn(text="Добавить запись")
        btn.bind(on_release=lambda *_: self._add_manual())
        col.add_widget(btn)
        return scrolled(col)

    def _add_manual(self):
        key = self.add_keys[self.add_labels.index(self.add_loot.text)]
        arc = next((k for k, v in C.ARC_KINDS.items() if v == self.add_arc.text), "standard")
        try:
            self.t.add_manual(key, POOL_BY_TITLE[self.add_banner.text], {"S": 5, "A": 4, "B": 3}[self.add_rank.text],
                              self.add_name.text, self.add_time.text.strip(),
                              qty=self.add_qty.text.strip() or None, is_bonus=self.add_bonus.active, arc_kind=arc)
        except Exception as e:  # noqa: BLE001
            return self.msg("Ошибка", str(e))
        self.refresh_all()
        self.msg("Готово", "Запись добавлена.")

    # ------------------------------------------------------------------ «Настройки»
    def _build_settings(self):
        self.set_col = column()
        return scrolled(self.set_col)

    def refresh_settings(self):
        col = self.set_col
        col.clear_widgets()
        profs = self.t.db.list_profiles() if self.t.has_profile else []
        active = self.t.db.active_profile() or {"name": "—", "id": 0}

        g = Glass()
        g.add_widget(WLabel(text="[b]Профиль[/b]"))
        names = [p["name"] for p in profs]
        spin = Spinner(text=active["name"], values=names, size_hint_y=None, height=dp(44))
        g.add_widget(spin)
        row = BoxLayout(size_hint_y=None, height=dp(44), spacing=dp(6))
        for text, fn in (("Переключить", lambda: self._switch(profs, spin.text)),
                         ("Новый", self._new_profile),
                         ("Имя", lambda: self.prompt("Переименовать", "Новый никнейм",
                                                      lambda n: (self.t.db.rename_profile(active["id"], n),
                                                                 self.refresh_all()), active["name"])),
                         ("Удалить", lambda: self.ask("Удаление", f"Удалить профиль «{active['name']}» "
                                                                  f"со всеми данными?",
                                                      lambda: self._delete_profile(active["id"])))):
            b = GBtn(text=text, font_size=dp(12))
            b.bind(on_release=lambda *_a, f=fn: f())
            row.add_widget(b)
        g.add_widget(row)
        col.add_widget(g)

        g = Glass()
        g.add_widget(WLabel(text="[b]Музыка[/b]"))
        row = BoxLayout(size_hint_y=None, height=dp(44))
        row.add_widget(WLabel(text="Включена"))
        sw = Switch(active=not self.music.muted)
        sw.bind(active=lambda _s, v: self.music.set_muted(not v))
        row.add_widget(sw)
        g.add_widget(row)
        sl = Slider(min=0, max=100, value=self.music.volume, size_hint_y=None, height=dp(40))
        sl.bind(value=lambda _s, v: self.music.set_volume(int(v)))
        g.add_widget(sl)
        if not self.music.sound:
            g.add_widget(WLabel(text=f"[color={MUTED}]Файл assets/audio/bgm.mp3 не найден.[/color]"))
        col.add_widget(g)

        g = Glass()
        g.add_widget(WLabel(text="[b]Данные[/b]"))
        for text, fn in (("Поделиться статистикой (картинка)", self._share_card),
                         ("Экспорт JSON", self._export_json),
                         ("Импорт JSON", self._import_json),
                         ("Резервная копия базы", self._backup),
                         ("Восстановить из копии", self._restore)):
            b = GBtn(text=text)
            b.bind(on_release=lambda *_a, f=fn: f())
            g.add_widget(b)
        col.add_widget(g)

    def _switch(self, profs, name):
        for p in profs:
            if p["name"] == name:
                self.t.switch_profile(p["id"])
                self.refresh_all()
                self.load_banners()

    def _new_profile(self):
        def create(name):
            self.t.create_profile(name)
            self.refresh_all()
        self.prompt("Новый профиль", "Введите никнейм", create)

    def _delete_profile(self, pid):
        try:
            self.t.db.delete_profile(pid)
        except Exception as e:  # noqa: BLE001 — «нельзя удалить последний профиль»
            return self.msg("Ошибка", str(e))
        self.t.db.load_active()
        self.refresh_all()

    def _share_card(self):
        out = str(P.cache_dir() / "share_card.png")
        reg = resource_find("data/fonts/Roboto-Regular.ttf")
        bold = resource_find("data/fonts/Roboto-Bold.ttf")
        render_share_card(self.t, out, reg, bold)
        P.share_file(out, "Статистика NTE")

    def _export_json(self):
        import json
        out = P.cache_dir() / "nte_export.json"
        data = {"wishes": [C.export_wish(r) for r in self.t.rows],
                "rewards": [{k: r[k] for k in C.REWARD_COLS} for r in self.t.rewards]}
        out.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
        P.share_file(str(out), "Экспорт NTE")

    def _import_json(self):
        def done(paths):
            if not paths:
                return
            try:
                p = Path(paths[0])
                aw, sw = self.t.db.import_records(C.load_json_records(p))
                ar, sr = self.t.db.import_rewards(C.load_json_rewards(p))
            except Exception as e:  # noqa: BLE001
                return self.msg("Импорт", f"Не удалось импортировать:\n{e}")
            self.refresh_all()
            self.msg("Импорт", f"Круток добавлено: {aw}, пропущено: {sw}\nПредметов добавлено: {ar}, пропущено: {sr}")
        P.pick_images(done, multiple=False, mime="*/*")

    def _backup(self):
        out = str(P.cache_dir() / "nte_wishes_backup.db")
        try:
            self.t.db.backup_to(out)
        except Exception as e:  # noqa: BLE001
            return self.msg("Копия", str(e))
        P.share_file(out, "Копия базы NTE")

    def _restore(self):
        def done(paths):
            if not paths:
                return

            def go():
                try:
                    self.t.db.restore_from(paths[0])
                    self.t.db.load_active()
                except Exception as e:  # noqa: BLE001
                    return self.msg("Восстановление", str(e))
                self.refresh_all()
            self.ask("Восстановление", "Текущая база будет заменена выбранной копией. Продолжить?", go)
        P.pick_images(done, multiple=False, mime="*/*")


if __name__ == "__main__":
    NteApp().run()

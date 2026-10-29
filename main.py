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
from kivy.uix.checkbox import CheckBox                                      # noqa: E402
from kivy.uix.button import Button                                          # noqa: E402
from kivy.uix.label import Label                                            # noqa: E402
from kivy.uix.popup import Popup                                            # noqa: E402
from kivy.uix.progressbar import ProgressBar                                # noqa: E402,F401
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
from share_card import render_share_card
from services import RANK_HEX, pity_hex
from widgets import WelcomeOverlay, BackgroundLayer, BannerCard, Glass, GBtn, Group, PagedList, Placeholder, WLabel, bar, hex_rgba  # noqa: F401                                    # noqa: E402

RANK_COLOR = {5: "ffd740", 4: "d6a0e0", 3: "90caf9"}        # S золотой, A фиолетовый, B синий
MUTED = "9a9eb0"
POOLS = [(C.EVENT_BANNER, "Ивентовые персонажи"), (C.STANDARD_BANNER, "Стандартные персонажи"),
         (C.ARC_BANNER, "Дуги")]
POOL_BY_TITLE = {t: k for k, t in POOLS}

def column() -> BoxLayout:
    return BoxLayout(orientation="vertical", size_hint_y=None, spacing=dp(10), padding=dp(10))


def scrolled(content: BoxLayout) -> ScrollView:
    content.bind(minimum_height=content.setter("height"))
    sv = ScrollView(do_scroll_x=False)
    sv.add_widget(content)
    return sv


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
        Window.softinput_mode = "below_target"       # клавиатура не закрывает поле ввода
        C._DATA_DIR = str(P.user_data_dir())
        import assets_ascii                           # иконки с русскими именами (u_<hex>.png)
        assets_ascii.install()
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
        from kivy.uix.floatlayout import FloatLayout
        outer = FloatLayout()
        bg = S.Tracker.find_background()
        if bg:                                        # фон: assets/background.* (размытый) + затемнение
            bg = S.Tracker.blurred_background(bg, P.cache_dir())
            outer.add_widget(BackgroundLayer(bg, size_hint=(1, 1), pos_hint={"x": 0, "y": 0}))
        root.size_hint, root.pos_hint = (1, 1), {"x": 0, "y": 0}
        outer.add_widget(root)
        self.outer = outer
        root = outer
        Window.bind(on_keyboard=self._on_key)
        Clock.schedule_interval(self._tick, 1)
        Clock.schedule_once(lambda _dt: self._startup(), 0.2)
        return root

    def _startup(self):
        P.request_permissions()
        if P.ON_ANDROID:
            try:                                  # классы Tesseract надо найти в ГЛАВНОМ потоке
                ocr_android.preload_java()
            except Exception as e:  # noqa: BLE001
                self.msg("OCR", "В APK нет Java-классов Tesseract4Android:\n"
                                f"{type(e).__name__}: {e}")
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

    def ask(self, title, text, on_yes, yes="Да", no="Нет", on_no=None):
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
        b_no.bind(on_release=lambda *_: (pop.dismiss(), on_no() if on_no else None))
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
        """Красивое стартовое окно вместо обычного диалога."""
        def start(nick, then=None):
            name = (nick or "").strip()
            if not name:
                return self.welcome.show_error("Введите никнейм.")
            try:
                self.t.create_profile(name)
            except Exception as e:  # noqa: BLE001 — DatabaseError с понятным русским текстом
                return self.welcome.show_error(str(e))
            self.outer.remove_widget(self.welcome)
            self.welcome = None
            self.refresh_all()
            self.load_banners()
            if then:
                then()
        self.welcome = WelcomeOverlay(on_start=start,
                                      on_import=lambda nick: start(nick, then=self._import_json))
        self.outer.add_widget(self.welcome)

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
        self.nick_lbl = Label(text="", size_hint_y=None, height=dp(34), bold=True,
                              color=(1, 0.88, 0.5, 1), font_size=dp(15))
        box.add_widget(self.nick_lbl)
        tabs = BoxLayout(size_hint_y=None, height=dp(48), spacing=dp(4), padding=(dp(6), 0))
        self.pool_tabs = {}
        for key, title in POOLS:
            b = ToggleButton(text=title, group="pool", allow_no_selection=False, font_size=dp(12),
                             background_normal="", background_down="",
                             background_color=(1, 1, 1, 0.10), halign="center",
                             state="down" if key == self.pool else "normal")
            b.bind(width=lambda w, v: setattr(w, "text_size", (v - dp(8), None)))
            b.bind(on_release=lambda _b, k=key: self._set_pool(k))
            self.pool_tabs[key] = b
            tabs.add_widget(b)
        box.add_widget(tabs)
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
        self.nick_lbl.text = f"Профиль: {prof['name']}"
        for key, b in self.pool_tabs.items():
            b.state = "down" if key == self.pool else "normal"
        col = self.staff_col
        col.clear_widgets()
        self.countdowns = []
        pool = self.pool
        s = self.t.pool_summary(pool)
        is_arc = pool == C.ARC_BANNER
        hide_std = False
        if is_arc:
            hide_std = self.t.db.get_setting("arc_hide_standard", "0", scoped=True) == "1"

        total_s, avg = s["s"], (s["avg_pity"] or "—")
        if is_arc and hide_std:
            total_s, avg = C.arc_event_only_stats(self.t.history)

        stats = BoxLayout(size_hint_y=None, height=dp(92), spacing=dp(8))
        for title, value in (("Всего круток", s["total"]), ("Всего S", total_s),
                             ("Средний гарант (S)", avg)):
            card = Glass()
            card.add_widget(WLabel(text=f"[color={MUTED}]{title}[/color]", font_size=dp(11), halign="center"))
            card.add_widget(WLabel(text=f"[b][color={RANK_COLOR[5]}]{value}[/color][/b]",
                                   font_size=dp(24), halign="center"))
            stats.add_widget(card)
        col.add_widget(stats)

        chips = [(k, C.CUBE_TITLES[k]) for k in C.POOL_CUBES.get(pool, ()) if k != "cube" or s["qty"].get("cube")]
        if chips:
            row = BoxLayout(size_hint_y=None, height=dp(40), spacing=dp(8))
            for kind, title in chips:
                chip = Glass(orientation="horizontal", padding=(dp(10), dp(6)))
                chip.add_widget(WLabel(text=f"{title}: [b]{s['qty'].get(kind, 0)}[/b] шт.", font_size=dp(13)))
                row.add_widget(chip)
            col.add_widget(row)

        cards = self.t.banner_cards(pool, datetime.now())
        for c in cards:
            card = BannerCard(c)
            col.add_widget(card)
            if c.get("entry"):
                self.countdowns.append((card.timer, c["entry"]))
        if pool == C.EVENT_BANNER and not self.t.banner_info and self.t.last_banner_error:
            col.add_widget(WLabel(text=f"[color={MUTED}]banners.json не загружен: "
                                       f"{self.t.last_banner_error}[/color]", font_size=dp(10)))
        if pool == C.STANDARD_BANNER:
            g = Glass()
            g.add_widget(WLabel(text=f"Стандартный S персонаж: [b][color={pity_hex(s['counter'], C.PITY_CHAR_HARD)}]"
                                     f"{s['counter']}/{C.PITY_CHAR_HARD}[/color][/b]  (мягкий {C.PITY_CHAR_SOFT})"))
            g.add_widget(bar(s["counter"], C.PITY_CHAR_HARD))
            col.add_widget(g)

        extra = None
        if is_arc:
            extra = BoxLayout(size_hint_y=None, height=dp(40))
            extra.add_widget(WLabel(text="Скрыть стандартные дуги"))
            sw = Switch(active=hide_std, size_hint_x=None, width=dp(70))
            sw.bind(active=lambda _s, v: (self.t.db.set_setting("arc_hide_standard", "1" if v else "0",
                                                                scoped=True), self.refresh_staff()))
            extra.add_widget(sw)
        empty = "Пока не выпала ни одна дуга S ранга." if is_arc else "Пока не выпал ни один персонаж S ранга."
        col.add_widget(Group("История выпадения S", self.t.drops(pool, hide_std), empty, extra))
        for g in self.t.rosters(pool):
            col.add_widget(Group(g["title"], g["tiles"]))
        col.add_widget(WLabel(text=f"[color={MUTED}]A: {s['a']}   B: {s['b']}   "
                                   f"Бонусная добыча: {s['bonus']}[/color]", font_size=dp(11)))

    # ------------------------------------------------------------------ «История»
    def _build_history(self):
        box = BoxLayout(orientation="vertical", padding=dp(8), spacing=dp(6))
        self.hist_filter = Spinner(text="Все пулы", values=["Все пулы"] + [t for _k, t in POOLS],
                                   size_hint_y=None, height=dp(44))
        self.hist_filter.bind(text=lambda *_: self.refresh_history())
        box.add_widget(self.hist_filter)
        self.hist_count = WLabel(text="", font_size=dp(11))
        box.add_widget(self.hist_count)
        self.hist_list = PagedList(page=40)
        box.add_widget(scrolled(self.hist_list))
        return box

    def refresh_history(self):
        key = POOL_BY_TITLE.get(self.hist_filter.text)
        items = [e for e in self.t.history if not key or e["banner"] == key]
        self.hist_count.text = f"[color={MUTED}]Записей: {len(items)}[/color]"
        self.hist_list.set_items(items, self._history_row, "В этом пуле пока нет записей.")

    def _history_row(self, _i, e):
        row = BoxLayout(size_hint_y=None, height=dp(64), spacing=dp(8), padding=(dp(4), dp(2)))
        icon = self.t.icon(e["name"], e.get("aliases") or (), e["rarity"])
        if icon:
            from kivy.uix.image import Image
            row.add_widget(Image(source=icon, size_hint_x=None, width=dp(52), fit_mode="contain"))
        else:
            ph = Placeholder(e["name"], e["rarity"], size_hint_x=None, width=dp(52))
            row.add_widget(ph)
        col = RANK_COLOR.get(e["rarity"], RANK_COLOR[3])
        btn = Button(background_normal="", background_color=(1, 1, 1, 0.05), markup=True,
                     halign="left", valign="middle",
                     text=(f"[b][color={col}]{C.rank_letter(e['rarity'])}[/color][/b]  {e['name']}\n"
                           f"[size=12sp][color={MUTED}]{e['type']} · {e['date']}[/color][/size]\n"
                           f"[size=12sp][color={MUTED}]№ {e['n']} · гарант {e['pity']} · "
                           f"{C.BANNERS.get(e['banner'], '')}[/color][/size]"))
        btn.bind(size=lambda w, v: setattr(w, "text_size", (v[0] - dp(12), v[1])))
        btn.bind(on_release=lambda *_a, en=e: self.open_history_entry(en))
        row.add_widget(btn)
        return row

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
        self.scan_list = PagedList(page=40)
        box.add_widget(scrolled(self.scan_list))
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
        self.scan_list.set_items([], None, "Идёт распознавание…")
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
        self.scan_list.set_items(list(enumerate(found)), self._scan_row,
                                 "Ничего не распознано. Проверьте, что на скриншоте видна история бросков.")
        self.scan_add.text = f"Добавить выбранные ({len(self.checked)})"

    def _scan_row(self, _i, item):
        idx, p = item
        row = BoxLayout(size_hint_y=None, height=dp(62), spacing=dp(6))
        cb = CheckBox(active=idx in self.checked, size_hint_x=None, width=dp(44))
        cb.bind(active=lambda _c, v, i=idx: self.scan_toggle(i, v))
        row.add_widget(cb)
        flagged = p.get("needs_review")
        btn = Button(text=self._row_text(p), markup=True, halign="left", valign="middle",
                     background_normal="",
                     background_color=(1, 0.67, 0.25, 0.22) if flagged else (1, 1, 1, 0.06))
        btn.bind(size=lambda w, v: setattr(w, "text_size", (v[0] - dp(12), v[1])))
        btn.bind(on_release=lambda *_a, i=idx: self.scan_edit(i))
        row.add_widget(btn)
        return row

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
            self.scan_list.set_items([], None)
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
                         ("Импорт истории с ПК (JSON / CSV / .db)", self._import_json),
                         ("Диагностика (иконки, OCR, баннеры)", self._diagnostics),
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
        """Импорт истории из файла с ПК: JSON / CSV (Экспорт на ПК) или сам файл базы nte_wishes.db."""
        def done(paths):
            if not paths:
                return
            try:
                data = self.t.read_import(paths[0])
            except Exception as e:  # noqa: BLE001
                return self.msg("Импорт", f"Не удалось прочитать файл:\n{type(e).__name__}: {e}")
            if not data["valid"] and not data["valid_rw"]:
                extra = "\n".join(data["errors"][:8])
                return self.msg("Импорт", "В файле не найдено корректных записей." + (f"\n\n{extra}" if extra else ""))
            text = f"Найдено корректных записей: {data['valid']}" if data["kind"] == "db" else \
                   f"Найдено корректных записей: {len(data['valid'])}"
            if data["kind"] == "db":
                text += f"\nПредметов: {data['valid_rw']}\nПрофилей в файле: " + \
                        ", ".join(f"«{p['name']}»" for p in data["profiles"])
            elif data["has_rewards"]:
                text += f"\nНайдено предметов: {len(data['valid_rw'])}"
            if data["kind"] == "file" and not data.get("has_seq"):
                text += ("\n\n⚠ В этом файле нет порядка записей внутри одной секунды (десять круток падают "
                         "одновременно), поэтому цифры гаранта у отдельных S могут отличаться от ПК на "
                         "несколько круток. Для точного совпадения импортируйте файл базы nte_wishes.db.")
            if data["errors"]:
                text += f"\nПропущено с ошибками: {len(data['errors'])}\n" + "\n".join(data["errors"][:4])

            def run(into_current):
                try:
                    report = self.t.apply_import(data, into_current)
                except Exception as e:  # noqa: BLE001
                    return self.msg("Импорт", f"Ошибка импорта:\n{type(e).__name__}: {e}")
                self.refresh_all()
                self.msg("Импорт завершён", report)

            if data["kind"] == "db" and len(data["profiles"]) == 1:
                cur = (self.t.db.active_profile() or {}).get("name", "")
                self.ask("Импорт базы с ПК", text + f"\n\nДобавить в текущий профиль «{cur}»?\n"
                         "(«По именам» — вместо этого создать/дополнить профиль с именем из файла)",
                         lambda: run(True), "В текущий", "По именам", on_no=lambda: run(False))
            else:
                self.ask("Импорт", text + "\n\nИмпортировать? Дубликаты будут пропущены.",
                         lambda: run(True))
        P.pick_images(done, multiple=False, mime="*/*")

    def _diagnostics(self):
        import assets_ascii
        import platform_android as PA
        lines = [f"Иконки и арт:\n{assets_ascii.describe()}"]
        bg = S.Tracker.find_background()
        lines.append(f"\nФон: {'найден' if bg else 'нет файла assets/background.*'}")
        for nm in ("Хотори", "EXE", "Блэкбёрд"):
            ic = self.t.icon(nm, (), 5)
            lines.append(f"Иконка «{nm}»: {'найдена' if ic else 'НЕ найдена'}")
        try:
            td = sorted(f.name for f in (PA.user_data_dir() / "tessdata").glob("*.traineddata"))
        except Exception:  # noqa: BLE001
            td = []
        lines.append(f"\nЯзыки OCR: {', '.join(td) or 'нет'}; готов: {'да' if self.ocr_ready else 'нет'}")
        lines.append(f"Баннеры: {'загружены' if self.t.banner_info else 'нет (' + (self.t.last_banner_error or 'ещё не запрашивались') + ')'}")
        self.msg("Диагностика", "\n".join(lines))

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

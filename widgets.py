"""Виджеты мобильного интерфейса: стеклянные карточки, плитки персонажей, баннер с артом,
постраничный список. Простые виджеты в ScrollView вместо RecycleView: на телефоне
RecycleView у нас не отрисовывался, а списки здесь короткие (страницами по 50 строк)."""
from kivy.lang import Builder
from kivy.metrics import dp
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.floatlayout import FloatLayout
from kivy.uix.image import Image
from kivy.uix.label import Label
from kivy.uix.progressbar import ProgressBar
from kivy.uix.stacklayout import StackLayout

Builder.load_string("""
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
<Tile>:
    orientation: 'vertical'
    size_hint: None, None
    size: dp(78), dp(118)
    padding: dp(4)
    spacing: dp(2)
    canvas.before:
        Color:
            rgba: 1, 1, 1, 0.06 if not root.dim else 0.03
        RoundedRectangle:
            pos: self.pos
            size: self.size
            radius: [dp(10)]
        Color:
            rgba: 1, 1, 1, 0.14 if not root.dim else 0.07
        Line:
            rounded_rectangle: (self.x, self.y, self.width, self.height, dp(10))
            width: 1
""")

from kivy.properties import BooleanProperty                                  # noqa: E402

RANK_RGB = {5: (1, 0.84, 0.25), 4: (0.84, 0.63, 0.88), 3: (0.56, 0.79, 0.98)}


def hex_rgba(h: str, a: float = 1.0):
    return (int(h[0:2], 16) / 255, int(h[2:4], 16) / 255, int(h[4:6], 16) / 255, a)


class Glass(BoxLayout):
    """Карточка «стекло»: полупрозрачная заливка, скругление, светлая рамка."""


class GBtn(Button):
    pass


class WLabel(Label):
    """Подпись с переносом по ширине и автоматической высотой."""
    def __init__(self, **kw):
        kw.setdefault("size_hint_y", None)
        kw.setdefault("markup", True)
        kw.setdefault("halign", "left")
        super().__init__(**kw)
        self.bind(width=lambda *_: setattr(self, "text_size", (self.width, None)))
        self.bind(texture_size=lambda *_: setattr(self, "height", self.texture_size[1] + dp(4)))


def bar(value, maximum, height=10):
    return ProgressBar(max=max(1, maximum), value=min(value, maximum), size_hint_y=None, height=dp(height))


class Placeholder(Label):
    """Когда иконки нет в assets/: цветная плитка с первой буквой имени."""
    def __init__(self, text, rank=5, **kw):
        super().__init__(text=(text or "?")[:1].upper(), bold=True, font_size=dp(24), **kw)
        r, g, b = RANK_RGB.get(rank, RANK_RGB[3])
        self.color = (r, g, b, 1)
        with self.canvas.before:
            from kivy.graphics import Color, RoundedRectangle
            Color(r, g, b, 0.18)
            self._bg = RoundedRectangle(pos=self.pos, size=self.size, radius=[dp(12)])
        self.bind(pos=self._sync, size=self._sync)

    def _sync(self, *_):
        self._bg.pos, self._bg.size = self.pos, self.size


class Tile(BoxLayout):
    """Плитка персонажа/дуги: иконка, имя, значение (гарант или ×N)."""
    dim = BooleanProperty(False)

    def __init__(self, name, value, color_hex, rank=5, icon=None, dim=False, label=None, **kw):
        super().__init__(**kw)
        self.dim = dim
        if icon:
            pic = Image(source=icon, size_hint_y=None, height=dp(64), fit_mode="contain",
                        opacity=0.35 if dim else 1)
        else:
            pic = Placeholder(name, rank, size_hint_y=None, height=dp(64))
            if dim:
                pic.opacity = 0.4
        self.add_widget(pic)
        nm = Label(text=label or name, font_size=dp(11), size_hint_y=None, height=dp(30),
                   halign="center", valign="middle", shorten=True, shorten_from="right",
                   max_lines=2, color=(1, 1, 1, 0.75 if dim else 1))
        nm.bind(width=lambda w, v: setattr(w, "text_size", (v, None)))
        self.add_widget(nm)
        self.add_widget(Label(text=f"[b]{value}[/b]", markup=True, font_size=dp(17),
                              size_hint_y=None, height=dp(22), color=hex_rgba(color_hex)))


class Flow(StackLayout):
    """Плитки с переносом по ширине (аналог FlowLayout на десктопе)."""
    def __init__(self, **kw):
        super().__init__(orientation="lr-tb", spacing=dp(8), size_hint_y=None, **kw)
        self.bind(minimum_height=self.setter("height"))


class Group(Glass):
    """Группа с заголовком и сеткой плиток (QGroupBox из десктопа)."""
    def __init__(self, title, tiles, empty_text="", extra=None, **kw):
        super().__init__(**kw)
        self.add_widget(WLabel(text=f"[b][color=ffe082]{title}[/color][/b]", font_size=dp(14)))
        if extra is not None:
            self.add_widget(extra)
        if tiles:
            flow = Flow()
            for t in tiles:
                flow.add_widget(Tile(t["name"], t["value"], t["color"], t["rank"], t.get("icon"),
                                     t.get("dim", False), t.get("label")))
            self.add_widget(flow)
        elif empty_text:
            self.add_widget(WLabel(text=f"[color=9a9eb0]{empty_text}[/color]", font_size=dp(12)))


class BannerCard(FloatLayout):
    """Плитка баннера: арт «cover» + затемнение + текст; без арта — стеклянная карточка."""
    def __init__(self, c, **kw):
        super().__init__(size_hint_y=None, height=dp(290 if c["arc"] else 240), **kw)
        if c.get("art"):
            self.add_widget(Image(source=c["art"], fit_mode="cover", size_hint=(1, 1),
                                  pos_hint={"x": 0, "y": 0}))
            shade = FloatLayout(size_hint=(1, 1), pos_hint={"x": 0, "y": 0})
            with shade.canvas:
                from kivy.graphics import Color, Rectangle
                Color(0, 0, 0, 0.55)
                self._shade = Rectangle(pos=self.pos, size=self.size)
            self.bind(pos=self._sync, size=self._sync)
            self.add_widget(shade)
        else:
            with self.canvas.before:
                from kivy.graphics import Color, RoundedRectangle
                Color(1, 1, 1, 0.07)
                self._bg = RoundedRectangle(pos=self.pos, size=self.size, radius=[dp(14)])
            self.bind(pos=self._sync_bg, size=self._sync_bg)
        col = BoxLayout(orientation="vertical", padding=dp(12), spacing=dp(3), size_hint=(1, 1),
                        pos_hint={"x": 0, "y": 0})
        col.add_widget(WLabel(text=f"[color=cfd2e0]{c['caption']}[/color]", font_size=dp(11)))
        col.add_widget(WLabel(text=f"[b]{c['name']}[/b]", font_size=dp(21)))
        gold = c["kind"] == "live"
        self.timer = WLabel(text=c["countdown"], font_size=dp(13),
                            color=(1, 0.84, 0.25, 1) if gold else (0.8, 0.82, 0.9, 1))
        col.add_widget(self.timer)
        if c["arc"]:
            if c["entry"] is not None or True:
                from services import pity_hex
                from nte_core import PITY_ARC_EVENT, PITY_ARC_STD
                col.add_widget(WLabel(text=f"Стандартная S дуга: [b][color={pity_hex(c['std'], PITY_ARC_STD)}]"
                                           f"{c['std']}/{PITY_ARC_STD}[/color][/b]", font_size=dp(13)))
                col.add_widget(bar(c["std"], PITY_ARC_STD, 8))
                col.add_widget(WLabel(text=f"Ивентовая S дуга: [b][color={pity_hex(c['ev'], PITY_ARC_EVENT)}]"
                                           f"{c['ev']}/{PITY_ARC_EVENT}[/color][/b]", font_size=dp(13)))
                col.add_widget(bar(c["ev"], PITY_ARC_EVENT, 8))
        else:
            from services import pity_hex
            from nte_core import PITY_CHAR_HARD
            col.add_widget(WLabel(text=f"До гаранта: [b][color={pity_hex(c['pity'], PITY_CHAR_HARD)}]"
                                       f"{c['pity']}/{PITY_CHAR_HARD}[/color][/b]", font_size=dp(14)))
            col.add_widget(bar(c["pity"], PITY_CHAR_HARD, 9))
        for line in c["lines"]:
            col.add_widget(WLabel(text=f"[color=e3e5f0]{line}[/color]", font_size=dp(11)))
        self.add_widget(col)

    def _sync(self, *_):
        self._shade.pos, self._shade.size = self.pos, self.size

    def _sync_bg(self, *_):
        self._bg.pos, self._bg.size = self.pos, self.size


class PagedList(BoxLayout):
    """Вертикальный список строк с кнопкой «Показать ещё» (кладётся внутрь ScrollView)."""
    def __init__(self, page=50, **kw):
        super().__init__(orientation="vertical", size_hint_y=None, spacing=dp(6), **kw)
        self.bind(minimum_height=self.setter("height"))
        self.page, self.items, self.builder, self.shown, self._more_btn = page, [], None, 0, None

    def set_items(self, items, builder, empty_text="Пока пусто."):
        self.items, self.builder, self.shown, self._more_btn = items, builder, 0, None
        self.clear_widgets()
        if not items:
            self.add_widget(WLabel(text=f"[color=9a9eb0]{empty_text}[/color]"))
            return
        self._more()

    def _more(self, *_):
        if self._more_btn is not None:
            self.remove_widget(self._more_btn)
            self._more_btn = None
        end = min(self.shown + self.page, len(self.items))
        for i in range(self.shown, end):
            self.add_widget(self.builder(i, self.items[i]))
        self.shown = end
        if end < len(self.items):
            self._more_btn = GBtn(text=f"Показать ещё ({len(self.items) - end})")
            self._more_btn.bind(on_release=self._more)
            self.add_widget(self._more_btn)


class BackgroundLayer(FloatLayout):
    """Фон приложения (assets/background.*) с затемнением rgba(15, 15, 25, 0.75), как на десктопе.
    Размытия в Kivy нет — вместо него заливка потемнее."""
    def __init__(self, path, **kw):
        super().__init__(**kw)
        self.add_widget(Image(source=path, fit_mode="cover", size_hint=(1, 1), pos_hint={"x": 0, "y": 0}))
        from kivy.graphics import Color, Rectangle
        with self.canvas.after:
            Color(15 / 255, 15 / 255, 25 / 255, 0.75)
            self._shade = Rectangle(pos=self.pos, size=self.size)
        self.bind(pos=self._sync, size=self._sync)

    def _sync(self, *_):
        self._shade.pos, self._shade.size = self.pos, self.size


class WelcomeOverlay(FloatLayout):
    """Стартовое окно первого запуска в общем стиле: стеклянная карточка по центру,
    золотой заголовок, поле никнейма, золотая кнопка и импорт истории с ПК."""
    def __init__(self, on_start, on_import, **kw):
        super().__init__(size_hint=(1, 1), pos_hint={"x": 0, "y": 0}, **kw)
        from kivy.graphics import Color, Rectangle
        from kivy.uix.textinput import TextInput
        with self.canvas.before:
            Color(0.04, 0.05, 0.10, 0.62)
            self._dim = Rectangle(pos=self.pos, size=self.size)
        self.bind(pos=self._sync, size=self._sync)
        card = Glass(size_hint=(0.9, None), pos_hint={"center_x": 0.5, "center_y": 0.55},
                     padding=dp(22), spacing=dp(12))
        card.add_widget(WLabel(text="[b][color=ffd740]NTE[/color]  Wish Tracker[/b]",
                               font_size=dp(30), halign="center"))
        card.add_widget(WLabel(text="[color=b9bdd0]Трекер круток Neverness to Everness[/color]",
                               font_size=dp(13), halign="center"))
        card.add_widget(Label(size_hint_y=None, height=dp(6)))
        card.add_widget(WLabel(text="[color=e3e5f0]Как вас называть?[/color]", font_size=dp(13)))
        self.nick = TextInput(multiline=False, hint_text="Никнейм", size_hint_y=None, height=dp(50),
                              background_normal="", background_active="",
                              background_color=(1, 1, 1, 0.10), foreground_color=(1, 1, 1, 1),
                              hint_text_color=(1, 1, 1, 0.35), cursor_color=(1, 0.84, 0.25, 1),
                              padding=(dp(14), dp(14), dp(14), dp(10)), font_size=dp(17))
        self.nick.bind(on_text_validate=lambda *_: on_start(self.nick.text))
        card.add_widget(self.nick)
        self.err = WLabel(text="", font_size=dp(12), color=(1, 0.5, 0.45, 1))
        card.add_widget(self.err)
        go = Button(text="Начать", bold=True, size_hint_y=None, height=dp(52), font_size=dp(17),
                    background_normal="", background_color=(1, 0.84, 0.25, 1), color=(0.1, 0.1, 0.14, 1))
        go.bind(on_release=lambda *_: on_start(self.nick.text))
        card.add_widget(go)
        imp = GBtn(text="Импортировать историю с ПК", font_size=dp(14))
        imp.bind(on_release=lambda *_: on_import(self.nick.text))
        card.add_widget(imp)
        card.add_widget(WLabel(text="[color=8c90a6]История, гарант и статистика хранятся только на этом телефоне.[/color]",
                               font_size=dp(11), halign="center"))
        self.add_widget(card)

    def show_error(self, text: str) -> None:
        self.err.text = text

    def _sync(self, *_):
        self._dim.pos, self._dim.size = self.pos, self.size

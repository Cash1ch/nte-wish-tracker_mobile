"""АВТОГЕНЕРАЦИЯ: tools/extract_core.py из main.py. Не редактируйте вручную."""
from qt_shim import QDateTime, QColor  # noqa: F401


# ----------------------------------------------------------------------------
# OCR-ФИКС 7: «Страна сна» / «Подарок за очки» — вне гаранта (в истории остаются); гарант
#   персонажей <= 90; «Занку»: «Мереспепх - Sexxy», «персонаж - занку» -> Персонаж, S.
# OCR-ФИКС 6 (единый конвейер ocr_extract_pulls_ex — все три вкладки скриншотов):
#   1) даты: опечатки месяца («4 man.» = май), день-буква («Б май» = 6 мая), день с приклеенной
#      цифрой количества; наследование времени пула (все строки страницы — одна крутка);
#   2) «Ирой»: срез приставших подписей интерфейса («персонажи», «персонажен», цифры …);
#   3) предметы по ключевым словам («кубик», «твердый», «фрагмент», «искривления», «passer»,
#      «reamnear», «fipasere») — всегда предмет, никогда не персонаж;
#   4) полнота страницы (5 записей): строки только со временем, дубль «Потерянного фрагмента».
# ----------------------------------------------------------------------------
import array


import csv


import difflib


import gc


import json


import math


import os


import random


import re


import sqlite3


import sys


import tempfile


import time


import traceback


import wave


from collections import Counter


from contextlib import contextmanager


from datetime import datetime


from pathlib import Path


# НОВОЕ: requests — для запроса текущего баннера. Подключается «мягко»: если пакета нет,
# BannerFetchThread использует стандартный urllib, поэтому приложение запустится в любом случае.
try:
    import requests
except ImportError:
    requests = None


import urllib.request


# Pillow нужен для анализа цвета рамки/фона и подготовки скриншота к OCR,
# pytesseract — для распознавания текста. Оба необязательны: без них остальное
# приложение работает как обычно.
try:
    from PIL import Image, ImageChops, ImageOps, ImageStat
except ImportError:
    Image = None


try:
    import pytesseract
except ImportError:
    pytesseract = None


# НОВОЕ: OpenCV + NumPy — для продвинутой предобработки скриншота перед OCR (увеличение,
# CLAHE, бинаризация, морфология). Необязательны: без них работает упрощённый вариант на Pillow.
try:
    import cv2
    import numpy as np
except ImportError:
    cv2 = None
    np = None


# ----------------------------------------------------------------------------
# Константы
# ----------------------------------------------------------------------------
APP_TITLE = "NTE Wish Tracker — Neverness to Everness"


DB_NAME = "nte_wishes.db"


DATE_FMT = "%Y-%m-%d %H:%M:%S"


QT_DATE_FMT = "yyyy-MM-dd HH:mm:ss"


TIME_SETTING_KEY = "last_pulled_at"  # последнее введённое время формы


TIME_SAVE_DELAY_MS = 600             # задержка записи времени формы в БД


SEARCH_DELAY_MS = 200                # задержка поиска в истории


# ---- НОВОЕ: автоопределение текущего ивентового баннера ----
BANNER_AUTODETECT = True             # False — вообще не ходить в интернет


# Адрес JSON с баннерами. Ожидаемый ответ:
#   {"current_event_banner": "Имя", "event_end_time": "...",
#    "rerun_banner": "Имя", "rerun_end_time": "..."}
# ИСПРАВЛЕНО: раньше в адресе стоял хэш коммита, из-за чего приложение вечно читало СТАРУЮ
# версию файла (без rerun_banner / rerun_end_time). Теперь адрес ведёт на актуальную ветку:
# HEAD — это ветка репозитория по умолчанию; main и master — запасные варианты.
BANNER_REPO_RAW = "https://raw.githubusercontent.com/Cash1ch/nte-banners/"


BANNER_BRANCHES = ("HEAD", "main", "master")


BANNER_FILE = "banners.json"


BANNER_URLS = tuple(f"{BANNER_REPO_RAW}{b}/{BANNER_FILE}" for b in BANNER_BRANCHES)


BANNER_URL = BANNER_URLS[0]          # оставлено для совместимости со старым кодом


BANNER_JSON_KEY = "current_event_banner"  # ключ с названием текущего баннера


BANNER_TIMEOUT = 3                   # секунд на запрос (соединение и чтение)


BANNER_MAX_BYTES = 64 * 1024         # ответ больше этого размера считаем мусором


BANNER_NAME_MAX_LEN = 60             # слишком длинное «имя» — признак мусора


BANNER_USER_AGENT = "NTE-Wish-Tracker/1.0"


# НОВОЕ: сроки баннера. Ключи JSON перебираются по порядку — берётся первый найденный.
BANNER_START_KEYS = ("event_start_time", "start_date", "start_time", "start")


BANNER_END_KEYS = ("event_end_time", "end_date", "end_time", "end")


# Для рерана к этим ключам добавляется префикс «rerun_»: rerun_end_time, rerun_start_time…
BANNER_TICK_MS = 1_000               # как часто обновлять подписи отсчёта (раз в секунду)


# ОБНОВЛЕНО: banners.json перечитывается с GitHub не только при запуске, но и периодически,
# поэтому новые персонажи и новые сроки подхватываются без перезапуска программы.
BANNER_REFRESH_MS = 15 * 60 * 1000   # раз в 15 минут (0 — только при запуске)


BANNER_NO_TIME_TEXT = "Время не указано"


BANNER_ENDED_TEXT = "Баннер завершён"


# НОВОЕ: реран и арт баннеров (вкладка «Стафф»)
# НОВОЕ: в таблице settings хранится момент, когда приложение впервые увидело баннер
# (ключ: banner_activated:<current|rerun>:<имя>). Если в JSON нет даты старта, крутки
# баннера считаются только начиная с этого момента — «задним числом» добавленные
# старые крутки в счётчик периода не попадают.
BANNER_ACTIVATED_PREFIX = "banner_activated:"


BANNER_RERUN_KEYS = ("rerun_banner", "current_rerun_banner", "rerun", "rerun_character",
                     "rerun_name", "rerun_character_banner")


BANNER_CURRENT_KEYS = (BANNER_JSON_KEY, "current_character_banner", "character_banner")


BANNER_CURRENT_DATE_PREFIXES = ("character_", "current_character_")


BANNER_RERUN_DATE_PREFIXES = ("rerun_", "rerun_character_")


BANNER_ARC_KEYS = ("current_arc_banner", "arc_banner", "current_arc", "event_arc_banner",
                   "event_arc", "arc")


BANNER_ARC_RERUN_KEYS = ("rerun_arc_banner", "arc_rerun_banner", "current_rerun_arc_banner",
                         "rerun_arc", "arc_rerun", "rerun_arc_name")


BANNER_ARC_DATE_PREFIXES = ("arc_", "current_arc_", "event_arc_")


BANNER_ARC_RERUN_DATE_PREFIXES = ("rerun_arc_", "arc_rerun_")


BANNER_ART_DIRS = ("banners", "characters")   # где искать арт: сначала banners/, затем characters/


BANNER_CARD_RADIUS = 16                       # скругление плитки баннера, px


BANNER_CARD_MIN_HEIGHT = 220                  # минимальная высота плитки баннера, px


# ---- НОВОЕ: фоновая музыка ----
# Путь к треку относительно папки программы (или папки с базой данных). Можно заменить
# на любой другой файл; если указанного расширения нет — пробуются MUSIC_EXTS.
MUSIC_FILE = "assets/audio/bgm.mp3"


MUSIC_EXTS = (".mp3", ".ogg", ".wav", ".flac", ".m4a", ".aac")


MUSIC_DEFAULT_VOLUME = 30            # громкость по умолчанию, % (фон не должен «орать»)


# НОВОЕ: фоновая анимация вкладки «Стафф» (настройки хранятся в таблице settings)
# НОВОЕ: профили игроков
ACTIVE_PROFILE_KEY = "active_profile_id"   # ключ в settings: id активного профиля


PROFILE_NAME_MAX = 32                      # максимальная длина никнейма


ANIM_ENABLED_KEY = "bg_anim_enabled"   # "1" — анимация включена, "0" — выключена


ANIM_EFFECT_KEY = "bg_anim_effect"     # snow | leaves | stars


ANIM_EFFECTS = (("snow", "Снежинки"), ("leaves", "Листочки"), ("stars", "Звёздочки"))


ANIM_DEFAULT_EFFECT = "snow"


ANIM_FRAME_MS = 33                     # ~30 кадров в секунду


MUSIC_VOLUME_KEY = "music_volume"    # ключ в таблице settings: громкость 0..100


MUSIC_MUTED_KEY = "music_muted"      # ключ в таблице settings: "1" — звук выключен


MUSIC_SAVE_DELAY_MS = 400            # задержка записи громкости в БД (debounce ползунка)


EVENT_BANNER, STANDARD_BANNER, ARC_BANNER = "event_character", "standard_character", "arc"


BANNERS = {
    EVENT_BANNER: "Ивентовый персонаж",
    STANDARD_BANNER: "Стандартный персонаж",
    ARC_BANNER: "Дуга",
}


# Названия подвкладок раздела «Стафф»
POOL_TITLES = {
    EVENT_BANNER: "Ивентовые персонажи",
    STANDARD_BANNER: "Стандартные персонажи",
    ARC_BANNER: "Дуги",
}


RARITIES = (3, 4, 5)


# Ранги редкости. Внутри программы (счётчики, гарант, сравнения «>= A») используется
# число 5 / 4 / 3, а пользователю везде показывается буква:
#   S (бывш. 5★) — золотистый, A (бывш. 4★) — фиолетовый, B (бывш. 3★) — синий.
# В базе SQLite хранится буква (см. Database.add_many / fetch_all).
RANK_LETTERS = {5: "S", 4: "A", 3: "B"}


LETTER_RANKS = {v: k for k, v in RANK_LETTERS.items()}


# Цвета РАМОК В ИГРЕ, по которым OCR определяет ранг на скриншоте (не цвета интерфейса!).
# Рамка ранга B в игре серая, поэтому здесь «серый» оставлен намеренно.
RANK_COLOR_NAMES = {5: "золотистый", 4: "фиолетовый", 3: "серый"}


# Кириллические А и В визуально совпадают с латинскими — принимаем их как A и B
CYR_TO_LAT = str.maketrans({"А": "A", "В": "B"})


def rank_letter(rarity) -> str:
    """Число редкости (5/4/3) -> буква ранга (S/A/B)."""
    return RANK_LETTERS.get(rarity, "?")


def rank_from_db(value) -> int:
    """Значение из БД (буква S/A/B или старое число) -> числовой ранг 5/4/3."""
    text = str(value).strip().upper()
    if text in LETTER_RANKS:
        return LETTER_RANKS[text]
    return int(text) if text.isdigit() else 3


PITY_CHAR_SOFT, PITY_CHAR_HARD = 70, 90   # персонажи: мягкий / жёсткий гарант


PITY_ARC_STD, PITY_ARC_EVENT = 60, 80     # дуги: стандартная / ивентовая S


BONUS_EVERY = 10                          # бонусный A за каждые 10 круток


BONUS_LABEL = "Дополнительная добыча (бонус 10 круток)"


# Предметы (костюм, планер, скин, кубик) лежат на баннере и тратят крутку: True —
# они увеличивают счётчики круток, но никогда не сбрасывают гарант; False — вообще
# не затрагивают счётчики.
ITEMS_COUNT_AS_PULL = True


COUNTERS = ("counter", "counter_std", "counter_ev")


# ---- НОВОЕ: составы персонажей (вкладка «Стафф») ----
ROSTER_EVENT_S = ("Наналли", "Хотори", "Лакримоза", "Хаос", "Шинку", "Ирой", "Занку",
                  "Линко", "Блэкбёрд", "Аканэ Рин", "Элимс", "EXE")


ROSTER_STANDARD_S = ("Сакири", "Даффодил", "Фадия", "Цзююань", "Байканг", "Хатор")


ROSTER_A = ("Ханиэль", "Адлер", "Минт", "Ския", "Эдгар", "Аурелия")


# Какие составы показывает подвкладка пула: баннер -> ((заголовок, ранг 5/4, состав), ...).
# У дуг составов нет. Персонажи A ранга показываются в обоих персонажных пулах.
POOL_ROSTERS = {
    EVENT_BANNER: (("Ивентовые персонажи S ранга", 5, ROSTER_EVENT_S),
                   ("Персонажи A ранга", 4, ROSTER_A)),
    STANDARD_BANNER: (("Стандартные персонажи S ранга", 5, ROSTER_STANDARD_S),
                      ("Персонажи A ранга", 4, ROSTER_A)),
}


DROP_COLUMNS = 7                     # устарело: число плиток в строке теперь определяет FlowLayout по ширине окна


DROP_HISTORY_NEWEST_FIRST = False    # False — от старых к новым (хронология), True — наоборот


# Составы для подсказок/OCR/привязки: {имя в нижнем регистре: (имя, ранг, баннер)}.
# Баннер у A ранга не определён (None) — такие персонажи встречаются в обоих пулах.
ROSTER_KNOWN = {}


for _banner, _groups in POOL_ROSTERS.items():
    for _title, _rarity, _roster in _groups:
        for _name in _roster:
            ROSTER_KNOWN.setdefault(_name.lower(),
                                    (_name, _rarity, _banner if _rarity == 5 else None))


ARC_KINDS = {"standard": "Стандартная дуга", "event": "Ивентовая дуга"}


# НОВОЕ: единый префикс названия дуги. Названия дуг всегда хранятся как «Дуга - Название».
DUGA_PREFIX = "Дуга - "


# НОВОЕ: единый префикс названия планера: «Планер - Название» (как у дуг).
GLIDER_PREFIX = "Планер - "


# ---------------------------------------------------------------------------
# НОВОЕ: МАСТЕР-СПРАВОЧНИКИ для распознавания (OCR, нечёткое сопоставление, подсказки)
# ---------------------------------------------------------------------------
# Полный состав персонажей: ВСЕ ивентовые S, стандартные S и A ранга из кода программы
# (ROSTER_EVENT_S + ROSTER_STANDARD_S + ROSTER_A). Именно он питает match_roster_name /
# ROSTER_FOLDED и список известных имён. Новых персонажей добавляйте в кортежи ROSTER_* выше.
ALL_CHARACTERS = tuple(dict.fromkeys(ROSTER_EVENT_S + ROSTER_STANDARD_S + ROSTER_A))


# Планеры (ранг A — см. FIXED_RARITY["glider"]). Хранятся и показываются как «Планер - Название».
GLIDER_NAMES = (
    "Предвестник", "Суперпризрак", "Алая лента", "Овцелёт", "Пасмурный навес",
    "Небесный всадник", "Томатный дуэт", "Орхидеевый бриз", "Младший босс младшего босса",
)


# Дуги A ранга. Хранятся как «Дуга - Название»; ранг A подставляется по справочнику.
ARC_A_NAMES = (
    "Зонтик", "Космический восторг", "Блестящие дни", "Забытые", "Забытое", "Ора-Ора!",
    "Королевство разума!", "Великий вор", "Берегите головы!", "Чистое небо",
    "Я подожду тебя с жестокостью в сердце", "Обнаженный клинок", "Время придёт",
    "Бандит времени", "Зов искаженного города",
)


# НОВОЕ: дуги B ранга (серые). Хранятся как «Дуга - Название»; ранг B подставляется по справочнику,
# но цвет текста на скриншоте остаётся главным: фиолетовая/золотая дуга сохранит свой ранг.
# ИСПРАВЛЕНО: добавлены дуги «Будь счастлив» и «Мы.» — раньше их не было в справочнике, поэтому
# OCR не мог их исправить, а искажённое «Мы.» превращалось в персонажа «Минт».
ARC_B_NAMES = ("Опасная игра", "Настоящая музыка", "Будь счастлив", "Мы.", "Первый шаг к успеху")


# НОВОЕ: дуги S ранга и костюмы. В коде их пока нет — впишите названия сюда (или в файл
# master_names.json, см. «МАСТЕР-СПРАВОЧНИК» ниже): OCR будет находить их в строке и
# исправлять опечатки; ранг S у дуги подставится по справочнику.
# Стандартные дуги S ранга (стандартный пул дуг)
ARC_S_STANDARD_NAMES = (
    "Вечный вальс", "Сообщество Камелии", "Большой квест хорошего мальчика", "Слезы за маской",
    "Песнь кита", "Бушующее пламя", "Звёздная вуаль", "Ребяческая фантазия",
    "Убежище реальности", "Взорвать толпу",
)


# Ивентовые дуги S ранга (ивентовый пул дуг)
ARC_S_EVENT_NAMES = (
    "Заветное желание", "Алеющий мираж", "Ненасытный клинок", "Преступление и наказание",
    "Голос странника", "Полная готовность", "Неверные врата", "Последняя роза",
    "Обратная сторона Луны", "За пределы времени",
)


ARC_S_NAMES = ARC_S_STANDARD_NAMES + ARC_S_EVENT_NAMES


# {название дуги S: "standard" / "event"} — тип S дуги определяется по названию
ARC_S_KIND_BY_NAME = {**{n.lower(): "standard" for n in ARC_S_STANDARD_NAMES},
                      **{n.lower(): "event" for n in ARC_S_EVENT_NAMES}}


def arc_kind_by_name(name: str, default: str = "") -> str:
    """Тип S дуги («standard» / «event») по названию из справочника; иначе default."""
    key = re.sub(r"^\s*(?:дуга|arc|weapon)\s*[-:–—]\s*", "", str(name or ""), flags=re.I)
    return ARC_S_KIND_BY_NAME.get(key.strip().lower(), default)


def arc_short_name(name) -> str:
    return re.sub(r"^\s*(?:дуга|arc|weapon)\s*[-:–—]\s*", "", str(name or ""),
                  flags=re.I).strip()


def arc_full_name(name) -> str:
    short = arc_short_name(name)
    return f"{DUGA_PREFIX}{short}" if short else ""


BANNER_PANEL_KEYS = (EVENT_BANNER, ARC_BANNER)


ARC_POOL_ROSTERS = {
    ARC_BANNER: (
        ("Ивентовые дуги S ранга", 5, tuple(f"{DUGA_PREFIX}{n}" for n in ARC_S_EVENT_NAMES)),
        ("Стандартные дуги S ранга", 5, tuple(f"{DUGA_PREFIX}{n}" for n in ARC_S_STANDARD_NAMES)),
        ("Дуги A ранга", 4, tuple(f"{DUGA_PREFIX}{n}" for n in dict.fromkeys(ARC_A_NAMES)
                                  if n != "Забытые")),
    ),
}


# ИСПРАВЛЕНО (костюмы): единый префикс названия костюма: «Костюм - Название» (как у дуг и планеров).
# Тип записи у костюма ВСЕГДА «Костюм» (вид outfit, ранг S) — он никогда не становится персонажем.
OUTFIT_PREFIX = "Костюм - "


OUTFIT_RANK = 5          # костюмы — ранг S (золотой), см. FIXED_RARITY["outfit"]


# Все известные костюмы игры (без префикса). Новые костюмы добавляйте сюда или в
# master_names.json (ключ "outfits"): они сразу попадут в мастер-справочник с типом «Костюм».
OUTFIT_NAMES = (
    "Осенняя виньетка", "Сёрфинг среди звёзд", "Красное и чёрное", "Бесценная орхидея",
    "Архимаг", "Удар феникса", "Позолоченная рапсодия", "Чистое небо", "Ученица Терраси",
)


# Как ROSTER_KNOWN: {«дуга - название» в нижнем регистре: (название, ранг, баннер)}. Попадает в
# подсказки названий, автоопределение ранга и список «известных» имён OCR.
ARC_KNOWN = {f"{DUGA_PREFIX}{n}".lower(): (f"{DUGA_PREFIX}{n}", 5, ARC_BANNER)
             for n in ARC_S_NAMES}


ARC_KNOWN.update({f"{DUGA_PREFIX}{n}".lower(): (f"{DUGA_PREFIX}{n}", 3, ARC_BANNER)
                  for n in ARC_B_NAMES})


ARC_KNOWN.update({f"{DUGA_PREFIX}{n}".lower(): (f"{DUGA_PREFIX}{n}", 4, ARC_BANNER)
                  for n in ARC_A_NAMES})


# ИСПРАВЛЕНО (костюмы): {«костюм - название» в нижнем регистре: (название, ранг S, баннер None)}.
# Попадает в список «известных» имён OCR, поэтому костюм не считается «неизвестным именем».
OUTFIT_KNOWN = {f"{OUTFIT_PREFIX}{n}".lower(): (f"{OUTFIT_PREFIX}{n}", OUTFIT_RANK, None)
                for n in OUTFIT_NAMES}


# Баннеры из старых версий программы -> новые ключи
LEGACY_BANNERS = {"limited_character": EVENT_BANNER, "standard": STANDARD_BANNER,
                  "weapon": ARC_BANNER}


# Баннер «Новичковый» удалён: его записи остаются в базе, но скрыты.
REMOVED_BANNERS = {"beginner", "newbie", "novice", "newcomer", "новичковый"}


# Кешбэк — крутка со своей жёсткой редкостью (лежит в общей истории круток)
CASHBACK_TYPES = {"regular": "Обычный", "premium": "Премиальный"}


CASHBACK_RARITY = {"regular": 3, "premium": 4}


# Предметы (таблица rewards): тип -> название. «cube» (старый общий кубик), «arc»,
# «character» и «cashback» оставлены для чтения старых записей/экспортов.
REWARD_KINDS = {
    "solid_cube": "Твердый кубик", "trick_cube": "Шулерский кубик", "outfit": "Костюм",
    "glider": "Планер", "paint": "Окраска", "car_skin": "Скин на авто",
    "lost_fragment": "Потерянный фрагмент", "warp_fragment": "Фрагмент искривления",
    "cube": "Кубик", "arc": "Дуга", "character": "Персонаж", "cashback": "Кешбэк",
}


# Жёсткая редкость предметов.
# ИСПРАВЛЕНО: S (5, золотой) раньше стоял у кубиков, фрагментов и окраски — из-за этого обычные
# предметы показывались с золотым фоном. Теперь S остаётся только у настоящих «легендарных»
# предметов (костюм, скин на авто); персонажи и дуги получают ранг по своим правилам отдельно.
#   A (4, фиолетовый): кубики (твёрдый, шулерский, старый общий), планер, окраска;
#   B (3, синий):      фрагменты (потерянный, искривления).
# При необходимости поменяйте число (5 = S, 4 = A, 3 = B) — на старые записи в базе это
# подействует сразу: редкость предметов нигде не хранится, а считается по этой таблице.
FIXED_RARITY = {
    "solid_cube": 4, "trick_cube": 4, "cube": 4, "outfit": 5, "glider": 4, "paint": 4,
    "car_skin": 5, "lost_fragment": 3, "warp_fragment": 3,
}


LEGACY_REWARD_RARITY = {"character": 5, "arc": 4, "cashback": 3}


# Предметы с количеством: допустимые значения (хранятся в поле detail)
QTY_OPTIONS = {
    "solid_cube": ("1", "5"), "trick_cube": ("1", "5"), "cube": ("1", "5"),
    "lost_fragment": ("30", "50"), "warp_fragment": ("30", "16", "4"),
}


# Виды, у которых количество может быть любым числом (Фрагмент искривления в игре бывает
# 4, 16, 30 и др.): список QTY_OPTIONS — лишь подсказки для формы, OCR берёт значение с экрана.
QTY_FREE_KINDS = {"warp_fragment"}


def qty_is_valid(kind: str, value) -> bool:
    """Допустимо ли количество предмета: из списка QTY_OPTIONS либо (для свободных видов)
    любое число 1…999."""
    v = str(value or "").strip()
    if v in QTY_OPTIONS.get(kind, ()):
        return True
    return kind in QTY_FREE_KINDS and v.isdigit() and 0 < int(v) <= 999


def pick_item_qty(info: dict, qty) -> str:
    """Количество записи предмета по описанию вида (LOOT_TYPES) и значению с экрана."""
    opts = info.get("qty") or ()
    v = str(qty or "").strip()
    if v in opts:
        return v
    if info.get("qty_free") and v.isdigit() and 0 < int(v) <= 999:
        return v
    return opts[0] if opts else ""


# Предметы с привязкой к персонажу (имя персонажа хранится в поле detail)
BIND_KINDS = {"outfit", "glider", "paint"}


# Предметы вне гаранта: в базе помечаются флагом no_pity и не прибавляют счётчик круток
NO_PITY_KINDS = {"warp_fragment"}


def _loot(label, mode, default, **extra):
    """Тип добычи в форме. mode: wish — крутка; cashback — крутка с фикс. редкостью;
    reward — предмет с фикс. редкостью. Необязательные ключи:
    name_label — подпись поля названия; hide_name — поле названия не нужно;
    bind — есть привязка к персонажу; qty — варианты количества; no_pity — вне гаранта."""
    return {"label": label, "mode": mode, "default": default, **extra}


# Порядок = порядок в выпадающем списке «Что получено»
LOOT_TYPES = {
    "character": _loot("Персонаж", "wish", "Персонаж",
                       name_label="Имя персонажа (необязательно):"),
    "arc":       _loot("Дуга", "wish", "Дуга", name_label="Название дуги (необязательно):"),
    "solid1": _loot("Предмет - Твердый кубик 1 шт", "reward", "Твердый кубик (1 шт)",
                    kind="solid_cube", detail="1", hide_name=True),
    "solid5": _loot("Предмет - Твердый кубик 5 шт", "reward", "Твердый кубик (5 шт)",
                    kind="solid_cube", detail="5", hide_name=True),
    "trick1": _loot("Предмет - Шулерский кубик 1 шт", "reward", "Шулерский кубик (1 шт)",
                    kind="trick_cube", detail="1", hide_name=True),
    "trick5": _loot("Предмет - Шулерский кубик 5 шт", "reward", "Шулерский кубик (5 шт)",
                    kind="trick_cube", detail="5", hide_name=True),
    "outfit": _loot("Костюм", "reward", "Костюм", kind="outfit", bind=True,
                    name_label="Название костюма:"),
    "glider": _loot("Планер", "reward", "Планер", kind="glider", bind=True,
                    name_label="Название планера:"),
    "paint":  _loot("Детали модификации - Окраска", "reward", "Окраска", kind="paint",
                    bind=True, name_label="Название окраски:"),
    "lost_fragment": _loot("Предмет - Потерянный фрагмент", "reward", "Потерянный фрагмент",
                           kind="lost_fragment", qty=("30", "50"), hide_name=True),
    "warp_fragment": _loot("Предмет - Фрагмент искривления", "reward", "Фрагмент искривления",
                           kind="warp_fragment", qty=("30", "16", "4"), qty_free=True, hide_name=True,
                           no_pity=True),
    # Не вошли в новое ТЗ, но оставлены, чтобы не терять ввод скинов и кешбэка:
    "car_skin":   _loot("Скин на авто", "reward", "Скин на авто", kind="car_skin"),
    "cb_regular": _loot("Кешбэк (Обычный)", "cashback", "Обычный кешбэк", cashback="regular"),
    "cb_premium": _loot("Кешбэк (Премиальный)", "cashback", "Премиальный кешбэк",
                        cashback="premium"),
}


# Типы, которых нет в списке «Что получено» формы «Ручная» (остаются для OCR и уже записанной истории)
MANUAL_HIDDEN_LOOT = ("car_skin", "cb_regular", "cb_premium")


def loot_rarity(info: dict):
    """Жёсткая редкость типа добычи или None, если редкость выбирается вручную."""
    if info["mode"] == "reward":
        return FIXED_RARITY[info["kind"]]
    if info["mode"] == "cashback":
        return CASHBACK_RARITY[info["cashback"]]
    return None


def loot_aliases(key) -> tuple:
    """НОВОЕ: имена-синонимы для поиска иконки типа добычи: полное название записи,
    название типа, ключ вида (solid_cube) и ключ формы (solid5). Любой из этих файлов
    в assets/ (например, items/solid_cube.png) подойдёт."""
    info = LOOT_TYPES.get(key)
    if info is None:
        return ()
    names = [info["default"], info["label"], info.get("kind"), key]
    if info.get("cashback"):
        names.append(f"cashback_{info['cashback']}")
    return tuple(n for n in names if n)


WISH_COLS = ("banner", "rarity", "name", "pulled_at", "is_bonus", "arc_kind", "cashback")


# OCR-ФИКС: «rarity» — ранг предмета, выбранный по цвету текста на скриншоте (буква S/A/B);
# пусто — ранг берётся по виду предмета (FIXED_RARITY)
REWARD_COLS = ("kind", "name", "detail", "obtained_at", "banner", "no_pity", "rarity")


def reward_rarity_to_db(value) -> str:
    """OCR-ФИКС: ранг предмета для базы — буква S/A/B или пустая строка (число 5/4/3, буква
    и кириллические А/В принимаются; всё остальное — «не задан»)."""
    if value in (None, "") or isinstance(value, bool):
        return ""
    if isinstance(value, int):
        return RANK_LETTERS.get(value, "")
    text = str(value).strip().upper().translate(CYR_TO_LAT)
    if text in LETTER_RANKS:
        return text
    return RANK_LETTERS.get(int(text), "") if text.isdigit() else ""


def _reward_row(r: dict) -> dict:
    """Запись предмета для INSERT: поле rarity всегда присутствует (по умолчанию пустое)."""
    return dict(r, rarity=reward_rarity_to_db(r.get("rarity")))


# Цвета рангов в интерфейсе — S золотистый, A фиолетовый, B синий. Эти же цвета
# используют иконки, плашки наград и выпадающие списки рангов.
RARITY_COLORS = {5: "#ffd740", 4: "#b66cff", 3: "#42a5f5"}


# Цвета строк таблицы (фон, текст)
ROW_COLORS = {
    5: (QColor(255, 193, 7, 70), QColor(255, 215, 64)),
    4: (QColor(156, 39, 176, 70), QColor(214, 160, 224)),
    3: (QColor(33, 150, 243, 45), QColor(144, 202, 249)),
}


ICON_EXTS = (".png", ".jpg", ".jpeg", ".webp")


ICON_DIR_NAMES = ("assets", "icons")


# НОВОЕ: подпапки внутри assets/ и icons/ (пустая строка — сама папка)
ICON_SUBDIRS = ("", "characters", "arcs", "items")


class DatabaseError(Exception):
    """Ошибка работы с базой данных (с понятным текстом для пользователя)."""


class OcrError(Exception):
    """Ошибка распознавания скриншота (с понятным текстом для пользователя)."""


@contextmanager
def blocked(*widgets):
    """Временно отключает сигналы виджетов. Используется при программном
    изменении полей формы, чтобы не запускать лишние пересчёты предпросмотра."""
    for w in widgets:
        w.blockSignals(True)
    try:
        yield
    finally:
        for w in widgets:
            w.blockSignals(False)


# ----------------------------------------------------------------------------
# Работа с путями
# ----------------------------------------------------------------------------
_DATA_DIR = None  # папка с базой данных (задаётся в main), тоже ищем в ней иконки


def app_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent


def resolve_db_path() -> Path:
    base = app_dir()
    try:
        test = base / ".write_test"
        test.touch()
        test.unlink()
        return base / DB_NAME
    except OSError:
        fallback = Path.home() / "NTE Wish Tracker"
        fallback.mkdir(parents=True, exist_ok=True)
        return fallback / DB_NAME


def asset_dirs() -> list:
    """ИЗМЕНЕНО: помимо assets/ и icons/ просматриваются и подпапки из ICON_SUBDIRS
    (characters/, arcs/, items/)."""
    roots = [app_dir()] + ([Path(_DATA_DIR)] if _DATA_DIR is not None else [])
    dirs = []
    for root in roots:
        for name in ICON_DIR_NAMES:
            for sub in ICON_SUBDIRS:
                d = root / name / sub if sub else root / name
                if d not in dirs:
                    dirs.append(d)
    return dirs


def find_music_file():
    """НОВОЕ: ищет файл фоновой музыки. Сначала берётся MUSIC_FILE как есть, затем
    файл с тем же именем и любым расширением из MUSIC_EXTS. Ищем рядом со скриптом и
    рядом с базой данных. Возвращает Path или None, если файла нет."""
    rel = Path(MUSIC_FILE)
    roots = [app_dir()] + ([Path(_DATA_DIR)] if _DATA_DIR is not None else [])
    for root in roots:
        base = root / rel
        names = [base] + [base.with_suffix(ext) for ext in MUSIC_EXTS]
        for p in names:
            try:
                if p.is_file():
                    return p
            except OSError:
                continue
    return None


# ----------------------------------------------------------------------------
# Иконки
# ----------------------------------------------------------------------------
_PATH_CACHE = {}


_ICON_CACHE = {}


_ICON_DPR_OVERRIDE = None   # временно задаётся при экспорте «Поделиться» (сверх-разрешение)


def _name_variants(name: str) -> list:
    safe = re.sub(r'[\\/:*?"<>|]', "", name.strip())
    slug = re.sub(r"\W+", "_", safe.lower(), flags=re.UNICODE).strip("_")
    candidates = [safe, safe.lower(), safe.replace(" ", "_"), safe.lower().replace(" ", "_"),
                  safe.replace(" ", "-"), safe.lower().replace(" ", "-"), slug]
    return list(dict.fromkeys(c for c in candidates if c))


def _search_icon(name: str):
    variants = _name_variants(name)
    lowered = {v.lower() for v in variants}
    for d in asset_dirs():
        if not d.is_dir():
            continue
        for v in variants:
            for ext in ICON_EXTS:
                if (d / (v + ext)).is_file():
                    return d / (v + ext)
        try:
            for p in d.iterdir():
                if p.suffix.lower() in ICON_EXTS and p.stem.lower() in lowered:
                    return p
        except OSError:
            pass
    return None


def icon_candidates(name: str, aliases=()) -> list:
    """НОВОЕ: список имён для поиска иконки по порядку важности: само название, затем
    синонимы. Для каждого имени добавляется вариант без префикса «Дуга - » и без
    скобок с количеством: «Дуга - Клинок» -> «Клинок», «Твердый кубик (5 шт)» ->
    «Твердый кубик»."""
    out = []
    for n in (name, *aliases):
        n = (n or "").strip()
        if not n:
            continue
        out.append(n)
        short = re.sub(r"^(?:Дуга|Планер)\s*-\s*", "", n)
        short = re.sub(r"\s*\([^)]*\)\s*$", "", short).strip()
        if short and short != n:
            out.append(short)
    return list(dict.fromkeys(out))


GENERIC_ARC_ICON_NAMES = ("Дуга", "default_arc", "arc_generic")


_ARC_AB_SHORT = {n.lower() for n in (*ARC_A_NAMES, *ARC_B_NAMES)}


_ARC_S_SHORT = {n.lower() for n in ARC_S_NAMES}


def is_generic_arc(name, aliases=(), rarity=None) -> bool:
    """Дуга A или B ранга -> True (используется единая общая иконка дуги).
    Дуги S ранга всегда сохраняют свои уникальные иконки."""
    if rarity == 5:
        return False
    for n in (name, *aliases):
        raw = str(n or "").strip()
        if not raw:
            continue
        short = arc_short_name(raw).strip().lower()
        has_prefix = raw.lower().startswith(DUGA_PREFIX.lower().strip()) or short != raw.lower()
        if short in _ARC_S_SHORT and has_prefix:
            return False
        if has_prefix:
            if short in _ARC_S_SHORT:
                return False
            if short in _ARC_AB_SHORT or rarity in (3, 4):
                return True
        known = ARC_KNOWN.get(raw.lower())
        if known is not None:
            return known[1] in (3, 4)
        if raw.lower() == "дуга" and rarity in (3, 4):
            return True
    return False


def find_generic_arc_icon_path():
    key = ("__generic_arc__",)
    if key not in _PATH_CACHE:
        _PATH_CACHE[key] = next((p for p in map(_search_icon, GENERIC_ARC_ICON_NAMES) if p), None)
    return _PATH_CACHE[key]


def find_icon_path(name: str, aliases=(), rarity=None):
    """Ищет файл иконки по названию (и синонимам) в assets/ и icons/ вместе с
    подпапками. Возвращает Path или None. Для дуг A и B ранга всегда возвращается
    единая общая иконка (default_arc / arc_generic); уникальные иконки — только у S."""
    aliases = tuple(aliases)
    if is_generic_arc(name, aliases, rarity):
        return find_generic_arc_icon_path()
    names = tuple(icon_candidates(name, aliases))
    if names not in _PATH_CACHE:
        _PATH_CACHE[names] = next((p for p in map(_search_icon, names) if p), None)
    return _PATH_CACHE[names]


def _initials(name: str) -> str:
    words = re.findall(r"\w+", name or "", flags=re.UNICODE)
    if not words:
        return "?"
    return words[0][:2].upper() if len(words) == 1 else (words[0][0] + words[1][0]).upper()


# НОВОЕ: параметры «стеклянных» иконок
ICON_RADIUS_RATIO = 0.25     # радиус скругления = 25 % стороны (56 px -> 12 px)


ICON_SHADOW_MIN_SIZE = 40    # у иконок меньше этого размера тени нет (не уменьшать картинку)


# ----------------------------------------------------------------------------
# Названия и описания предметов
# ----------------------------------------------------------------------------
def default_reward_name(kind: str, detail: str = "") -> str:
    """Название предмета, подставляемое, если пользователь не ввёл своё."""
    if kind in QTY_OPTIONS:
        return f"{REWARD_KINDS[kind]} ({detail or '?'} шт)"
    if kind == "cashback":
        return {"regular": "Обычный кешбэк", "premium": "Премиальный кешбэк"}.get(detail, "Кешбэк")
    return REWARD_KINDS.get(kind, kind)


def reward_display_name(r: dict) -> str:
    return (r.get("name") or "").strip() or default_reward_name(r["kind"], r.get("detail", ""))


def reward_detail_text(r: dict) -> str:
    """Короткое пояснение к предмету: количество, привязка к персонажу или тип кешбэка."""
    kind, detail = r["kind"], r.get("detail", "")
    if kind in QTY_OPTIONS:
        return f"×{detail}"
    if kind in BIND_KINDS:
        return f"→ {detail}" if detail else ""
    if kind == "cashback":
        return CASHBACK_TYPES.get(detail, detail)
    return ""


def reward_rarity(r: dict) -> int:
    # OCR-ФИКС: ранг, выбранный по цвету текста на скриншоте, важнее ранга вида предмета
    override = reward_rarity_to_db(r.get("rarity"))
    if override:
        return LETTER_RANKS[override]
    kind = r["kind"]
    if kind in FIXED_RARITY:
        return FIXED_RARITY[kind]
    if kind == "cashback":
        return CASHBACK_RARITY.get(r.get("detail"), 3)
    return LEGACY_REWARD_RARITY.get(kind, 3)


def wish_kind_label(r: dict) -> str:
    """НОВОЕ: вид крутки для колонки «Тип» — «Дуга» или «Персонаж».
    Сначала смотрим на название (префикс «Дуга - » или заглушка «Дуга»), затем на баннер:
    на баннере «Дуга» выпадают дуги, на остальных — персонажи."""
    name = (r.get("name") or "").strip()
    if name == "Дуга" or name.startswith(DUGA_PREFIX) or r.get("banner") == ARC_BANNER:
        return "Дуга"
    return "Персонаж"


def wish_type_text(r: dict) -> str:
    """Текст колонки «Тип» в истории. ИСПРАВЛЕНО: раньше у обычных круток колонка была
    пустой — теперь везде указан вид («Персонаж» / «Дуга»); у бонусной добычи — «Бонус
    (10 круток) · Дуга», у S дуг — «Стандартная дуга» / «Ивентовая дуга»."""
    if r.get("is_bonus"):
        return f"{BONUS_TYPE_PREFIX} - {wish_kind_label(r)}"   # OCR-ФИКС 3: «Бонус (10 круток) - Дуга»
    if r.get("cashback"):
        return f"Кешбэк: {CASHBACK_TYPES.get(r['cashback'], r['cashback'])}"
    if r["banner"] == ARC_BANNER and r["rarity"] == 5:
        return ARC_KINDS.get(r.get("arc_kind") or "", "Дуга S")
    return wish_kind_label(r)


def _safe_int(value, default=0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def fmt_avg(values: list) -> str:
    return f"{sum(values) / len(values):.1f}" if values else "—"


def arc_event_only_stats(history: list) -> tuple:
    """(число ивентовых S-дуг, средний гарант по ним) — для режима «скрыть стандартные дуги».
    Гарант ивентовой дуги — крутки от прошлой ивентовой (стандартная S не сбрасывает)."""
    pulls = [int(e.get("ce") or 0) for e in history
             if e["banner"] == ARC_BANNER and e["kind"] == "main" and e["rarity"] == 5
             and arc_kind_by_name(e.get("name"), e.get("arc_kind") or "") == "event"]
    return len(pulls), fmt_avg(pulls)


# ----------------------------------------------------------------------------
# Нормализация записей (импорт из CSV/JSON/логов)
# ----------------------------------------------------------------------------
def _alias_map(labels: dict, extra: dict = None) -> dict:
    """Словарь «любое написание (в нижнем регистре) -> ключ»."""
    m = {k: k for k in labels}
    m.update({v.lower(): k for k, v in labels.items()})
    for key, words in (extra or {}).items():
        m.update({w: key for w in words})
    return m


BANNER_MAP = _alias_map(BANNERS, {
    EVENT_BANNER: ("limited", "character", "char", "event", "event_char", "limited_char"),
    STANDARD_BANNER: ("permanent", "regular", "standard_char"),
    ARC_BANNER: ("weapons", "arcs", "дуги"),
})


BANNER_MAP.update(LEGACY_BANNERS)


ARC_MAP = _alias_map(ARC_KINDS, {
    "standard": ("стандартная", "std", "perm", "permanent", "regular"),
    "event": ("ивентовая", "limited", "evt"),
})


CASHBACK_MAP = _alias_map(CASHBACK_TYPES, {"regular": ("normal", "basic"), "premium": ("премиум",)})


REWARD_KIND_MAP = _alias_map(REWARD_KINDS)


TRUE_WORDS = {"1", "true", "yes", "y", "t", "да", "bonus", "бонус"}


FALSE_WORDS = {"", "0", "false", "no", "n", "f", "нет", "none"}


EXTRA_DATE_FORMATS = ("%Y-%m-%d %H:%M", "%d.%m.%Y %H:%M:%S", "%d.%m.%Y %H:%M",
                      "%Y/%m/%d %H:%M:%S", "%Y/%m/%d %H:%M", "%Y.%m.%d %H:%M:%S",
                      "%Y.%m.%d %H:%M", "%Y-%m-%d")


def _lookup(value, mapping: dict, what: str, allow_empty: bool = False) -> str:
    s = str(value or "").strip().lower()
    if not s and allow_empty:
        return ""
    if s in mapping:
        return mapping[s]
    raise ValueError(f"{what}: {value!r}")


def _normalize_banner(value) -> str:
    if str(value or "").strip().lower() in REMOVED_BANNERS:
        raise ValueError("баннер «Новичковый» больше не поддерживается")
    return _lookup(value, BANNER_MAP, "неизвестный баннер")


def _normalize_rarity(value) -> int:
    """Ранг из импорта: S / A / B (в том числе кириллические А, В) или старые 5 / 4 / 3,
    «5★». Возвращает числовой ранг 5/4/3."""
    text = str(value or "").strip().upper().translate(CYR_TO_LAT)
    m = re.match(r"([SAB])(?:\W|$)", text)
    if m:
        return LETTER_RANKS[m.group(1)]
    m = re.search(r"\d", text)
    if not m or int(m.group()) not in RARITIES:
        raise ValueError(f"неверная редкость (ожидается S, A или B): {value!r}")
    return int(m.group())


def _normalize_bool(value) -> int:
    s = str(value if value is not None else "").strip().lower()
    if s in TRUE_WORDS:
        return 1
    if s in FALSE_WORDS:
        return 0
    raise ValueError(f"неверное значение флага бонуса: {value!r}")


def _normalize_date(value) -> str:
    if value is None or str(value).strip() == "":
        raise ValueError("не указана дата")
    if isinstance(value, (int, float)) or re.fullmatch(r"\d{9,13}", str(value).strip()):
        ts = float(value)
        if ts > 1e11:  # миллисекунды
            ts /= 1000.0
        return datetime.fromtimestamp(ts).strftime(DATE_FMT)
    s = str(value).strip()
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        if dt.tzinfo is not None:
            dt = dt.astimezone().replace(tzinfo=None)
        return dt.strftime(DATE_FMT)
    except ValueError:
        pass
    # НОВОЕ: русская дата с названием месяца («30 апр. 2026 г. 12:03:36»)
    if RU_DATE_RE.search(s):
        return parse_russian_datetime(s)  # при неверной дате бросит ValueError
    for fmt in EXTRA_DATE_FORMATS:
        try:
            return datetime.strptime(s, fmt).strftime(DATE_FMT)
        except ValueError:
            continue
    raise ValueError(f"не удалось разобрать дату: {value!r}")


def _picker(raw: dict):
    """Возвращает pick(*ключи): первое непустое значение (ключи — без учёта регистра)."""
    if not isinstance(raw, dict):
        raise ValueError("запись не является объектом")
    low = {str(k).strip().lower(): v for k, v in raw.items()}

    def pick(*keys):
        return next((low[k] for k in keys if low.get(k) not in (None, "")), None)
    return pick


def normalize_record(raw: dict) -> dict:
    """Приводит произвольную запись к формату БД или бросает ValueError.
    Лишние поля (например, старое «featured») игнорируются."""
    pick = _picker(raw)
    name = str(pick("name", "item", "item_name", "title") or "").strip()
    if not name:
        raise ValueError("не указано название")
    banner = _normalize_banner(pick("banner", "gacha_type", "pool", "banner_type"))
    rarity = _normalize_rarity(pick("rarity", "stars", "rank", "star"))
    is_bonus = _normalize_bool(pick("is_bonus", "bonus", "extra"))
    cashback = _lookup(pick("cashback", "cashback_type"), CASHBACK_MAP,
                       "неизвестный тип кешбэка", allow_empty=True)
    if cashback:
        if is_bonus:
            raise ValueError("кешбэк не может быть бонусной добычей")
        rarity = CASHBACK_RARITY[cashback]
    elif is_bonus and rarity != 4:
        raise ValueError("дополнительная добыча должна быть A")
    arc_kind = _lookup(pick("arc_kind", "arc_type", "weapon_type"), ARC_MAP,
                       "неизвестный тип дуги", allow_empty=True)
    if not (banner == ARC_BANNER and rarity == 5 and not is_bonus and not cashback):
        arc_kind = ""
    return {
        "banner": banner, "rarity": rarity, "name": name,
        "pulled_at": _normalize_date(pick("pulled_at", "time", "date", "datetime", "timestamp")),
        "is_bonus": is_bonus, "arc_kind": arc_kind, "cashback": cashback,
    }


def normalize_reward(raw: dict) -> dict:
    """Приводит запись предмета к формату БД или бросает ValueError.
    Пустое название заменяется названием типа; баннер необязателен (старые записи).
    detail: количество (кубики, фрагменты), имя персонажа (костюм, планер, окраска)
    или тип кешбэка."""
    pick = _picker(raw)
    kind = _lookup(pick("kind", "type"), REWARD_KIND_MAP, "неизвестный тип награды")
    name = str(pick("name", "title") or "").strip()
    detail = str(pick("detail", "details", "value") or "").strip()
    raw_banner = pick("banner", "gacha_type", "pool", "banner_type")
    if kind in QTY_OPTIONS:
        m = re.search(r"\d+", detail)
        if not m or not qty_is_valid(kind, m.group()):
            raise ValueError(f"{REWARD_KINDS[kind]}: количество должно быть "
                             f"{' или '.join(QTY_OPTIONS[kind])}, а не {detail!r}")
        detail = m.group()
    elif kind == "cashback":
        detail = _lookup(detail, CASHBACK_MAP, "неизвестный тип кешбэка")
    elif kind not in BIND_KINDS:
        detail = ""
    return {
        "kind": kind,
        "name": name or default_reward_name(kind, detail),
        "detail": detail,
        "obtained_at": _normalize_date(
            pick("obtained_at", "pulled_at", "time", "date", "datetime", "timestamp")),
        "banner": _normalize_banner(raw_banner) if raw_banner else "",
        "no_pity": int(kind in NO_PITY_KINDS or _normalize_bool(pick("no_pity"))),
        "rarity": reward_rarity_to_db(pick("rarity", "rank")),   # OCR-ФИКС
    }


def normalize_all(raw: list, fn, label: str):
    """Применяет fn к каждой записи. Возвращает (корректные, тексты ошибок)."""
    valid, errors = [], []
    for i, rec in enumerate(raw, 1):
        try:
            valid.append(fn(rec))
        except ValueError as e:
            errors.append(f"{label} {i}: {e}")
    return valid, errors


def _read_json(path: Path):
    with open(path, "r", encoding="utf-8-sig") as f:
        return json.load(f)


def load_json_records(path: Path) -> list:
    data = _read_json(path)
    if isinstance(data, dict):
        for key in ("records", "wishes", "pulls", "list", "data", "items"):
            if isinstance(data.get(key), list):
                return data[key]
        if isinstance(data.get("rewards"), list):
            return []  # файл содержит только предметы
        raise ValueError("в JSON не найден список записей (ожидается ключ 'records')")
    if isinstance(data, list):
        return data
    raise ValueError("неподдерживаемая структура JSON")


def load_json_rewards(path: Path) -> list:
    data = _read_json(path)
    return data["rewards"] if isinstance(data, dict) and isinstance(data.get("rewards"), list) else []


def load_csv_records(path: Path) -> list:
    with open(path, "r", encoding="utf-8-sig", newline="") as f:
        sample = f.read(4096)
        f.seek(0)
        try:
            dialect = csv.Sniffer().sniff(sample, delimiters=",;\t")
        except csv.Error:
            dialect = csv.excel
        return list(csv.DictReader(f, dialect=dialect))


# ----------------------------------------------------------------------------
# ЗАГЛУШКА: автоматический импорт из логов игры
# ----------------------------------------------------------------------------
def parse_game_logs(path: str) -> list:
    """
    ЗАГЛУШКА для автоматического импорта круток.

    Должна вернуть список словарей вида:
        {"banner": "event_character", "rarity": 5, "name": "Имя",
         "pulled_at": "2026-01-31 18:45:12", "is_bonus": 0, "arc_kind": "", "cashback": ""}
    (ключи и значения дополнительно нормализуются функцией normalize_record).

    Сейчас поддерживаются только JSON-файлы (см. load_json_records).
    Чтобы добавить чтение локальных логов игры:
      1. найдите файл лога (например, в папке игры или %LOCALAPPDATA%),
      2. найдите в нём строки/URL с историей круток,
      3. разберите их здесь и верните список записей.
    """
    p = Path(path)
    if p.suffix.lower() == ".json":
        return load_json_records(p)
    # TODO: реализовать разбор логов игры (.log / .txt)
    raise NotImplementedError(
        "Автоматический разбор логов игры пока не реализован.\n"
        "Реализуйте функцию parse_game_logs() в main.py "
        "или используйте импорт JSON/CSV."
    )


# ----------------------------------------------------------------------------
# OCR скриншотов (pytesseract)
# ----------------------------------------------------------------------------
TESSERACT_WIN_PATH = Path(r"C:\Program Files\Tesseract-OCR\tesseract.exe")


# Слова, которые сами по себе — тип добычи, а не название предмета
KEYWORD_SET = {"кубик", "костюм", "планер", "скин", "окраска", "фрагмент", "кешбэк", "кэшбэк",
               "кешбек", "cube", "outfit", "glider", "skin", "cashback"}


# ---------------------------------------------------------------------------
# ИСПРАВЛЕНО: русские даты со скриншота («30 апр. 2026 г. 12:03:36»)
# ---------------------------------------------------------------------------
# ПРИЧИНА БАГА: DATE_RE знал только числовые форматы («2026-04-30 12:03:36»,
# «30.04.2026 12:03»). Дата с названием месяца не находилась, поэтому она оставалась в
# названии предмета, а время записи подменялось текущим системным.
# Ключ — первые три буквы месяца (без «ё», в нижнем регистре): «апр.», «апреля», «апрель»
# сводятся к «апр». У мая две формы: «май» (именительный) и «мая» (родительный).
RU_MONTHS = {"янв": 1, "фев": 2, "мар": 3, "апр": 4, "мая": 5, "май": 5, "июн": 6,
             "июл": 7, "авг": 8, "сен": 9, "окт": 10, "ноя": 11, "дек": 12}


# OCR-ФИКС 6 (даты): типичные искажения названия месяца. Tesseract читает «май» как «man»,
# «маи», «ман» и т. п. Ключи — написание ПОСЛЕ замены латинских «двойников» букв на русские
# (man -> ман, mai -> маи, cen -> сен). Словарь МОЖНО ДОПОЛНЯТЬ.
MONTH_OCR_TYPOS = {"ман": 5, "маи": 5, "мап": 5, "мам": 5, "мав": 5, "мау": 5, "мей": 5,
                   "мяи": 5, "мии": 5}


_LATIN_TO_CYR = str.maketrans({"a": "а", "c": "с", "e": "е", "k": "к", "m": "м", "o": "о",
                               "p": "р", "t": "т", "x": "х", "y": "у", "h": "н", "n": "н",
                               "b": "в", "i": "и", "u": "и", "r": "г"})


# День, который OCR прочитал буквой («Б май» = «6 май»; «З» = 3; «l», «I», «|» = 1)
DAY_OCR_LETTERS = {"б": 6, "з": 3, "l": 1, "i": 1, "|": 1}


def month_from_token(token: str):
    """OCR-ФИКС 6: номер месяца по слову с возможными опечатками OCR или None.
    Порядок: словарь искажений -> первые три буквы -> нечёткое сходство с трёхбуквенными
    основами (засчитывается, только если лучший результат относится к ЕДИНСТВЕННОМУ месяцу)."""
    t = (token or "").lower().replace("ё", "е").strip(".,")
    if len(t) < 2:
        return None
    f = t.translate(_LATIN_TO_CYR)
    for form in (t, f):
        if form in MONTH_OCR_TYPOS:
            return MONTH_OCR_TYPOS[form]
        if form[:3] in RU_MONTHS:
            return RU_MONTHS[form[:3]]
    if len(f) < 3:
        return None
    scores = {}
    for stem, num in RU_MONTHS.items():
        r = difflib.SequenceMatcher(None, f[:3], stem).ratio()
        scores[num] = max(scores.get(num, 0.0), r)
    best = max(scores.values())
    winners = [n for n, v in scores.items() if v == best]
    return winners[0] if best >= 0.66 and len(winners) == 1 else None


# Русская дата и время одной цепочкой. Допуски на типичные ошибки OCR:
#   * между днём и месяцем пробела может не быть («30апр.»);
#   * точка после месяца, запятые и «г.» необязательны (OCR часто читает «г» как «r»);
#   * разделитель времени — «:» или «;»; секунды необязательны.
# Название месяца берётся любым словом из 3–9 букв — так дата вырезается из названия
# предмета, даже если месяц распознан с ошибкой (тогда время просто не определится и его
# можно будет поправить вручную в списке). Проверка месяца — в parse_russian_datetime().
# OCR-ФИКС 6: день может быть прочитан буквой («Б май» = 6 мая; такая буква не должна быть
# концом другого слова), название месяца — от 2 букв (проверка — month_from_token()).
RU_DATE_RE = re.compile(
    r"(?<![\d:;.,/\-+×xх(])"
    r"(?P<d>(?<!\d)\d{1,2}(?!\d)|(?<![^\W\d_])[БбЗзlI|])[ \t]*(?P<m>[^\W\d_]{3,9})\.?,?[ \t]*(?P<y>(?:19|20)\d{2})(?!\d)[ \t]*(?:[гrГ]\.?)?,?[ \t]*"
    r"(?P<h>\d{1,2})[:;](?P<mi>\d{2})(?:[:;](?P<s>\d{2}))?(?!\d)", re.I)


# Общий поиск даты: числовые форматы (как раньше) ИЛИ русский формат.
# ВНИМАНИЕ: в RU_DATE_RE есть именованные группы, поэтому DATE_RE.findall() возвращает
# кортежи — для получения строк используйте DATE_RE.finditer() и m.group().
DATE_RE = re.compile(r"\d{4}[-/.]\d{2}[-/.]\d{2}[ T]\d{2}:\d{2}(?::\d{2})?"
                     r"|\d{2}\.\d{2}\.\d{4} \d{2}:\d{2}(?::\d{2})?"
                     r"|" + RU_DATE_RE.pattern, re.I)


def _ocr_day(token: str):
    """День месяца из токена даты: число или буква-двойник цифры (Б -> 6)."""
    token = token.strip()
    if token.isdigit():
        return int(token)
    return DAY_OCR_LETTERS.get(token.lower())


def _stamp_from_match(m, day=None) -> str:
    month = month_from_token(m.group("m"))
    if month is None:
        raise ValueError(f"неизвестный месяц: {m.group('m')!r}")
    day = day if day is not None else _ocr_day(m.group("d"))
    if day is None:
        raise ValueError(f"неизвестный день: {m.group('d')!r}")
    try:
        dt = datetime(int(m.group("y")), month, day,
                      int(m.group("h")), int(m.group("mi")), int(m.group("s") or 0))
    except ValueError as e:  # 31 апреля, 25:99 и т. п.
        raise ValueError(f"невозможная дата: {e}") from e
    return dt.strftime(DATE_FMT)


def find_valid_date_match(text: str):
    """Первое совпадение DATE_RE, которое является настоящей датой."""
    for m in DATE_RE.finditer(text or ""):
        try:
            if m.groupdict().get("m") is not None:
                _stamp_from_match(m)
            else:
                _normalize_date(m.group())
        except ValueError:
            continue
        return m
    return None


def parse_russian_datetime(text: str) -> str:
    """Русская дата -> строка ISO «ГГГГ-ММ-ДД ЧЧ:ММ:СС» (формат DATE_FMT).

    Пример: «30 апр. 2026 г. 12:03:36» -> «2026-04-30 12:03:36».
    OCR-ФИКС 6: допускаются опечатки месяца («4 man.» = 4 мая) и день-буква («Б май» = 6 мая).
    Бросает ValueError, если это не русская дата, месяц неизвестен или дата невозможна."""
    for m in RU_DATE_RE.finditer(text or ""):
        try:
            return _stamp_from_match(m)
        except ValueError:
            continue
    raise ValueError(f"не русская дата: {text!r}")


# День-БУКВА, за которой скрываются несколько цифр: в шрифте игры «5» часто читается как «Б»,
# но «Б» бывает и настоящей «6». Первая цифра — запасной вариант, если контекста нет.
AMBIG_DAY_LETTERS = {"б": (6, 5)}


def soft_day_stamps(raw_date: str) -> list:
    """Если день в сыром тексте даты — неоднозначная буква («Б май» = 5 или 6 мая), возвращает
    список возможных меток времени (первая — по умолчанию), иначе пустой список."""
    m = next((x for x in RU_DATE_RE.finditer(raw_date or "")
              if month_from_token(x.group("m")) is not None), None)
    if not m:
        return []
    days = AMBIG_DAY_LETTERS.get(m.group("d").strip().lower())
    out = []
    for d in days or ():
        try:
            out.append(_stamp_from_match(m, d))
        except ValueError:
            pass
    return out if len(out) > 1 else []


def alt_day_stamp(raw_date: str):
    """OCR-ФИКС 6: запасной разбор даты, когда к дню приклеилась цифра количества
    («15 май» = количество 1 + день 5): день — только последняя цифра. None, если нельзя."""
    m = next((x for x in RU_DATE_RE.finditer(raw_date or "")
              if month_from_token(x.group("m")) is not None), None)
    if not m or not (m.group("d").isdigit() and len(m.group("d")) == 2):
        return None
    try:
        return _stamp_from_match(m, int(m.group("d")[-1]))
    except ValueError:
        return None


# ---- Пороги цветового анализа ТЕКСТА (подбираются под реальные скриншоты игры) ----
# OCR-ФИКС: ранг снова определяется по цвету самих БУКВ названия на скриншоте:
#   жёлтый / золотой текст -> S,  фиолетовый / пурпурный текст -> A,
#   серый / белый / тёмный текст -> B.
# Золотистый (ранг S): оттенок 30–65°, насыщенный и яркий
GOLD_HUE, GOLD_MIN_SAT, GOLD_MIN_VAL = (30, 65), 0.35, 0.50


# Фиолетовый / пурпурный (ранг A): оттенок 255–320°
PURPLE_HUE, PURPLE_MIN_SAT, PURPLE_MIN_VAL = (255, 320), 0.30, 0.35


# Текстом считаются пиксели, заметно отличающиеся от фона строки (фон — медианный цвет
# вырезанной области): так не нужно знать, светлый интерфейс или тёмный, а цвет подложки
# строки не принимается за цвет текста.
TEXT_FG_DIFF = 60            # минимальное отличие пикселя от фона (0–255 по каналу)


TEXT_MIN_PIXELS = 15         # меньше пикселей текста — цвет не определяется (None)


TEXT_COLOR_MIN_FRACTION = 0.20   # доля золотых / фиолетовых пикселей среди пикселей текста


# ---------------------------------------------------------------------------
# ИСПРАВЛЕНО: облегчённый и устойчивый к шуму OCR скриншотов
# ---------------------------------------------------------------------------
# Что было не так. Прошлая версия увеличивала снимок до ×3, жёстко бинаризовала его целиком
# (Otsu) и делала до четырёх запусков Tesseract на КАЖДУЮ строку. Результат: долгая обработка
# и «мусорные» символы («| o |**»), потому что на полупрозрачном игровом фоне жёсткий порог
# превращает рамки, значки и свечение в чёрные пятна, которые Tesseract читает как знаки.
# Что сделано сейчас:
#   1) основной путь лёгкий: масштаб не больше ×2 и не выше OCR_TARGET_WIDTH по ширине, оттенки
#      серого, нормализация полярности (текст тёмный на светлом) и мягкий CLAHE — БЕЗ жёсткой
#      бинаризации. Tesseract (LSTM) читает полутона заметно лучше, чем «выжженный» порог;
#   2) ОДИН запуск Tesseract на весь снимок (--psm 6). Бинаризация Otsu с морфологией — только
#      запасной вариант, если уверенность распознавания низкая; --psm 11 — если слов нет вовсе;
#   3) строки собираются по ВЕРТИКАЛЬНОМУ положению слов, а не по разбиению Tesseract: одна
#      строка таблицы = одна строка текста (раньше одна запись могла разваливаться на две и
#      давать «дубликаты»); слишком высокие «слова» (значки) отбрасываются;
#   4) мусор вычищается ДО разбора: слова из одних знаков («|», «**»), слова с очень низкой
#      уверенностью, строки без букв и строки вне таблицы (заголовки окна, кнопки);
#   5) повторное чтение столбца названия (--psm 7) — только для строк с низкой уверенностью
#      и не более OCR_REFINE_ROWS строк на снимок;
#   6) всё это выполняется в ФОНОВОМ потоке (OcrThread), окно не зависает.

# ---- Настройки (при необходимости подберите под свои скриншоты) ----
# Область таблицы в ДОЛЯХ снимка (левый, верхний, правый, нижний), например (0.2, 0.15, 0.85, 0.95).
# None — анализируется весь снимок (строки вне таблицы отсекаются автоматически).
OCR_TABLE_ROI = None


OCR_TARGET_WIDTH = 2400        # до такой ширины (px) увеличивается мелкий снимок


OCR_MAX_SCALE = 2.0            # предел увеличения (раньше было ×3 — слишком медленно)


OCR_CLAHE_CLIP = 2.0           # сила выравнивания контраста CLAHE (мягкая)


OCR_CLAHE_TILE = 8             # сетка CLAHE (8×8 блоков)


OCR_PSM_LAYOUT = 6             # 6 — ровный блок текста (основной режим)


OCR_PSM_SPARSE = 11            # 11 — разреженный текст (запасной, если слов не найдено)


OCR_PSM_ROW = 7                # одна строка текста — для повторного чтения названия


OCR_LOW_CONF = 55              # средняя уверенность (0–100): ниже — запасной вариант / перечитывание


OCR_MIN_WORD_CONF = 30         # слова короче 4 знаков с уверенностью ниже — считаются мусором


OCR_MIN_LETTER_RATIO = 0.35    # доля букв в строке без даты; ниже — строка считается мусором


OCR_REFINE_ROWS = 12           # максимум строк, названия которых перечитываются отдельно


OCR_PAD = 10                   # поля вокруг вырезаемой строки (px исходного снимка)


# ---- КОНВЕЙЕР Б (текст): настройки улучшенной копии строки ----
OCR_ENHANCE_SCALE = 2.5        # увеличение копии строки через cv2.resize (допустимо 2.0–3.0)


OCR_ENHANCE_ROWS = 60          # максимум строк с повторным чтением конвейером Б на снимок


OCR_DENOISE_H = 12             # сила шумоподавления (fastNlMeansDenoising): убирает свечение шрифта


OCR_B_CONF_MARGIN = 8          # результат Б берётся, если не хуже первого прохода более чем на это


# столбец названия в таблице дуг: левый / правый край — доля ширины снимка левее начала даты
OCR_NAME_COL_FRACS = (0.46, 0.20)


OCR_NAME_MAX_CALLS = 24      # максимум запусков Tesseract на перечитывание одного названия


OCR_NAME_LANGS = ("rus", "rus+eng")   # языки для перечитывания названия


OCR_GOOD_CONF = 88             # уверенность, при которой перечитывание названия прекращается


OCR_BILATERAL = (5, 40, 40)    # мягкое шумоподавление всего снимка (диаметр, sigmaColor, sigmaSpace)


OCR_SHARPEN = 0.6              # сила нерезкой маски (0 — выключено)


OCR_ADAPTIVE_BLOCK = 31        # окно адаптивного порога (нечётное)


OCR_ADAPTIVE_C = 11            # смещение адаптивного порога


OCR_DEBUG_DIR = None           # папка для сохранения промежуточных картинок (отладка), или None


# Параметры Tesseract: LSTM-движок, сохранение пробелов между словами, задан DPI.
# Словари языка НЕ отключаются — они помогают исправлять русские слова («Твердый кубик»).
OCR_BASE_CONFIG = "--oem 1 -c preserve_interword_spaces=1 -c user_defined_dpi=300"


_NAME_WORD_RE = re.compile(r"[^\W\d_]{2,}")                 # слово минимум из двух букв


_QTY_WORD_RE = re.compile(r"^[x×х]?\d{1,3}$", re.I)         # «1», «×5», «x30»


# Символы-мусор по краям и внутри слов: рамки таблицы, маркеры, «звёздочки» и т. п.
_JUNK_EDGE_RE = re.compile(r"^[|*_~=<>\[\]{}\\^`©®™•·°¦§]+|[|*_~=<>\[\]{}\\^`©®™•·°¦§]+$")


# Слово целиком из знаков, не нужных в таблице. Дефис, тире, двоеточие, скобки, «×» и «★»
# сохраняются: они нужны в «Дуга - Название», «(S)», «×5», датах.
_JUNK_WORD_RE = re.compile(r"[^\w\-–—:()×★]+")


_ocr_langs_cache = None


def _available_langs() -> list:
    """Языки, установленные в Tesseract (список кэшируется). При ошибке — пустой список."""
    global _ocr_langs_cache
    if _ocr_langs_cache is None:
        try:
            _ocr_langs_cache = list(pytesseract.get_languages(config=""))
        except Exception:
            _ocr_langs_cache = []
    return _ocr_langs_cache


def _choose_scale(width: int, height: int) -> float:
    """Во сколько раз увеличить снимок: до OCR_TARGET_WIDTH по ширине, но не больше
    OCR_MAX_SCALE. Широкие снимки (от OCR_TARGET_WIDTH) не увеличиваются вовсе."""
    scale = min(OCR_MAX_SCALE, max(1.0, OCR_TARGET_WIDTH / max(1, width)))
    return 1.0 if scale < 1.1 else scale


def _prepare_gray(rgb_img, scale: float):
    """Лёгкая подготовка: оттенки серого -> увеличение кубической интерполяцией -> тёмный
    интерфейс инвертируется (текст становится тёмным на светлом) -> мягкий CLAHE."""
    gray = cv2.cvtColor(np.array(rgb_img), cv2.COLOR_RGB2GRAY)
    if scale > 1.0:
        gray = cv2.resize(gray, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
    if float(gray.mean()) < 110:                 # тёмный интерфейс игры
        gray = cv2.bitwise_not(gray)
    if OCR_BILATERAL:                            # шум и зернистость полупрозрачных панелей
        gray = cv2.bilateralFilter(gray, *OCR_BILATERAL)
    clahe = cv2.createCLAHE(clipLimit=OCR_CLAHE_CLIP,
                            tileGridSize=(OCR_CLAHE_TILE, OCR_CLAHE_TILE))
    gray = clahe.apply(gray)
    if OCR_SHARPEN:                              # нерезкая маска: чётче края букв
        blur = cv2.GaussianBlur(gray, (0, 0), 1.2)
        gray = cv2.addWeighted(gray, 1.0 + OCR_SHARPEN, blur, -OCR_SHARPEN, 0)
    return gray


def _binarize_fallback(gray):
    """ЗАПАСНОЙ вариант (только при низкой уверенности): порог Otsu и лёгкая морфология —
    открытие убирает одиночные пятна, закрытие склеивает разрывы штрихов. Возвращает чёрный
    текст на белом. Используется редко, поэтому стоит заметно дешевле прежнего конвейера."""
    _, bw = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    mask = cv2.bitwise_not(bw) if (bw > 0).mean() >= 0.5 else bw     # текст = меньшинство
    k = cv2.getStructuringElement(cv2.MORPH_RECT, (2, 2))
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, k)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, k)
    return cv2.bitwise_not(mask)


def _adaptive_binarize(gray):
    """Второй запасной вариант: адаптивный гауссов порог — хорошо работает при неравномерной
    подсветке (жёлтые / фиолетовые строки, полупрозрачные панели). Чёрный текст на белом."""
    block = OCR_ADAPTIVE_BLOCK if OCR_ADAPTIVE_BLOCK % 2 else OCR_ADAPTIVE_BLOCK + 1
    return cv2.adaptiveThreshold(gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                                 cv2.THRESH_BINARY, block, OCR_ADAPTIVE_C)


def _save_debug(name: str, img) -> None:
    """Сохраняет промежуточную картинку в OCR_DEBUG_DIR (если папка задана)."""
    if not OCR_DEBUG_DIR:
        return
    try:
        folder = Path(OCR_DEBUG_DIR)
        folder.mkdir(parents=True, exist_ok=True)
        ok, buf = cv2.imencode(".png", img)   # imencode — чтобы работали пути с кириллицей
        if ok:
            (folder / f"{name}.png").write_bytes(buf.tobytes())
    except OSError:
        pass


def _prepare_for_ocr_pil(img):
    """ЗАПАСНОЙ вариант без OpenCV (Pillow): ×2, серый, инверсия тёмного фона, автоконтраст.
    Возвращает (картинка, масштаб относительно оригинала)."""
    img = ImageOps.exif_transpose(img).convert("L")
    scale = 1
    if img.width < 1600:  # мелкий текст читается лучше в увеличенном виде
        scale = 2
        img = img.resize((img.width * 2, img.height * 2), Image.BICUBIC)
    if ImageStat.Stat(img).mean[0] < 110:  # тёмный интерфейс игры -> тёмный текст на светлом
        img = ImageOps.invert(img)
    return ImageOps.autocontrast(img), scale


def _extract_words(data: dict, scale: float) -> list:
    """Слова из image_to_data: [{"text", "conf", "box"}]; рамка пересчитана обратно в пиксели
    исходного скриншота."""
    words = []
    for i, word in enumerate(data["text"]):
        word = word.strip()
        try:
            conf = float(data["conf"][i])
        except (TypeError, ValueError):
            conf = -1
        if not word or conf < 0:
            continue
        left, top = data["left"][i], data["top"][i]
        right, bottom = left + data["width"][i], top + data["height"][i]
        words.append({"text": word, "conf": conf,
                      "box": tuple(int(v / scale) for v in (left, top, right, bottom))})
    return words


def _clean_words(words: list) -> list:
    """НОВОЕ: вычищает мусор из слов ДО сборки строк.
      * символы-рамки и маркеры по краям слова срезаются («|Дуга», «кубик**» -> «Дуга», «кубик»);
      * слова из одних лишних знаков («|», «**», «!») удаляются (дефис, «:», «×» остаются);
      * короткие слова (до 3 знаков) с низкой уверенностью удаляются — это почти всегда шум;
      * слишком высокие «слова» (значки и рамки, прочитанные как символ) удаляются."""
    heights = sorted(w["box"][3] - w["box"][1] for w in words)
    med_h = heights[len(heights) // 2] if heights else 0
    out = []
    for w in words:
        text = _JUNK_EDGE_RE.sub("", w["text"]).strip()
        if not text or _JUNK_WORD_RE.fullmatch(text):
            continue
        if len(text) <= 3 and w["conf"] < OCR_MIN_WORD_CONF:
            continue
        if med_h and (w["box"][3] - w["box"][1]) > 2.5 * med_h:
            continue
        out.append(dict(w, text=text))
    return out


def _group_words(words: list) -> list:
    """Собирает слова в строки по ВЕРТИКАЛЬНОМУ положению: слова, чьи центры по высоте близки,
    — одна строка таблицы (Tesseract мог разбить её на несколько блоков — отсюда дубликаты).
    Возвращает [{"text", "box": (l, t, r, b), "words": [...]}] сверху вниз."""
    rows = []   # каждая: {"cy", "h", "words"}
    for w in sorted(words, key=lambda w: (w["box"][1] + w["box"][3])):
        cy = (w["box"][1] + w["box"][3]) / 2
        h = max(1, w["box"][3] - w["box"][1])
        for r in rows[-3:]:                       # сравниваем только с ближайшими строками
            if abs(cy - r["cy"]) <= 0.6 * max(h, r["h"]):
                r["words"].append(w)
                n = len(r["words"])
                r["cy"] += (cy - r["cy"]) / n     # центр строки — скользящее среднее
                r["h"] = max(r["h"], h)
                break
        else:
            rows.append({"cy": cy, "h": h, "words": [w]})
    lines = []
    for r in rows:
        ws = sorted(r["words"], key=lambda w: w["box"][0])
        box = (min(w["box"][0] for w in ws), min(w["box"][1] for w in ws),
               max(w["box"][2] for w in ws), max(w["box"][3] for w in ws))
        lines.append({"text": " ".join(w["text"] for w in ws), "box": box, "words": ws})
    lines.sort(key=lambda ln: (ln["box"][1], ln["box"][0]))
    return lines


def _mean_conf(words: list) -> float:
    """Средняя уверенность Tesseract по словам (0 — если слов нет)."""
    return sum(w["conf"] for w in words) / len(words) if words else 0.0


# НОВОЕ: пороги проверки результата OCR (уверенность Tesseract — 0..100)
OCR_REVIEW_CONF = 70       # строка с уверенностью ниже — подсвечивается жёлтым и идёт в редактор


OCR_FALLBACK_CONF = 85     # запасное правило / словарь исправлений + уверенность ниже — проверка


FUZZY_REVIEW_SIM = 0.85    # итоговое название похоже на прочитанное меньше — проверка


def line_confidence(ln: dict):
    """НОВОЕ: уверенность Tesseract для строки (0–100) или None, если данных нет.
    Берётся уверенность названия (у перечитанного названия — конвейера Б); если слова с
    цифрами (дата, количество) читаются хуже — берётся меньшее значение: неверная дата
    нарушает хронологию, поэтому она тоже должна привлекать внимание."""
    words = ln.get("words") or []
    conf = ln.get("name_conf") or _mean_conf(words)
    if not conf:
        return None
    digit = [w["conf"] for w in words if re.search(r"\d", w.get("text", ""))]
    if digit:
        conf = min(conf, sum(digit) / len(digit))
    if ln.get("time_doubt"):                       # время прочитано по-разному — на проверку
        conf = min(conf, OCR_REVIEW_CONF - 1)
    return round(max(0.0, min(100.0, float(conf))), 1)


def _letter_ratio(text: str) -> float:
    """Доля букв среди непробельных знаков строки."""
    chars = re.sub(r"\s+", "", text)
    return len(re.findall(r"[^\W\d_]", chars)) / len(chars) if chars else 0.0


def _filter_table_lines(lines: list) -> list:
    """НОВОЕ: оставляет только строки таблицы.
      * строки с низкой долей букв без даты («| o |**», обрывки рамок) удаляются;
      * если на снимке есть строки с датой (они — «якоря» таблицы), строки заметно выше первой
        и ниже последней записи (заголовок окна, кнопки, подсказки) удаляются."""
    kept = [ln for ln in lines
            if DATE_RE.search(ln["text"]) or (_NAME_WORD_RE.search(ln["text"])
                                              and _letter_ratio(ln["text"]) >= OCR_MIN_LETTER_RATIO)]
    anchors = [ln for ln in kept if DATE_RE.search(ln["text"])]
    if not anchors:
        return kept
    heights = sorted(ln["box"][3] - ln["box"][1] for ln in anchors)
    med_h = heights[len(heights) // 2]
    top = min(ln["box"][1] for ln in anchors) - 3 * med_h
    bottom = max(ln["box"][3] for ln in anchors) + 3 * med_h
    return [ln for ln in kept if ln["box"][3] >= top and ln["box"][1] <= bottom]


def _tess_words(img, lang: str, psm: int, scale: float) -> list:
    """Один запуск Tesseract. Ошибки: TesseractNotFoundError -> OcrError,
    TesseractError пробрасывается (вызывающий пробует другой язык)."""
    try:
        data = pytesseract.image_to_data(img, lang=lang, config=f"--psm {psm} {OCR_BASE_CONFIG}",
                                         output_type=pytesseract.Output.DICT)
    except pytesseract.TesseractNotFoundError as e:
        raise OcrError("Программа Tesseract OCR не найдена. Установите её и добавьте в PATH "
                       f"(или в {TESSERACT_WIN_PATH}).") from e
    return _clean_words(_extract_words(data, scale))


def _run_langs(img, psm: int, scale: float, langs=("rus+eng", "eng")):
    """Запуск Tesseract с запасным языком (без русского пакета — только английский).
    Возвращает (слова, язык, последняя ошибка)."""
    last_error = None
    for lang in langs:
        try:
            return _tess_words(img, lang, psm, scale), lang, None
        except pytesseract.TesseractError as e:
            last_error = e
    return None, None, last_error


def _layout_pass(gray, scale: float):
    """ПРОХОД 1: распознаёт весь снимок. Обычно ОДИН запуск (серая картинка, --psm 6).
    Если уверенность ниже OCR_LOW_CONF — одна попытка по бинаризованной картинке; если слов
    нет вовсе — одна попытка в режиме --psm 11. Возвращает (слова, язык)."""
    words, lang, err = _run_langs(gray, OCR_PSM_LAYOUT, scale)
    if words is None:
        raise OcrError(f"Ошибка распознавания:\n{err}")
    best = (sum(w["conf"] for w in words), words)
    if not words or _mean_conf(words) < OCR_LOW_CONF:
        for tag, make in (("otsu", _binarize_fallback), ("adaptive", _adaptive_binarize)):
            bw = make(gray)
            _save_debug("layout_" + tag, bw)
            alt, _, _ = _run_langs(bw, OCR_PSM_LAYOUT, scale, (lang,))
            if alt and sum(w["conf"] for w in alt) > best[0]:
                best = (sum(w["conf"] for w in alt), alt)
            if best[1] and _mean_conf(best[1]) >= OCR_LOW_CONF:
                break
    if not best[1]:
        alt, _, _ = _run_langs(gray, OCR_PSM_SPARSE, scale, (lang,))
        if alt:
            best = (0, alt)
    return best[1], lang


def _right_column_index(words: list, start: int = 1):
    """Индекс первого слова правых столбцов («Количество», «Время получения») в строке или None.
    Это либо отдельное число (количество), либо начало даты. Слова левее — название предмета."""
    offsets, pos = [], 0
    for w in words:
        offsets.append(pos)
        pos += len(w["text"]) + 1
    m = DATE_RE.search(" ".join(w["text"] for w in words))
    date_idx = None
    if m:
        date_idx = max(i for i, off in enumerate(offsets) if off <= m.start())
    for i in range(max(1, start), len(words)):
        if _QTY_WORD_RE.match(words[i]["text"]) or i == date_idx:
            return i
        # ИСПРАВЛЕНО (таблица дуг): между названием и временем стоит столбец «Тип»
        # («Чудо-коробка»). Раньше он попадал в рамку названия: цвет текста считался вместе с
        # серой подписью типа (золотые/фиолетовые дуги читались как серые), а название
        # перечитывалось вместе с «Чудо-коробка». Теперь столбец «Тип» — тоже правая колонка:
        # она начинается со слова «Чудо-коробка» либо после широкого разрыва между словами.
        if TYPE_COLUMN_RE.search(words[i]["text"]):
            return i
        try:
            prev, cur = words[i - 1]["box"], words[i]["box"]
            height = max(1, cur[3] - cur[1])
            if cur[0] - prev[2] > max(2.2 * height, 50):
                return i
        except (KeyError, TypeError, IndexError):
            pass
    return date_idx if date_idx is not None and date_idx >= start else None


# ---------------------------------------------------------------------------
# НОВОЕ: ДВА НЕЗАВИСИМЫХ КОНВЕЙЕРА ДЛЯ КАЖДОЙ СТРОКИ
#   КОНВЕЙЕР А (цвет / ранг): читает пиксели НЕИЗМЕНЁННОГО исходного снимка по рамке текста
#       названия (detect_rarity_colors -> classify_rarity_color): жёлтый/золотой -> S,
#       фиолетовый -> A, серый/белый -> B. Логика цвета НЕ менялась и от обработки текста
#       не зависит: конвейер Б меняет только поле строки «text» и никогда не трогает рамки
#       («box», «words», «name_left»), по которым конвейер А вырезает свою область.
#   КОНВЕЙЕР Б (текст): копия вырезки строки -> увеличение cv2.resize (×2–3) -> оттенки
#       серого -> шумоподавление (убирает свечение шрифта и полупрозрачные элементы
#       интерфейса) -> порог Оцу (THRESH_BINARY + THRESH_OTSU): чёрный текст на чистом
#       белом -> медианный фильтр -> Tesseract. Результат объединяется с рангом из конвейера А
#       уже в parse_screenshot_text / ocr_extract_pulls, а опечатки исправляют нечёткие
#       справочники (difflib: персонажи, дуги, планеры, предметы).
# ---------------------------------------------------------------------------
def enhance_text_crop(rgb):
    """КОНВЕЙЕР Б: улучшенная КОПИЯ вырезки строки для Tesseract. rgb — массив RGB (исходная
    вырезка не изменяется). Возвращает одноканальную картинку: чёрный текст на белом фоне
    с белым полем по краям."""
    work = rgb.copy()                                               # исходник не трогаем
    work = cv2.resize(work, None, fx=OCR_ENHANCE_SCALE, fy=OCR_ENHANCE_SCALE,
                      interpolation=cv2.INTER_CUBIC)
    gray = cv2.cvtColor(work, cv2.COLOR_RGB2GRAY)
    gray = cv2.fastNlMeansDenoising(gray, None, h=OCR_DENOISE_H,
                                    templateWindowSize=7, searchWindowSize=21)
    _, bw = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    if (bw > 0).mean() < 0.5:        # белых пикселей меньшинство -> светлый текст на тёмном фоне
        bw = cv2.bitwise_not(bw)     # (тёмный интерфейс игры): делаем текст чёрным на белом
    bw = cv2.medianBlur(bw, 3)       # убирает одиночные пятна и «соль-перец» после порога
    pad = max(8, int(OCR_PAD * OCR_ENHANCE_SCALE))
    return cv2.copyMakeBorder(bw, pad, pad, pad, pad, cv2.BORDER_CONSTANT, value=255)


def _pad_white(img):
    pad = max(8, int(OCR_PAD * OCR_ENHANCE_SCALE))
    return cv2.copyMakeBorder(img, pad, pad, pad, pad, cv2.BORDER_CONSTANT, value=255)


def enhance_text_crop_variants(rgb) -> list:
    """Несколько независимых вариантов улучшенной КОПИИ вырезки строки (исходник не меняется):
      1) «отличие от фона»: цвет фона — медиана краёв вырезки, текст — пиксели, заметно
         отличающиеся от него по любому каналу; не зависит ни от цвета подсветки строки
         (жёлтая / фиолетовая), ни от полярности (светлый текст на тёмном и наоборот);
      2) серый + шумоподавление + порог Оцу (прежний вариант конвейера Б);
      3) CLAHE + адаптивный порог (неравномерный фон, полупрозрачные панели).
    Все варианты — чёрный текст на белом с белым полем по краям."""
    work = cv2.resize(rgb.copy(), None, fx=OCR_ENHANCE_SCALE, fy=OCR_ENHANCE_SCALE,
                      interpolation=cv2.INTER_CUBIC)
    out = []
    try:
        edge = np.concatenate([work[0, :], work[-1, :], work[:, 0], work[:, -1]]).reshape(-1, 3)
        bg = np.median(edge, axis=0).astype(np.int16)
        diff = np.abs(work.astype(np.int16) - bg).max(axis=2).astype(np.uint8)
        diff = cv2.GaussianBlur(diff, (3, 3), 0)
        _, mask = cv2.threshold(diff, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        out.append(_pad_white(cv2.medianBlur(cv2.bitwise_not(mask), 3)))
    except (ValueError, cv2.error):
        pass
    gray = cv2.cvtColor(work, cv2.COLOR_RGB2GRAY)
    den = cv2.fastNlMeansDenoising(gray, None, h=OCR_DENOISE_H,
                                   templateWindowSize=7, searchWindowSize=21)
    _, bw = cv2.threshold(den, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    if (bw > 0).mean() < 0.5:
        bw = cv2.bitwise_not(bw)
    out.append(_pad_white(cv2.medianBlur(bw, 3)))
    if float(gray.mean()) < 110:
        gray = cv2.bitwise_not(gray)
    eq = cv2.createCLAHE(clipLimit=2.5, tileGridSize=(4, 4)).apply(gray)
    out.append(_pad_white(_adaptive_binarize(eq)))
    return out


def _color_fill_mask(rgb):
    """Маска ЗАЛИВКИ цветного названия (золото S / розово-фиолетовый A) на светлой строке
    таблицы: насыщенные яркие пиксели. Серый текст, светлый фон и чёрная обводка в маску не
    попадают. Возвращает (маска uint8 0/255, hsv) или (None, None), если цветного текста нет."""
    hsv = cv2.cvtColor(rgb, cv2.COLOR_RGB2HSV)
    fill = ((hsv[:, :, 1] > 110) & (hsv[:, :, 2] > 110)).astype(np.uint8) * 255
    fill = cv2.morphologyEx(fill, cv2.MORPH_OPEN, np.ones((2, 2), np.uint8))
    if int((fill > 0).sum()) < max(12, 0.002 * fill.size):
        return None, None
    return fill, hsv


def _fill_rank_hint(rgb):
    """Ранг по оттенку заливки названия: золото -> 5 (S), розово-фиолетовый -> 4 (A);
    нет цветной заливки -> 3 (серый, B). None — маску построить не удалось."""
    try:
        fill, hsv = _color_fill_mask(rgb)
        if fill is None:
            return 3
        hue = float(np.median(hsv[:, :, 0][fill > 0]))
        if 8 <= hue <= 45:
            return 5
        if 115 <= hue <= 179 or hue <= 3:
            return 4
        return None
    except (ValueError, cv2.error):
        return None


def _color_fill_variants(rgb) -> list:
    """ИСПРАВЛЕНО: цветные названия в таблице дуг (золотые / розовые буквы с ЧЁРНОЙ обводкой)
    обычная бинаризация читает частично или не читает вовсе: в строке оставалась «только
    дата». Текст выделяется по цвету заливки (чёрный текст на белом, белое поле по краям):
      1) ГЛАДКАЯ маска: мягкая насыщенность -> увеличение ×3 с интерполяцией -> размытие ->
         порог (ровные края букв, без «лесенки»);
      2) жёсткая маска заливки ×2.5;
      3) жёсткая маска со сглаженными краями (замкнуты мелкие разрывы букв)."""
    try:
        fill, hsv = _color_fill_mask(rgb)
        if fill is None:
            return []
        out = []
        sat = hsv[:, :, 1].astype(np.float32)
        soft = np.clip((sat - 70.0) / 80.0, 0.0, 1.0) * (hsv[:, :, 2] > 100)
        soft = cv2.bitwise_and((soft * 255).astype(np.uint8), cv2.dilate(fill, np.ones((3, 3), np.uint8)))
        big = cv2.resize(soft, None, fx=3.0, fy=3.0, interpolation=cv2.INTER_CUBIC)
        big = cv2.GaussianBlur(big, (0, 0), 1.2)
        _, big = cv2.threshold(big, 110, 255, cv2.THRESH_BINARY)
        out.append(_pad_white(cv2.bitwise_not(big)))
        work_fill = cv2.resize(fill, None, fx=OCR_ENHANCE_SCALE, fy=OCR_ENHANCE_SCALE,
                               interpolation=cv2.INTER_CUBIC)
        _, work_fill = cv2.threshold(work_fill, 127, 255, cv2.THRESH_BINARY)
        out.append(_pad_white(cv2.bitwise_not(work_fill)))
        both = cv2.morphologyEx(work_fill, cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8))
        both = cv2.medianBlur(both, 5)
        out.append(_pad_white(cv2.bitwise_not(both)))
        return out
    except (ValueError, cv2.error):
        return []


def _text_bbox(rgb):
    """Рамка текста названия внутри вырезки (x0, y0, x1, y1) в координатах вырезки: сначала по
    цвету заливки, иначе по отличию от фона. None — текста не найдено."""
    try:
        mask, _hsv = _color_fill_mask(rgb)
        if mask is None:
            edge = np.concatenate([rgb[0, :], rgb[-1, :], rgb[:, 0], rgb[:, -1]]).reshape(-1, 3)
            bg = np.median(edge, axis=0).astype(np.int16)
            diff = np.abs(rgb.astype(np.int16) - bg).max(axis=2).astype(np.uint8)
            mask = ((diff > 60).astype(np.uint8)) * 255
            mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((2, 2), np.uint8))
        ys, xs = np.nonzero(mask)
        if len(xs) < 12:
            return None
        return int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1
    except (ValueError, cv2.error):
        return None


def _read_name_enhanced(rgb_np, box: tuple, langs: list, debug_name: str = "",
                        color_first: bool = False):
    """КОНВЕЙЕР Б для одной строки: вырезает область названия из ИСХОДНОГО снимка (box — в
    пикселях исходника: x0, y0, x1, y1), улучшает копию (enhance_text_crop) и читает её как
    одну строку (--psm 7). Возвращает (текст, средняя уверенность)."""
    height, width = rgb_np.shape[:2]
    x0, y0 = max(0, box[0]), max(0, box[1])
    x1, y1 = min(width, box[2]), min(height, box[3])
    if x1 - x0 < 8 or y1 - y0 < 4:
        return "", 0.0
    crop = rgb_np[y0:y1, x0:x1]
    try:
        variants = enhance_text_crop_variants(crop)
    except cv2.error:
        variants = [enhance_text_crop(crop)]
    if color_first:                       # цветное название с обводкой: сначала маска по цвету
        variants = _color_fill_variants(crop) + variants
    best_text, best_conf = "", 0.0
    for v, row in enumerate(variants):
        if debug_name:
            _save_debug(f"{debug_name}{v}", row)
        for lang in langs:
            try:
                words = _tess_words(row, lang, OCR_PSM_ROW, 1.0)
            except pytesseract.TesseractError:
                continue
            text = " ".join(w["text"] for w in words).strip()
            conf = _mean_conf(words)
            if text and _NAME_WORD_RE.search(text) and conf > best_conf:
                best_text, best_conf = text, conf
            if best_text and best_conf >= OCR_GOOD_CONF:
                return best_text, best_conf
        if best_text and best_conf >= OCR_LOW_CONF and v >= 1:
            break
    return best_text, best_conf


# Флаг «сейчас обрабатывается баннер дуг». Дорогое перечитывание цветных названий
# (_recover_missing_names) нужно только в таблице дуг; в остальных баннерах оно не запускается,
# чтобы не замедлять распознавание. Выставляется перед запуском потоков OCR.
OCR_ARC_BANNER = False


def set_ocr_arc_banner(flag: bool):
    global OCR_ARC_BANNER
    OCR_ARC_BANNER = bool(flag)


def _line_name_part(ln: dict) -> str:
    """Название из текста строки (слева от даты, без «Чудо-коробка» и заголовков)."""
    t = strip_type_column(ln.get("text") or "")
    m = DATE_RE.search(t)
    return (t[:m.start()] if m else t).strip()


def _line_has_name(ln: dict) -> bool:
    """В строке есть прочитанное название (буквы слева от даты; «Чудо-коробка» и заголовки
    столбцов не считаются). Строка «только с датой» — название OCR не прочитал."""
    return bool(re.search(r"[^\W\d_]{2,}", _line_name_part(ln)))


def _date_start_x(ln: dict) -> int:
    """Левый край даты в строке (пиксели снимка): первое слово, с которого начинается дата."""
    words = ln.get("words") or []
    if words:
        offsets, pos = [], 0
        for w in words:
            offsets.append(pos)
            pos += len(w["text"]) + 1
        m = DATE_RE.search(" ".join(w["text"] for w in words))
        if m:
            idx = max(i for i, off in enumerate(offsets) if off <= m.start())
            return int(words[idx]["box"][0])
    return int(ln["box"][0])


NAME_CHAR_WIDTH = 0.74        # средняя ширина буквы названия в долях высоты текста (шрифт таблицы)


NAME_COMPLETE_RATIO = 0.6     # прочитано меньше 60% ожидаемых букв — название считается обрезанным


NAME_GOOD_SCORE = 0.88        # сходство с эталоном, при котором чтение признаётся надёжным


NAME_MIN_SCORE = 0.55         # ниже — кандидат с эталоном не связан


def _name_candidate_score(text: str, rank_hint=None):
    """Лучшее сходство прочитанного текста с названиями мастер-справочника: (оценка, название).
    При известном ранге (по цвету) сравнение идёт только с названиями этого ранга."""
    clean = re.sub(r"[^\w\s.]", " ", text or "")
    best = (0.0, "")
    for e in master_index():
        rk = _snap_rank_of(e)
        if rank_hint and rk and rk != rank_hint:
            continue
        sc = lookalike_similarity(clean, e["name"])
        if sc > best[0]:
            best = (sc, e["name"])
    return best


def _read_name_candidates(rgb_np, box: tuple, langs: list, rank_hint=None, debug_name: str = ""):
    """Несколько независимых прочтений названия из вырезки: цветовые маски + обычные варианты,
    режимы --psm 7 (строка) и --psm 8 (слово). Возвращает [(текст, уверенность)]; останавливается,
    как только найдено надёжное совпадение с эталоном."""
    height, width = rgb_np.shape[:2]
    x0, y0 = max(0, box[0]), max(0, box[1])
    x1, y1 = min(width, box[2]), min(height, box[3])
    if x1 - x0 < 8 or y1 - y0 < 4:
        return []
    crop = rgb_np[y0:y1, x0:x1]
    try:
        variants = _color_fill_variants(crop) + enhance_text_crop_variants(crop)
    except cv2.error:
        variants = _color_fill_variants(crop) + [enhance_text_crop(crop)]
    cands, calls = [], 0
    for v, row in enumerate(variants):
        if debug_name:
            _save_debug(f"{debug_name}{v}", row)
        for psm in (OCR_PSM_ROW, 8):
            for lang in langs:
                if calls >= OCR_NAME_MAX_CALLS:
                    return cands
                calls += 1
                try:
                    words = _tess_words(row, lang, psm, 1.0)
                except pytesseract.TesseractError:
                    continue
                text = " ".join(w["text"] for w in words).strip()
                if text and _NAME_WORD_RE.search(text):
                    cands.append((text, _mean_conf(words)))
                    if _name_candidate_score(text, rank_hint)[0] >= NAME_GOOD_SCORE:
                        return cands
    return cands


def _recover_missing_names(lines: list, src, lang: str) -> list:
    """ИСПРАВЛЕНО (таблица дуг): цветные названия (золото / розовый, чёрная обводка) первый
    проход Tesseract читает частично («ОИ», «Обн» вместо «Неверные врата», «Обнаженный клинок»)
    или не видит вовсе (в строке только дата). Для каждой строки вырезается столбец названия
    (левее столбцов «Тип» и «Время»); если название не прочитано или обрезано (букв заметно меньше,
    чем помещается в рамку текста), оно перечитывается несколькими способами по маске цвета, а
    из прочтений выбирается самое близкое к названиям справочника нужного ранга. Рамка текста
    запоминается (name_box) — по ней определяется ранг (S / A / B)."""
    if cv2 is None or np is None or not lines or not OCR_ARC_BANNER:
        return lines
    # ИСПРАВЛЕНО: это перечитывание рассчитано на таблицу дуг со столбцом «Тип». В таблице бросков
    # («Результат броска» / «Название предмета») столбцов другая геометрия, и оно портило
    # правильные названия («Настоящая музыка» -> «conanr», «Дуга - Мы.» -> «мы»); там названия
    # уже читаются по маске цвета в _refine_name_column.
    if _header_icon_center(lines) is not None:
        return lines
    if not any(DATE_RE.search(ln["text"]) and not ln.get("synthetic") for ln in lines):
        return lines
    avail = _available_langs()
    langs = [l for l in OCR_NAME_LANGS if all(p in avail for p in l.split("+"))] or [lang]
    if lang == "eng":
        langs = ["eng"]
    rgb_np = np.array(src)
    height, width = rgb_np.shape[:2]
    named_left = [int(ln["name_left"]) for ln in lines
                  if _line_has_name(ln) and ln.get("name_left") is not None]
    budget = OCR_ENHANCE_ROWS
    out = []
    for n, ln in enumerate(lines):
        m_date = DATE_RE.search(ln["text"])
        if ln.get("synthetic") or not m_date or budget <= 0:
            out.append(ln)
            continue
        date_left = _date_start_x(ln)
        x0 = int(date_left - OCR_NAME_COL_FRACS[0] * width)
        x1 = int(date_left - OCR_NAME_COL_FRACS[1] * width)
        if named_left:
            x0 = min(x0, min(named_left) - OCR_PAD)
        for w in ln.get("words") or ():                  # слова столбца «Тип» ограничивают справа
            if TYPE_COLUMN_RE.search(w["text"]):
                x1 = min(x1, int(w["box"][0]) - OCR_PAD)
        x0, x1 = max(0, x0), min(width, x1)
        top, bottom = int(ln["box"][1]), int(ln["box"][3])
        padv = max(OCR_PAD, int((bottom - top) * 0.6))
        y0, y1 = max(0, top - padv), min(height, bottom + padv)
        if x1 - x0 < 40 or y1 - y0 < 8:
            out.append(ln)
            continue
        crop = rgb_np[y0:y1, x0:x1]
        bbox = _text_bbox(crop)
        new = dict(ln)
        if bbox:
            new["name_box"] = (x0 + bbox[0], y0 + bbox[1], x0 + bbox[2], y0 + bbox[3])
            new["name_left"] = x0 + bbox[0]
        first = _line_name_part(ln)
        first_letters = len(re.findall(r"[^\W\d_]", first))
        rank_hint = _fill_rank_hint(crop)
        incomplete = not first_letters
        if bbox and first_letters:
            bw, bh = bbox[2] - bbox[0], max(1, bbox[3] - bbox[1])
            expected = 0.85 * bw / (NAME_CHAR_WIDTH * bh)
            incomplete = first_letters < NAME_COMPLETE_RATIO * expected
        if (first_letters and not incomplete
                and _name_candidate_score(first, rank_hint)[0] >= NAME_GOOD_SCORE):
            out.append(new)                              # название прочитано полностью и надёжно
            continue
        if first_letters and not incomplete and rank_hint == 3:
            out.append(new)                              # серое название прочитано целиком — оставляем
            continue
        budget -= 1
        cands = _read_name_candidates(rgb_np, (x0, y0, x1, y1), langs, rank_hint,
                                      f"line_{n:02d}_C")
        if first_letters:
            cands.append((first, 0.0))
        best, best_key = None, (-1.0, -1)
        for text, conf in cands:
            letters = len(re.findall(r"[^\W\d_]", text))
            if letters < 2:
                continue
            score = _name_candidate_score(text, rank_hint)[0]
            key = (round(score, 2), letters)
            if key > best_key:
                best, best_key = text, key
        if best and (best_key[0] >= NAME_MIN_SCORE or not first_letters):
            new.update(text=f"{best} {ln['text'][m_date.start():]}".strip(), refined=True,
                       text_src="C", recovered=True)
        out.append(new)
    return out


def _refine_name_column(lines: list, src, lang: str) -> list:
    """Определяет границы столбца «Название предмета» в каждой строке (поле name_left —
    левый край названия, нужен цветовому анализу значка слева) и перечитывает название
    КОНВЕЙЕРОМ Б (улучшенная копия строки) для каждой строки с названием (не более
    OCR_ENHANCE_ROWS). Текст конвейера Б берётся, если он не заметно хуже первого прохода
    (или первый проход был слабым). Количество и дата остаются из первого прохода.
    ВАЖНО: меняется только поле «text»; рамки («box», «words», «name_left») остаются
    прежними — конвейер А (цвет/ранг) читает именно их, поэтому его результат не меняется."""
    if not lines:
        return lines
    avail = _available_langs()
    langs = [l for l in OCR_NAME_LANGS if all(p in avail for p in l.split("+"))] or [lang]
    if lang == "eng":
        langs = ["eng"]
    rgb_np = np.array(src)                     # исходный снимок (RGB), конвейер Б только копирует
    budget = OCR_ENHANCE_ROWS
    label_right = _header_label_right(lines)
    out = []
    for n, ln in enumerate(lines):
        words = ln["words"]
        first = next((i for i, w in enumerate(words) if _NAME_WORD_RE.search(w["text"])), None)
        if first is None or not _line_has_name(ln):   # строка без названия (только дата) — не трогаем
            out.append(dict(ln, name_left=ln["box"][0]))
            continue
        label_n = _left_label_count(words[first:])
        label_text = _label_canon(words, label_n)
        first += label_n                      # название начинается ПОСЛЕ подписи левого столбца
        if label_right is not None:           # значок кубика, прочитанный как «ee» / «se?)»
            while first < len(words) - 1 and words[first]["box"][2] <= label_right + 4:
                first += 1
        idx = _right_column_index(words, first + 1)
        # одиночные знаки пунктуации перед столбцом количества — остатки разделителей
        cut = idx
        while cut is not None and cut - 1 > first and re.fullmatch(r"[\W_]+", words[cut - 1]["text"]):
            cut -= 1
        name_words = words[:cut] if cut is not None else words
        right_words = words[idx:] if idx is not None else []
        left = words[first]["box"][0]            # значки слева от названия отсекаются
        old_conf = _mean_conf(name_words)
        ln = dict(ln, name_left=left, text_src="A", name_conf=old_conf)   # + уверенность названия
        if budget <= 0 or not clean_ocr_line(ln["text"]):
            out.append(ln)
            continue
        right = (words[cut]["box"][0] - OCR_PAD // 2) if cut is not None else ln["box"][2] + OCR_PAD
        top, bottom = ln["box"][1], ln["box"][3]
        padv = max(OCR_PAD, (bottom - top) // 4)
        box = (int(left - OCR_PAD), int(top - padv), int(right), int(bottom + padv))
        budget -= 1
        # ИСПРАВЛЕНО: цветное название (золото / фиолетовый с чёрной обводкой) читается по маске
        # заливки: обычная бинаризация сливает обводку с буквами и даёт мусор
        try:
            colored = _fill_rank_hint(rgb_np[max(0, box[1]):box[3], max(0, box[0]):box[2]]) in (4, 5)
        except (ValueError, cv2.error):
            colored = False
        text, conf = _read_name_enhanced(rgb_np, box, langs, f"line_{n:02d}_B", color_first=colored)
        name_part = _line_name_part(ln)
        if label_n:
            name_part = " ".join(w["text"] for w in words[label_n:cut]) if cut is not None else ""
        better = colored and _NAME_WORD_RE.search(text) and (
            _name_candidate_score(text, None)[0] >= _name_candidate_score(name_part, None)[0] - 0.02
            or conf >= old_conf)
        if (_NAME_WORD_RE.search(text) and _letter_ratio(text) >= OCR_MIN_LETTER_RATIO
                and (better or conf >= old_conf - OCR_B_CONF_MARGIN or old_conf < OCR_LOW_CONF)):
            right_text = " ".join(w["text"] for w in right_words)
            ln = dict(ln, text=f"{label_text} {text} {right_text}".strip(), refined=True,
                      text_src="B", name_conf=conf)
        elif label_n:                                        # подпись сохраняем в любом случае
            ln = dict(ln, text=f"{label_text} {name_part} {' '.join(w['text'] for w in right_words)}".strip())
        out.append(ln)
    return out


# ---------------------------------------------------------------------------
# НОВОЕ: цифровой проход по времени и чтение номера страницы «86/115»
# ---------------------------------------------------------------------------
_TIME_TOKEN_RE = re.compile(r"(\d{2}):(\d{2}):(\d{2})")


PAGE_INDICATOR_RE = re.compile(r"(?<![\d/])(\d{1,3})\s*[/|\\]\s*(\d{1,3})(?![\d/])")


PAGE_INFO = {}                  # путь файла -> (страница, всего) или None (заполняет run_ocr_pipeline)


PAGE_ALTS = {}                  # путь файла -> [((страница, всего), голосов), ...] — запасные прочтения


OCR_TIME_PASS = True            # False — не перечитывать время отдельным цифровым проходом


def parse_page_indicator(text: str):
    """Номер страницы истории из текста вида «86/115»: (номер, всего) или None."""
    for m in PAGE_INDICATOR_RE.finditer(text or ""):
        n, total = int(m.group(1)), int(m.group(2))
        if 1 <= n <= total <= 999:
            return n, total
    return None


def parse_page_indicator_loose(text: str) -> list:
    """ИСПРАВЛЕНО: Tesseract с цифровым списком знаков часто читает «/» как «1» («77/90» ->
    «77190») — страница не находилась, и порядок всего пакета строился по времени. Здесь строка
    из одних цифр разбирается по местам, где «разделитель» мог быть прочитан как «1» (чаще всего)
    или «7»; варианты упорядочены: сначала «1», затем с равной длиной номера и «всего».
    Возвращает список [(номер, всего), ...] по убыванию правдоподобия."""
    digits = re.sub(r"\D", "", text or "")
    if "/" in (text or "") or not 3 <= len(digits) <= 7:
        return []
    out = []
    for i in range(1, len(digits) - 1):
        if digits[i] not in "17":
            continue
        a, b = digits[:i], digits[i + 1:]
        if not (1 <= len(a) <= 3 and 1 <= len(b) <= 3) or a[0] == "0" or b[0] == "0":
            continue
        n, total = int(a), int(b)
        if 1 <= n <= total <= 999:
            out.append(((digits[i] != "1", abs(len(a) - len(b)), i), (n, total)))
    out.sort()
    return [pg for _k, pg in out]


# Цифры, которые Tesseract путает в наклонном шрифте номера страницы («39/55» -> «59/55»)
_PAGE_DIGIT_SWAP = {"5": "3", "3": "5", "1": "7", "7": "1", "0": "8", "8": "0", "6": "8",
                    "9": "8", "2": "7"}


def parse_page_indicator_repairs(text: str) -> list:
    """Исправление ОШИБОЧНОГО прочтения номера страницы. Если прочитано невозможное «59/55»
    (номер больше общего числа страниц), одна цифра номера заменяется на похожую (5<->3, 1<->7,
    0<->8 …); у трёхзначного номера пробуется ещё и отбрасывание лишней цифры («357/55» ->
    «37/55»). Возвращает список правдоподобных (номер, всего), лучшие первыми; пусто, если
    прочтение и так корректно или ничего не подошло."""
    out = []
    for m in PAGE_INDICATOR_RE.finditer(text or ""):
        n_txt, total = m.group(1), int(m.group(2))
        n = int(n_txt)
        if 1 <= n <= total <= 999 or not 1 <= total <= 999:
            continue
        bases = [n_txt]
        if len(n_txt) == 3:
            bases += [n_txt[:i] + n_txt[i + 1:] for i in range(3)]
        for b in bases:
            for i, ch in enumerate(b):
                alt = _PAGE_DIGIT_SWAP.get(ch)
                if alt is None:
                    continue
                cand = b[:i] + alt + b[i + 1:]
                if cand[0] != "0" and 1 <= int(cand) <= total and (int(cand), total) not in out:
                    out.append((int(cand), total))
        for b in bases[1:]:
            if b[0] != "0" and 1 <= int(b) <= total and (int(b), total) not in out:
                out.append((int(b), total))
    return out[:4]


def _tess_digits(img, whitelist: str, psm: int = 7) -> str:
    """Чтение картинки Tesseract только с разрешёнными знаками (цифры, «:», «/»)."""
    cfg = (f"--psm {psm} --oem 1 -c user_defined_dpi=300 "
           f"-c tessedit_char_whitelist={whitelist}")
    try:
        return pytesseract.image_to_string(img, lang="eng", config=cfg).strip()
    except (pytesseract.TesseractError, pytesseract.TesseractNotFoundError, RuntimeError):
        return ""


def _refine_time_column(lines: list, src) -> list:
    """Отдельный цифровой проход по времени «ЧЧ:ММ:СС» каждой строки: узкая вырезка, несколько
    вариантов обработки, Tesseract только с цифрами. Голосование: значение первого прохода и
    все прочтения; побеждает большинство (при равенстве — первый проход). Если прочтения
    расходятся и большинства нет — строка помечается сомнительной (жёлтая, в редактор)."""
    if not OCR_TIME_PASS or cv2 is None or np is None or not lines:
        return lines
    rgb = np.array(src)
    height, width = rgb.shape[:2]
    budget = OCR_ENHANCE_ROWS
    for ln in lines:
        words = ln.get("words") or []
        idx = next((i for i in range(len(words) - 1, -1, -1)
                    if _TIME_TOKEN_RE.search(words[i]["text"])), None)
        if idx is None or budget <= 0:
            continue
        budget -= 1
        w = words[idx]
        first = _TIME_TOKEN_RE.search(w["text"]).group(0)
        x0, y0, x1, y1 = (int(v) for v in w["box"])
        padv = max(OCR_PAD, (y1 - y0) // 3)
        crop = rgb[max(0, y0 - padv):min(height, y1 + padv),
                   max(0, x0 - OCR_PAD):min(width, x1 + OCR_PAD)]
        if crop.shape[0] < 4 or crop.shape[1] < 8:
            continue
        try:
            variants = enhance_text_crop_variants(crop)
        except cv2.error:
            continue
        votes = [first]
        for v in variants:
            m = re.fullmatch(r"\D*(\d{2}:\d{2}:\d{2})\D*", _tess_digits(v, "0123456789:"))
            if m:
                votes.append(m.group(1))
        if len(votes) == 1:
            continue                                   # цифровой проход ничего не прочитал
        best, n = Counter(votes).most_common(1)[0]
        if n < 2:
            ln["time_doubt"] = True                    # все прочтения разные
            continue
        if best != first:
            pos = ln["text"].rfind(first)
            if pos >= 0:
                ln["text"] = ln["text"][:pos] + best + ln["text"][pos + len(first):]
            w["text"] = w["text"].replace(first, best)
            ln["time_fixed"] = (first, best)
    return lines


def _day_word_index(words: list):
    """Индекс слова-ДНЯ в строке таблицы («13» перед «май. 2026»): число 1–2 цифры (или
    буква-двойник цифры) + слово-месяц + слово с цифрами (год). None, если даты нет."""
    idx = None
    for i in range(len(words) - 1):
        mon = words[i + 1]["text"].strip(".,")
        if (re.fullmatch(r"\d{1,2}|[БбЗзlI|]", words[i]["text"].strip())
                and re.fullmatch(r"[^\W\d_]{2,9}", mon) and month_from_token(mon) is not None
                and i + 2 < len(words) and re.search(r"\d", words[i + 2]["text"])):
            idx = i
    return idx


def _refine_qty_column(lines: list, src) -> list:
    """Отдельный цифровой проход по КОЛИЧЕСТВУ (слово перед днём даты): «30» у потерянного
    фрагмента читалось как «50» (3<->5), из-за чего в статистику попадало неверное число.
    Узкая вырезка, несколько вариантов обработки, Tesseract только с цифрами; побеждает
    значение, прочитанное минимум дважды (первый проход тоже голосует). Количество «1»
    (дуги, персонажи, кубики) не перечитывается: его ошибка не возможна на практике."""
    if not OCR_TIME_PASS or cv2 is None or np is None or not lines:
        return lines
    rgb = np.array(src)
    height, width = rgb.shape[:2]
    budget = OCR_ENHANCE_ROWS
    for ln in lines:
        words = ln.get("words") or []
        if budget <= 0:
            break
        di = _day_word_index(words)
        if di is None or di < 1:
            continue
        w = words[di - 1]
        first = w["text"].strip()
        if not re.fullmatch(r"\d{1,3}", first):
            continue
        if first == "1" and not re.search(r"куб|шулер|тв[её]рд", ln["text"], re.I):
            continue                    # у дуг и персонажей количество всегда 1
        budget -= 1
        x0, y0, x1, y1 = (int(v) for v in w["box"])
        padv = max(6, (y1 - y0) // 2)
        crop = rgb[max(0, y0 - padv):min(height, y1 + padv),
                   max(0, x0 - OCR_PAD):min(width, x1 + OCR_PAD)]
        if crop.shape[0] < 4 or crop.shape[1] < 8:
            continue
        try:
            variants = enhance_text_crop_variants(crop)
        except cv2.error:
            continue
        low_text = ln["text"].lower()
        if re.search(r"куб|шулер|тв[её]рд", low_text):
            allowed = ("1", "5")                 # кубики: 1 или 5 шт
        elif re.search(r"искр|warp", low_text):
            allowed = None                       # Фрагмент искривления: любое число (4, 16, 30…)
        elif re.search(r"потер|фрагм|lost", low_text):
            allowed = ("30", "50")               # Потерянный фрагмент: 30 или 50 шт
        else:
            allowed = None
        votes = [first]
        for v in variants:
            m = re.fullmatch(r"\D*(\d{1,3})\D*", _tess_digits(v, "0123456789"))
            if m and m.group(1)[0] != "0":
                votes.append(m.group(1))
        if allowed:                              # невозможные для предмета значения не голосуют
            votes = [v for v in votes if v in allowed]
            if not votes:
                continue
        best, n = Counter(votes).most_common(1)[0]
        if allowed is None and re.search(r"искр|warp", low_text):
            known = QTY_OPTIONS["warp_fragment"]       # 30 / 16 / 4: «50» вместо «30» — ошибка 3<->5
            if first not in known and any(v in known for v in votes):
                best, n = Counter(v for v in votes if v in known).most_common(1)[0]
                n = max(n, 2)
        if best == first or (n < 2 and (not allowed or first in allowed)):
            continue
        pos = ln["text"].rfind(f"{first} {words[di]['text']}")
        if pos < 0:
            continue
        ln["text"] = ln["text"][:pos] + best + ln["text"][pos + len(first):]
        w["text"] = best
        ln["qty_fixed"] = (first, best)
    return lines


def _refine_date_column(lines: list, src) -> list:
    """Отдельный цифровой проход по ДНЮ месяца каждой строки («13 май. 2026 г.»): у Tesseract
    «13» часто превращается в «15», а «5» — в «Б». Узкая вырезка числа, несколько вариантов
    обработки, Tesseract только с цифрами; побеждает значение, которое прочитали минимум два
    раза (первый проход тоже голосует, если это число). Исправленная строка помечается
    ln["day_fixed"]; нет большинства — строка остаётся как есть."""
    if not OCR_TIME_PASS or cv2 is None or np is None or not lines:
        return lines
    rgb = np.array(src)
    height, width = rgb.shape[:2]
    budget = OCR_ENHANCE_ROWS
    for ln in lines:
        words = ln.get("words") or []
        if budget <= 0:
            break
        idx = _day_word_index(words)
        if idx is None:
            continue
        budget -= 1
        w = words[idx]
        first = w["text"].strip()
        x0, y0, x1, y1 = (int(v) for v in w["box"])
        padv = max(6, (y1 - y0) // 2)
        crop = rgb[max(0, y0 - padv):min(height, y1 + padv),
                   max(0, x0 - OCR_PAD):min(width, x1 + OCR_PAD)]
        if crop.shape[0] < 4 or crop.shape[1] < 8:
            continue
        try:
            variants = enhance_text_crop_variants(crop)
        except cv2.error:
            continue
        votes = [first] if first.isdigit() else []
        for v in variants:
            m = re.fullmatch(r"\D*(\d{1,2})\D*", _tess_digits(v, "0123456789"))
            if m and 1 <= int(m.group(1)) <= 31:
                votes.append(str(int(m.group(1))))
        if not votes:
            continue
        best, n = Counter(votes).most_common(1)[0]
        if n < 2 or best == first:
            continue
        mon_text = words[idx + 1]["text"]
        pos = ln["text"].rfind(f"{first} {mon_text}")
        if pos < 0:
            continue
        ln["text"] = ln["text"][:pos] + best + ln["text"][pos + len(first):]
        w["text"] = best
        ln["day_fixed"] = (first, best)
    return lines


def _find_page_in_lines(raw_lines: list, table_lines: list):
    """Номер страницы среди строк первого прохода: нижняя строка без даты, ниже таблицы."""
    anchors = [ln for ln in table_lines if DATE_RE.search(ln["text"])]
    floor = max((ln["box"][3] for ln in anchors), default=-1)
    best = None
    for ln in raw_lines:
        if DATE_RE.search(ln["text"]) or ln["box"][1] < floor - 2:
            continue
        found = parse_page_indicator(ln["text"])
        if found:
            best = found
            break
    return best


def _page_bar_crops(rgb, top: int, med_h: int) -> list:
    """Кандидаты вырезок для номера страницы. Номер стоит в центре окна на тёмной плашке между
    кнопками «Назад» и «Далее»: ищется ближайшая к таблице тёмная полоса в центральной части
    снимка (кнопки по бокам в неё не попадают). Запасной вариант — центральная полоса под
    таблицей. Возвращает список картинок RGB."""
    h, w = rgb.shape[:2]
    cx0, cx1 = int(w * 0.44), int(w * 0.56)
    top = max(0, min(h - 1, top))
    out = []
    gray = cv2.cvtColor(rgb[top:, cx0:cx1], cv2.COLOR_RGB2GRAY)
    dark = gray.mean(axis=1) < 90
    y, n = 0, len(dark)
    while y < n:
        if not dark[y]:
            y += 1
            continue
        k = y
        while k < n and dark[k]:
            k += 1
        if 0.4 * med_h <= k - y <= 3 * med_h:
            pad = max(2, (k - y) // 8)
            out.append(rgb[top + max(0, y - pad):min(h, top + k + pad), cx0:cx1])
            break
        y = k
    out.append(rgb[top:min(h, top + int(7 * med_h)), cx0:cx1])
    return out


def _read_page_below(src, table_lines: list):
    """Запасное чтение «N/M», когда общий проход его не увидел (белые цифры на чёрной плашке):
    вырезка плашки под таблицей, увеличение ×2/×3/×4, серый и бинарный вариант, Tesseract только
    с цифрами и «/». Голосование: побеждает самое частое прочтение. Возвращает
    (страница или None, список [(страница, голосов), ...] по убыванию голосов)."""
    if cv2 is None or np is None:
        return None, []
    anchors = [ln for ln in table_lines if DATE_RE.search(ln["text"])]
    if not anchors:
        return None, []
    heights = sorted(ln["box"][3] - ln["box"][1] for ln in anchors)
    med_h = max(8, heights[len(heights) // 2])
    rgb = np.array(src)
    votes = Counter()
    for crop in _page_bar_crops(rgb, int(max(ln["box"][3] for ln in anchors)), med_h):
        if crop.shape[0] < 8 or crop.shape[1] < 16:
            continue
        base = cv2.cvtColor(crop, cv2.COLOR_RGB2GRAY)
        for fx in (2, 3, 4):
            gray = cv2.resize(base, None, fx=fx, fy=fx, interpolation=cv2.INTER_CUBIC)
            if float(gray.mean()) < 110:                  # светлые цифры на тёмном -> наоборот
                gray = cv2.bitwise_not(gray)
            gray = cv2.copyMakeBorder(gray, 20, 20, 20, 20, cv2.BORDER_CONSTANT, value=255)
            imgs = [gray]
            try:
                imgs.append(cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)[1])
            except cv2.error:
                pass
            for img in imgs:
                raw = _tess_digits(img, "0123456789/", 7)
                found = parse_page_indicator(raw)
                if found:
                    votes[found] += 1
                else:
                    fixed = parse_page_indicator_repairs(raw)
                    if fixed:                  # «59/55» -> «39/55»: невозможный номер
                        for k, cand in enumerate(fixed):
                            votes[cand] += 0.9 if k == 0 else 0.1
                        continue
                    for k, cand in enumerate(parse_page_indicator_loose(raw)[:3]):
                        votes[cand] += 1 if k == 0 else 0.1
        if votes:
            break
    alts = votes.most_common()
    return (alts[0][0] if alts else None), alts


def _fill_row_gaps(lines: list) -> list:
    """ИСПРАВЛЕНО (счётчик гаранта): строку, которую OCR потерял, нельзя достраивать в конец
    страницы — тогда сдвигается порядок всех записей ниже/выше неё (персонаж на 2-й позиции
    сверху становился 5-м вместо 4-го). Здесь по геометрии находятся пропуски между строками и
    над первой строкой (под заголовком таблицы) и на их место вставляются строки-«пустышки»
    с общим временем страницы: дальше разбор видит их как строки без названия на своём месте
    и помечает для проверки. Вставляется не больше, чем нужно до OCR_PAGE_SIZE строк."""
    dated = [ln for ln in lines if DATE_RE.search(ln["text"])]
    if len(dated) < 3:
        return lines
    last_y = max(ln["box"][3] for ln in dated)
    first_y = min(ln["box"][1] for ln in dated)
    head = [ln for ln in lines if ln["box"][3] <= first_y + 2 and not DATE_RE.search(ln["text"])]
    header = max(head, key=lambda ln: ln["box"][3]) if head else None
    rows = sorted((ln for ln in lines if ln["box"][1] >= first_y - 2 and ln["box"][3] <= last_y + 2),
                  key=lambda ln: ln["box"][1])
    if len(rows) < 3 or len(rows) >= OCR_PAGE_SIZE:
        return lines
    mid = [(ln["box"][1] + ln["box"][3]) / 2 for ln in rows]
    diffs = sorted(b - a for a, b in zip(mid, mid[1:]) if b - a > 4)
    if len(diffs) < 2:
        return lines
    near = [d for d in diffs if d <= diffs[0] * 1.35]
    pitch = near[len(near) // 2]
    stamps = Counter(m.group() for ln in dated for m in [DATE_RE.search(ln["text"])])
    stamp = stamps.most_common(1)[0][0]
    x0 = min(ln["box"][0] for ln in rows)
    x1 = max(ln["box"][2] for ln in rows)
    height = sum(ln["box"][3] - ln["box"][1] for ln in rows) / len(rows)
    room = OCR_PAGE_SIZE - len(rows)
    new = []

    def blank(center):
        return {"text": stamp, "box": (x0, int(center - height / 2), x1, int(center + height / 2)),
                "words": [], "name_left": x0, "synthetic": True}

    if header is not None:
        top_gap = mid[0] - (header["box"][1] + header["box"][3]) / 2
        k = min(room, max(0, round(top_gap / pitch - 1.2))) if top_gap >= 1.8 * pitch else 0
        for i in range(k, 0, -1):
            new.append(blank(mid[0] - i * pitch))
        room -= k
    for a, b in zip(mid, mid[1:]):
        if room > 0 and b - a >= 1.7 * pitch:
            k = min(room, round((b - a) / pitch) - 1)
            new += [blank(a + i * pitch) for i in range(1, k + 1)]
            room -= k
    if not new:
        return lines
    return sorted(lines + new, key=lambda ln: (ln["box"][1], ln["box"][0]))


def _header_icon_center(lines: list):
    """Центр столбца «Результат броска» (x) по заголовку таблицы, если он найден среди строк."""
    def like(word, target):
        return difflib.SequenceMatcher(None, fold_name(word), fold_name(target)).ratio() >= 0.75
    for ln in lines:
        words = ln.get("words") or ()
        hit = next((i for i, w in enumerate(words) if like(w["text"], "результат")), None)
        if hit is None:
            continue
        group = [words[hit]["box"]]
        if hit + 1 < len(words) and like(words[hit + 1]["text"], "броска"):
            group.append(words[hit + 1]["box"])
        return (min(b[0] for b in group) + max(b[2] for b in group)) / 2.0
    return None


def _header_label_right(lines: list):
    """Правая граница столбца «Результат броска» (x) по заголовку: всё, что целиком левее неё,
    — подпись левого столбца («Страна сна», «Подарок за очки») или значок, но не название."""
    def like(word, target):
        return difflib.SequenceMatcher(None, fold_name(word), fold_name(target)).ratio() >= 0.75
    for ln in lines:
        words = ln.get("words") or ()
        hit = next((i for i, w in enumerate(words) if like(w["text"], "результат")), None)
        if hit is None:
            continue
        box = words[hit]["box"]
        if hit + 1 < len(words) and like(words[hit + 1]["text"], "броска"):
            return float(words[hit + 1]["box"][2])
        return float(box[2] + 0.6 * (box[2] - box[0]))
    return None


def _flag_rows_without_icon(lines: list, src) -> list:
    """ИСПРАВЛЕНО (счётчик): в таблице бросков у каждой ОБЫЧНОЙ строки в левом столбце стоит значок
    кубика, а у «Подарок за очки» / «Страна сна» вместо него — подпись. Подпись OCR иногда не читает
    («Страна с нева»), и тогда бонусная строка считалась обычной круткой и сдвигала гарант на 1.
    Строка без значка кубика (при заголовке «Результат броска» и значках у остальных строк) без
    прочитанной подписи получает «Подарок за очки»: бонус и «Страна сна» одинаково не меняют счётчик."""
    if cv2 is None or np is None or len(lines) < 3:
        return lines
    cx = _header_icon_center(lines)
    rows = [ln for ln in lines if not ln.get("synthetic") and DATE_RE.search(ln.get("text") or "")]
    if cx is None or len(rows) < 3:
        return lines
    mids = sorted((ln["box"][1] + ln["box"][3]) / 2.0 for ln in rows)
    diffs = sorted(b - a for a, b in zip(mids, mids[1:]) if b - a > 8)
    if not diffs:
        return lines
    pitch = diffs[len(diffs) // 2]
    rgb = np.array(src).astype(int)
    height, width = rgb.shape[:2]
    half = 0.30 * pitch
    flags = {}
    for ln in rows:
        yc = (ln["box"][1] + ln["box"][3]) / 2.0
        y0, y1 = int(max(0, yc - half)), int(min(height, yc + half))
        x0, x1 = int(max(0, cx - half)), int(min(width, cx + half))
        if y1 - y0 < 4 or x1 - x0 < 4:
            continue
        reg = rgb[y0:y1, x0:x1]
        gray = ((np.abs(reg[:, :, 0] - reg[:, :, 1]) < 14) & (np.abs(reg[:, :, 1] - reg[:, :, 2]) < 14)
                & (reg[:, :, 0] > 55) & (reg[:, :, 0] < 115))
        flags[id(ln)] = float(gray.mean()) >= 0.45          # есть значок кубика
    if len(flags) < 3 or sum(flags.values()) < 0.6 * len(flags) or all(flags.values()):
        return lines
    out = []
    for ln in lines:
        if flags.get(id(ln)) is False and _line_has_name(ln):
            t = ln["text"]
            if not (BONUS_MARK_RE.search(t) or STRANA_SNA_RE.search(t)):
                # «Фрагмент искривления» без значка кубика — награда «Страна сна», не бонус
                mark = "Страна сна" if re.search(r"искр|warp", t, re.I) else "Подарок за очки"
                ln = dict(ln, text=f"{mark} {t}", no_icon=True)
        out.append(ln)
    return out


def _ocr_pipeline(src, info=None) -> list:
    """Конвейер на OpenCV: серая картинка (≤×2) -> проход 1 (весь снимок, один запуск) ->
    группировка по строкам -> отсев мусора и строк вне таблицы -> перечитывание слабых названий.
    src — Pillow RGB. Возвращает строки в координатах src."""
    scale = _choose_scale(src.width, src.height)
    gray = _prepare_gray(src, scale)
    _save_debug("gray_prepared", gray)
    words, lang = _layout_pass(gray, scale)
    raw = _group_words(words)
    lines = _filter_table_lines(raw)
    lines = _refine_name_column(lines, src, lang)
    lines = _refine_time_column(lines, src)
    lines = _refine_date_column(lines, src)
    lines = _refine_qty_column(lines, src)
    lines = _recover_missing_names(lines, src, lang)
    lines = _fill_row_gaps(lines)
    lines = _flag_rows_without_icon(lines, src)
    label_right = _header_label_right(lines)
    if label_right is not None:
        for ln in lines:
            ln["label_right"] = label_right
    if info is not None:
        page = _find_page_in_lines(raw, lines)
        alts = [(page, 1)] if page else []
        if page is None:
            page, alts = _read_page_below(src, lines)
        info["page"], info["page_alts"] = page, alts
    return lines


def _ocr_pipeline_pil(src, info=None) -> list:
    """Упрощённый конвейер без OpenCV: одна попытка --psm 6 по подготовленной Pillow картинке
    с той же очисткой мусора и группировкой строк."""
    img, scale = _prepare_for_ocr_pil(src)
    words, _, err = _run_langs(img, OCR_PSM_LAYOUT, scale)
    if words is None:
        raise OcrError(f"Ошибка распознавания:\n{err}")
    raw = _group_words(words)
    lines = [dict(ln, name_left=ln["box"][0]) for ln in _filter_table_lines(raw)]
    if info is not None:
        info["page"] = _find_page_in_lines(raw, lines)
    return lines


def ocr_image(path: str, roi=None, info=None) -> list:
    """Распознаёт текст на изображении. Возвращает строки [{"text", "box", "name_left", ...}]
    в порядке сверху вниз; box и name_left — в пикселях ИСХОДНОГО файла (нужны цветовому
    анализу рангов). roi — область таблицы в долях снимка (левый, верхний, правый, нижний);
    по умолчанию OCR_TABLE_ROI. Бросает OcrError с понятным текстом."""
    if pytesseract is None or Image is None:
        raise OcrError("Для распознавания скриншотов нужны библиотеки:\n"
                       "    pip install pytesseract pillow opencv-python numpy\n"
                       "и программа Tesseract OCR с языковым пакетом rus.")
    if TESSERACT_WIN_PATH.is_file():
        pytesseract.pytesseract.tesseract_cmd = str(TESSERACT_WIN_PATH)
    try:
        src = ImageOps.exif_transpose(Image.open(path)).convert("RGB")
    except (OSError, ValueError, Image.DecompressionBombError) as e:
        raise OcrError(f"Не удалось открыть изображение:\n{e}") from e

    # необязательная вырезка области таблицы; смещение вернём в координаты полного снимка
    ox = oy = 0
    roi = roi if roi is not None else OCR_TABLE_ROI
    if roi:
        fl, ft, fr, fb = (min(1.0, max(0.0, float(v))) for v in roi)
        box = (int(src.width * fl), int(src.height * ft),
               int(src.width * fr), int(src.height * fb))
        if box[2] - box[0] > 50 and box[3] - box[1] > 50:
            src, (ox, oy) = src.crop(box), box[:2]

    if cv2 is not None and np is not None:
        lines = _ocr_pipeline(src, info)
    else:
        lines = _ocr_pipeline_pil(src, info)

    if ox or oy:
        def shift(b):
            return (b[0] + ox, b[1] + oy, b[2] + ox, b[3] + oy)
        for ln in lines:
            ln["box"] = shift(ln["box"])
            ln["name_left"] = ln.get("name_left", ln["box"][0] - ox) + ox
            for w in ln.get("words", ()):
                w["box"] = shift(w["box"])
    return lines


# ---------------------------------------------------------------------------
# Анализ цвета рамки / фона слота -> ранг S / A / B
# ---------------------------------------------------------------------------
# Для каждого цветового диапазона строится бинарная маска средствами Pillow
# (таблицы подстановки + умножение масок — всё на C), а пиксели считаются по
# гистограмме: на порядок быстрее попиксельного цикла на Python.
def _hue255(deg: float) -> int:
    """Оттенок из градусов (0..360) в шкалу Pillow (0..255)."""
    return int(deg * 255 / 360)


def _lut_mask(band, lo, hi):
    """Маска канала: 255 там, где значение лежит в [lo, hi], иначе 0."""
    lo, hi = int(lo), int(hi)
    return band.point([255 if lo <= v <= hi else 0 for v in range(256)])


def _hsv_count(h, s, v, hue, sat, val) -> int:
    """Число пикселей, у которых оттенок, насыщенность и яркость лежат в заданных диапазонах."""
    mask = _lut_mask(h, *hue)
    for band, rng in ((s, sat), (v, val)):
        mask = ImageChops.multiply(mask, _lut_mask(band, *rng))
    return mask.histogram()[255]


def classify_rarity_color(region):
    """OCR-ФИКС: ранг по цвету ТЕКСТА в области region (PIL.Image с названием предмета).

    Золотистый / жёлтый текст -> 5 (S), фиолетовый / пурпурный -> 4 (A), серый, белый или
    тёмный -> 3 (B). Если текста в области не нашлось (слишком мало пикселей) — None.

    Как считается: фоном считается медианный цвет области; «текст» — пиксели, заметно
    отличающиеся от фона (TEXT_FG_DIFF). Среди них считаются золотые и фиолетовые (по
    оттенку, насыщенности и яркости). Если одного из цветов не меньше
    TEXT_COLOR_MIN_FRACTION всех пикселей текста — это S или A (побеждает тот, которого
    больше); иначе текст бесцветный (серый / белый / тёмный) — это B."""
    img = region.convert("RGB")
    factor = max(1, max(img.size) // 640)  # уменьшаем крупные области (быстрее считать)
    if factor > 1:
        img = img.reduce(factor)
    if img.width * img.height < TEXT_MIN_PIXELS:
        return None
    bg = tuple(int(v) for v in ImageStat.Stat(img).median)
    diff = ImageChops.difference(img, Image.new("RGB", img.size, bg))
    dr, dg, db = diff.split()
    dmax = ImageChops.lighter(ImageChops.lighter(dr, dg), db)
    text_mask = dmax.point([255 if v >= TEXT_FG_DIFF else 0 for v in range(256)])
    text_px = text_mask.histogram()[255]
    if text_px < TEXT_MIN_PIXELS:
        return None
    h, s, v = img.convert("HSV").split()  # в Pillow H, S, V лежат в диапазоне 0..255

    def count(hue, sat, val) -> int:
        """Сколько пикселей ТЕКСТА попадает в цветовой диапазон."""
        mask = _lut_mask(h, *tuple(map(_hue255, hue)))
        for band, rng in ((s, (sat[0] * 255, 255)), (v, (val[0] * 255, 255))):
            mask = ImageChops.multiply(mask, _lut_mask(band, *rng))
        return ImageChops.multiply(mask, text_mask).histogram()[255]

    gold = count(GOLD_HUE, (GOLD_MIN_SAT,), (GOLD_MIN_VAL,))
    purple = count(PURPLE_HUE, (PURPLE_MIN_SAT,), (PURPLE_MIN_VAL,))
    if max(gold, purple) / text_px >= TEXT_COLOR_MIN_FRACTION:
        return 5 if gold >= purple else 4
    return 3


def _left_label_count(words: list) -> int:
    """ИСПРАВЛЕНО: число первых слов строки, образующих подпись ЛЕВОГО столбца («Подарок за очки»,
    «Страна сна»). Раньше подпись входила в рамку названия: цвет считался вместе с серыми буквами
    подписи (фиолетовая дуга читалась как серая), а название перечитывалось вместе с подписью, и
    Tesseract выдавал мусор («NlepeerEnx Ayana» вместо «Персонаж - Аурелия»)."""
    for k, label in ((3, "подарок за очки"), (2, "страна сна"), (3, "страна сна")):
        if len(words) <= k:
            continue
        joined = " ".join(w["text"] for w in words[:k])
        if (BONUS_MARK_RE if label[0] == "п" else STRANA_SNA_RE).search(joined) or difflib.SequenceMatcher(
                None, re.sub(r"\W", "", fold_name(joined)), fold_name(label.replace(" ", ""))).ratio() >= 0.72:
            return k
    return 0


def _label_canon(words: list, k: int) -> str:
    if not k:
        return ""
    joined = " ".join(w["text"] for w in words[:k])
    return "Страна сна" if (STRANA_SNA_RE.search(joined) or fold_name(joined)[:3] == fold_name("стр")) \
        and not BONUS_MARK_RE.search(joined) and fold_name(joined)[:1] != fold_name("п") else "Подарок за очки"


def _name_box(ln: dict):
    """OCR-ФИКС: рамка ТЕКСТА названия в строке (x0, y0, x1, y1) в пикселях исходного
    снимка — от первого слова до столбца «Количество» / «Время». Значки слева и числа с датой
    справа в рамку не входят, поэтому цвет считается только по буквам названия.
    Нет слов у строки — берётся левая часть рамки строки."""
    if ln.get("name_box"):               # рамка названия, найденная по цвету (_recover_missing_names)
        return tuple(int(v) for v in ln["name_box"])
    words = ln.get("words") or []
    first = next((i for i, w in enumerate(words) if _NAME_WORD_RE.search(w["text"])), None)
    if first is not None:
        label_n = _left_label_count(words[first:])
        first += label_n                                    # подпись левого столбца — не название
        lr = ln.get("label_right")
        if lr is not None:       # слова целиком в левом столбце (подпись, которую OCR исказил)
            while first < len(words) - 1 and words[first]["box"][2] <= lr + 4:
                first += 1
                label_n += 1
        idx = _right_column_index(words, first + 1)
        chosen = words[first:idx] if idx is not None else words[first:]
        if chosen:
            x0 = min(w["box"][0] for w in chosen)
            x1 = max(w["box"][2] for w in chosen)
            if label_n:        # слова названия могли слиться с подписью: рамка — от конца подписи
                x0 = min(x0, int(words[first - 1]["box"][2]) + 2)
                if idx is not None:
                    x1 = max(x1, int(words[idx]["box"][0]) - 4)
            return (x0, min(w["box"][1] for w in chosen), x1, max(w["box"][3] for w in chosen))
    left, top, right, bottom = ln["box"]
    left = int(ln.get("name_left", left))
    return left, top, left + int(0.55 * max(1, right - left)), bottom


def detect_rarity_colors(path: str, lines: list):
    """Цветовой анализ скриншота по ЦВЕТУ ТЕКСТА названия. Возвращает (ранги по строкам, None).

    OCR-ФИКС: вместо значка слева от названия (так ранг определялся в последней версии)
    анализируется вырезка с самим текстом названия каждой строки: жёлтый -> S (5),
    фиолетовый -> A (4), серый / белый / тёмный -> B (3). Второй элемент результата всегда
    None (цвет всего снимка не используется: на нём всегда есть золотые элементы).
    Нет Pillow, файл не открылся или текст не найден — ранг строки None."""
    empty = ([None] * len(lines), None)
    if Image is None:
        return empty
    try:
        img = ImageOps.exif_transpose(Image.open(path)).convert("RGB")
    except (OSError, ValueError, Image.DecompressionBombError):
        return empty
    width, height = img.size
    ranks = []
    for ln in lines:
        x0, y0, x1, y1 = _name_box(ln)
        pad_x = max(4, (y1 - y0) // 3)
        pad_y = max(2, (y1 - y0) // 3)   # рамка слов бывает уже буквы с обводкой: золото обрезалось и читалось серым
        x0, x1 = max(0, x0 - pad_x), min(width, x1 + pad_x)
        y0, y1 = max(0, y0 - pad_y), min(height, y1 + pad_y)
        if x1 - x0 < 8 or y1 - y0 < 4:
            ranks.append(None)                           # области текста нет — цвет не используем
            continue
        ranks.append(classify_rarity_color(img.crop((x0, y0, x1, y1))))
    return ranks, None


# Значок кубика (🎲, ⚀–⚅). Это ЗАПАСНОЙ признак: тип в первую очередь берётся из текста.
DICE_RE = re.compile("[\U0001F3B2\u2680-\u2685\uFE0F]+")


def _cube_qty(low: str) -> str:
    """Количество кубиков в строке: «5» для «×5» / «5 шт», иначе «1»."""
    return "5" if re.search(r"[x×х]\s*5\b|\b5\s*(?:шт|pcs)", low) else "1"


def split_fused_item_label(text: str) -> str:
    """OCR-ФИКС: разделяет слово «Предмет», слипшееся с названием.

    Tesseract читает «Предмет - Потерянный фрагмент» как «предметтолерянны Фравмени»: дефис и
    пробел потеряны, а «Предмет» приклеено к первому слову названия. Если первое слово строки
    длинное (9+ букв) и его начало похоже на «предмет» (допускаются ошибки OCR), оно
    разделяется: «предметтолерянны Фравмени» -> «Предмет - толерянны Фравмени».
    Обычные строки (в том числе имена персонажей) не меняются."""
    t = (text or "").lstrip(" |¦")
    m = re.match(r"([^\W\d_]{9,})(?=\s|$)", t)
    if not m:
        return text
    word = m.group(1)
    target = fold_name("предмет")
    best_k, best_score = 0, 0.0
    for k in (6, 7, 8):                       # «предмет» OCR мог потерять или добавить букву
        score = difflib.SequenceMatcher(None, fold_name(word[:k]), target).ratio()
        if score > best_score:
            best_k, best_score = k, score
    if best_score >= 0.80 and len(word) - best_k >= 4:
        return f"Предмет - {word[best_k:]}{t[m.end():]}"
    return text


# OCR-ФИКС 2: словарь известных искажений названий предметов. Из-за шрифта игры
# «Потерянный фрагмент» иногда читается как «Прут Фочеарякитый Фрезия». Слово из словаря
# (с допуском на одну-две опечатки OCR) делает строку предметом этого вида. Словарь МОЖНО
# ДОПОЛНЯТЬ: добавьте новое искажение в кортеж нужного вида.
GARBLED_ITEM_ALIASES = {
    # OCR-ФИКС 3: добавлены искажения «Потерянный фрагмент», которые Tesseract выдаёт из-за
    # шрифта игры («eB Tpamher Tlorepanneal реки», «толерянны Фравмени» и т. п.).
    "lost_fragment": ("Прут", "Фочеарякитый", "Фрезия",
                      "Tpamher", "Tlorepanneal", "Tlorepannei", "Tlorepaннeal",
                      "Фравмени", "Фрагмеит", "Фрагмени", "Потеряный", "Толерянны",
                      "Потерянныи", "Потерянныйфрагмент"),
}


GARBLED_MATCH_CUTOFF = 0.80   # минимальное сходство слова с искажением из словаря


GARBLED_MIN_LEN = 4           # короче 4 букв — только точное совпадение


# Количество, начиная с которого строка таблицы без префикса и без известного имени —
# предмет (потерянный фрагмент 30 / 50, фрагмент искривления 30), а не персонаж или дуга
LARGE_QTY_MIN = 30


# Символы-мусор в НАЧАЛЕ строки: всё, кроме букв, цифр и звёзд ранга ★ / ☆
_LEADING_JUNK_RE = re.compile(r"^(?:(?![★☆])[\W_])+")


_LOOKUP_SYMBOLS_RE = re.compile(r"[\[\]{}<>«»|¦\\/_~^`©®™•·°§=*#@]+")


_LOOKUP_LONE_RE = re.compile(r"(?<=\s)[^\w\s()\-–—:×★☆](?=\s)")


_TRAILING_JUNK_RE = re.compile(r"[\s.,;:!?\-–—'\"‘’“”]+$")


def clean_lookup_text(text: str) -> str:
    """Очистка строки ПЕРЕД поиском в мастер-справочнике: скобки, рамки, значки и одиночные
    знаки между словами заменяются пробелами; мусор в начале и конце срезается; повторы
    пробелов и точек схлопываются. Дефис, двоеточие, скобки-скобки «( )», «×» и «★» остаются."""
    t = _LOOKUP_SYMBOLS_RE.sub(" ", text or "")
    t = re.sub(r"\.{2,}", " ", t)
    t = re.sub(r"\s+", " ", t)
    t = _LOOKUP_LONE_RE.sub(" ", t)
    t = _TRAILING_JUNK_RE.sub("", t.strip())
    return re.sub(r"\s+", " ", strip_leading_junk(t)).strip()


def strip_leading_junk(text: str) -> str:
    """OCR-ФИКС 2: срезает с начала строки мусор до первой буквы или цифры: одиночные
    двоеточия, точки с запятой, дефисы, скобки, «|» и одиночные символы-мусор OCR
    («l», «I», «1») перед ними. «: Прут Фочеарякитый» -> «Прут Фочеарякитый»,
    «; Дуга - Клинок» -> «Дуга - Клинок». Звёзды ранга ★ / ☆ остаются."""
    t = (text or "").strip()
    for _ in range(4):                       # мусор мог идти вперемешку: «l : | Дуга»
        before = t
        t = _LEADING_JUNK_RE.sub("", t).strip()
        t = _trim_edge_junk(t)
        if t == before:
            break
    return t


def garbled_item_key(text: str):
    """OCR-ФИКС 2: ключ вида предмета (например, «lost_fragment»), если в тексте есть слово
    из словаря искажений GARBLED_ITEM_ALIASES, иначе None. Сравнение нечёткое: регистр,
    «ё/е» и похожие буквы (fold_name) не важны."""
    tokens = [t for t in re.findall(r"[^\W\d_]+", text or "") if len(t) >= GARBLED_MIN_LEN]
    for key, aliases in GARBLED_ITEM_ALIASES.items():
        for alias in aliases:
            target = fold_name(alias)
            for tok in tokens:
                folded = fold_name(tok)
                if folded == target or (
                        abs(len(folded) - len(target)) <= 2 and difflib.SequenceMatcher(
                            None, folded, target).ratio() >= GARBLED_MATCH_CUTOFF):
                    return key
    return None


# ---------------------------------------------------------------------------
# OCR-ФИКС 3: СТРОГОЕ правило «Потерянный фрагмент» (материал) — резерв для строк, которые
# из-за шрифта игры превращаются в мусор («eB Tpamher Tlorepanneal реки» и т. п.)
# ---------------------------------------------------------------------------
FRAGMENT_QTYS = ("30", "50")      # у потерянного фрагмента бывает только 30 или 50 шт


# Ключевые слова материала/фрагмента, включая типичные искажения OCR (кириллица + латиница):
# «фраг…», «фрагм…», «fragm…», «потер…» (потерянный), «tlor…» / «tpam…» (латинские
# двойники слов «Потерянный» / «Фрагмент»), «lost fr…».
FRAGMENT_KEYWORD_RE = re.compile(
    r"ф[рp][аa][гrвv]|фрагм|fragm|потер|tlor|tpam|lost\s*fr", re.I)


# Количество в сыром тексте после разбора строки: «×30», «x 50»
_RAW_QTY_RE = re.compile(r"[x×х]\s*(\d{1,3})(?!\d)", re.I)


# Порог «настоящего» имени: известное имя (история / состав / эталон дуги) не трогаем
FRAGMENT_KNOWN_CUTOFF = 0.80


def _qty_from_raw(text: str) -> str:
    """OCR-ФИКС 3: количество из хвоста «×N» сырого текста (или пустая строка)."""
    m = _RAW_QTY_RE.search(text or "")
    return m.group(1) if m else ""


def fragment_qty(qty, text: str = "") -> str:
    """OCR-ФИКС 3: количество потерянного фрагмента — строго «30» или «50».
    Цифры берутся из qty, а если их нет — из текста строки (отдельное 30 / 50). Любое
    значение, начинающееся на 5 («5», «50», «5О»), даёт 50, остальное — 30."""
    digits = re.sub(r"\D", "", str(qty or ""))
    if not digits:
        m = re.search(r"(?<!\d)(30|50)(?!\d)", text or "")
        digits = m.group(1) if m else ""
    return "50" if digits.startswith("5") else "30"


def warp_qty(qty, text: str = "") -> str:
    """Количество «Фрагмента искривления»: любое число 1…999 с экрана (в игре бывает 4, 16,
    30 …). Если цифр нет — 30."""
    digits = re.sub(r"\D", "", str(qty or ""))
    if not digits:
        m = re.search(r"(?<!\d)(\d{1,3})\s*(?:шт\.?)?\s*$", (text or "").strip())
        digits = m.group(1) if m else ""
    return str(int(digits)) if digits and 0 < int(digits) <= 999 else "30"


def _is_real_name(name: str, known: dict = None) -> bool:
    """OCR-ФИКС 3: настоящее (не мусорное) имя персонажа / дуги: есть в истории, в составе
    персонажей или похоже на эталонное название дуги. Нужна высокая точность совпадения,
    чтобы мусорная строка случайно не «прилипла» к имени."""
    name = (name or "").strip()
    if not name:
        return False
    index = {strip_labels(k, ("arc",)).lower(): k for k in (known or {})}
    if (name.lower() in index
            or difflib.get_close_matches(name.lower(), list(index), n=1,
                                         cutoff=FRAGMENT_KNOWN_CUTOFF)):
        return True
    if match_roster_name(name, cutoff=FRAGMENT_KNOWN_CUTOFF):
        return True
    snap = snap_known_phrase(name)
    return bool(snap and snap[1] not in ITEM_PHRASE_KEYS)      # эталон дуги («Забытое»…)


def strict_fragment_key(body: str, qty=None, known: dict = None):
    """OCR-ФИКС 3: «lost_fragment» / «warp_fragment» или None.

    Жёсткое правило «это материал, а не персонаж и не дуга». Срабатывает для строки без
    явного префикса «Дуга» / «Персонаж», которая НЕ является бонусом «Подарок за очки»
    и не содержит настоящего имени (история, состав, эталон дуги), если выполняется
    любое из условий:
      * есть ключевое слово фрагмента / материала (FRAGMENT_KEYWORD_RE), слово из словаря
        искажений (GARBLED_ITEM_ALIASES) или слово, похожее на «фрагмент»;
      * количество — 30 или 50 (у персонажей и дуг в таблице оно всегда 1), а название
        испорчено OCR и ни на какое известное имя не похоже.
    Вид «Фрагмент искривления» выбирается только при слове «искр» / «warp»."""
    if BONUS_MARK_RE.search(body or ""):
        return None                                    # бонусная добыча — не материал
    clean = strip_leading_junk(body or "")
    if leading_type(clean) in ("arc", "character"):
        return None                                    # явный префикс важнее догадок
    name = strip_labels(clean_name(clean), ("rank", "item"))
    if _is_real_name(name, known):
        return None
    low = clean.lower().replace("ё", "е")
    kind = "warp_fragment" if re.search(r"искр|warp", low) else "lost_fragment"
    if (FRAGMENT_KEYWORD_RE.search(clean) or garbled_item_key(clean)
            or _fragment_like_word(clean) or fragment_stem_hint(clean)):
        return kind
    digits = re.sub(r"\D", "", str(qty or ""))
    if not digits:
        m = re.search(r"(?<!\d)(30|50)(?!\d)", clean)
        digits = m.group(1) if m else ""
    if digits in FRAGMENT_QTYS or (digits and int(digits) >= LARGE_QTY_MIN):
        return kind
    return None


def forced_item_label(body: str, qty, known: dict = None):
    """OCR-ФИКС 2/3: жёсткое правило «это предмет, а не персонаж». Возвращает подпись вида
    «Предмет - Потерянный фрагмент» или None (тогда строка разбирается как обычно).

    Если обычный разбор (_loot_from_text) предмет сам не нашёл — решает строгое правило
    strict_fragment_key (ключевые слова, словарь искажений, количество 30 / 50)."""
    clean = strip_leading_junk(body)
    if leading_type(clean) in ("arc", "character"):
        return None                          # явный префикс важнее любых догадок
    if _loot_from_text(clean):
        return None                          # вид предмета нашёлся обычным способом
    key = strict_fragment_key(body, qty, known)
    return f"Предмет - {REWARD_KINDS[key]}" if key else None


def _fragment_like_word(text: str) -> bool:
    """OCR-ФИКС: есть ли в тексте слово, похожее на «фрагмент» («Фравмени», «фраг мент»)."""
    target = _phrase_form("фрагмент")
    tokens = re.findall(r"[^\W\d_]+", text or "")
    variants = tokens + [a + b for a, b in zip(tokens, tokens[1:])]
    return any(len(v) >= 5 and difflib.SequenceMatcher(None, _phrase_form(v), target).ratio() >= 0.70
               for v in variants)


def _item_key_from_snap(snap, low: str) -> str:
    """Ключ LOOT_TYPES по результату snap_known_phrase для предметов (кубики — с количеством)."""
    key = snap[1]
    return key + _cube_qty(low) if key in ("solid", "trick") else key


def recover_item_loot(body: str):
    """OCR-ФИКС («страховка»): пытается узнать предмет в строке, которую обычный разбор не
    смог определить. Вызывается только для строк с датой и количеством (то есть это
    точно запись таблицы). Возвращает эталонную подпись («Предмет - Потерянный фрагмент»)
    или None. Дуги и персонажи здесь не угадываются — только предметы."""
    rest = strip_labels(clean_name(split_fused_item_label(body)), ("rank", "item"))
    snap = snap_known_phrase(rest, PHRASE_RECOVER_CUTOFF, ITEM_PHRASE_KEYS)
    if snap:
        return f"Предмет - {snap[0]}"
    if _fragment_like_word(rest):             # искажённое «фрагмент»; «искр» — искривления
        return ("Предмет - Фрагмент искривления" if re.search(r"искр|warp", rest.lower())
                else "Предмет - Потерянный фрагмент")
    return None


def _loot_from_text(text: str, dice: bool = False):
    """Ключ LOOT_TYPES по тексту строки или None.

    ИСПРАВЛЕНО: порядок признаков (от надёжного к слабому):
      1) эталонное название с исправлением опечаток OCR (snap_known_phrase);
      2) ключевые слова: «кубик», «фрагмент», «костюм», «планер», «окраска», «скин», «кешбэк»;
      3) значок кубика 🎲 — только если в строке нет вообще никакого названия
         (раньше значок перебивал текст, и «🎲 Обнаженный клинок» становился кубиком).
    dice — значок кубика был в строке, но убран на этапе предобработки (prepare_ocr_row)."""
    low = text.lower().replace("ё", "е")
    snap = snap_known_phrase(text)
    if snap:
        key = snap[1]
        return key + _cube_qty(low) if key in ("solid", "trick") else key
    if "кубик" in low or "cube" in low:
        return ("trick" if re.search(r"шулер|trick", low) else "solid") + _cube_qty(low)
    if "фрагмент" in low or "fragment" in low:
        # «Фрагмент искривления» отличаем по корню «искр»; любой другой фрагмент считаем
        # потерянным — искажённое OCR слово «Потерянный» больше не теряет тип
        return "warp_fragment" if re.search(r"искр|warp", low) else "lost_fragment"
    for words, key in ((("окраск", "модификац"), "paint"), (("костюм", "outfit"), "outfit"),
                       (("планер", "glider"), "glider"), (("скин", "skin"), "car_skin")):
        if any(w in low for w in words):
            return key
    if any(w in low for w in ("кешб", "кэшб", "cashback")):
        return "cb_premium" if re.search(r"премиум|премиал|premium", low) else "cb_regular"
    # OCR-ФИКС: строка с префиксом «Предмет - …», название которой сильно искажено
    # («Предмет - толерянны Фравмени»). Раз это точно предмет, сравниваем с эталонами с
    # пониженным порогом и ищем искажённое слово «фрагмент»; дуги и персонажи не угадываются.
    # OCR-ФИКС 2: слово из словаря искажений («Прут», «Фочеарякитый», «Фрезия»)
    garbled = garbled_item_key(text)
    if garbled:
        return garbled
    if leading_type(text) == "item":
        rest = strip_labels(clean_name(text), ("rank", "item"))
        snap = snap_known_phrase(rest, PHRASE_ITEM_CUTOFF, ITEM_PHRASE_KEYS)
        if snap:
            return _item_key_from_snap(snap, low)
        if _fragment_like_word(rest):
            return "warp_fragment" if re.search(r"искр|warp", low) else "lost_fragment"
    if dice or DICE_RE.search(text):
        rest = strip_labels(clean_name(text), ("rank", "arc", "char", "item"))
        if not re.search(r"[^\W\d_]{3,}", rest):     # названия нет — остался только значок
            return "solid" + _cube_qty(low)
    return None


def _rarity_from_text(text: str):
    """Ранг, написанный в тексте: «ранг S», «rank A» или «5★» / ряд звёзд (старый вид).
    Возвращает 5/4/3 или None."""
    up = text.upper().translate(CYR_TO_LAT)
    m = re.search(r"(?:Р[АA]НГ|RANK)\W{0,3}([SAB])\b", up)
    if m:
        return LETTER_RANKS[m.group(1)]
    m = re.search(r"([345])\s*[★☆*]", text)
    if m:
        return int(m.group(1))
    m = re.search(r"[★☆*]{3,5}", text)
    return len(m.group()) if m else None


# ---------------------------------------------------------------------------
# НОВОЕ: очистка названий (персонаж / дуга)
# ---------------------------------------------------------------------------
JUNK_RE = re.compile(r"[|\[\]{}<>_~`\\^=]+")  # типичный мусор OCR


# Обозначения ранга внутри строки, которые не должны попасть в название
STAR_TOKEN_RE = re.compile(r"\(?\s*[345]\s*[★☆*]\s*\)?|[★☆*]{2,}|\b(?:ранг|rank)\W{0,3}[SAB]\b",
                           re.I)


# НОВОЕ: ранг в скобках — «(S)», «[A]»
RANK_PAREN_RE = re.compile(r"[(\[]\s*[SAB]\s*[)\]]")


# НОВОЕ: слова, по которым строка распознаётся как дуга
ARC_WORD_RE = re.compile(r"дуг|\barcs?\b|weapon|оружи", re.I)


# Префиксы, которые снимаются с начала названия:
#   ранг: «S », «Ранг A:», «Rank B -» (одиночная латинская S/A/B или кириллическая А/В);
#   тип дуги: «Дуга -», «Дуги:», «Arc», «Weapon»;
#   тип персонажа: «Персонаж:», «Character».
_RANK_PREFIX_RE = re.compile(r"^(?:(?i:ранг|rank)\W{0,3})?(?:[SAB]|[АВ])(?!\w)[\s:.\-–—)\]|]*")


_ARC_PREFIX_RE = re.compile(r"^(?i:[дл][уy][гrт][аиуеойa]*|arcs?|weapons?|оружие)(?!\w)[\s:.\-–—]*")


_CHAR_PREFIX_RE = re.compile(r"^(?i:персонаж\w*|character)(?!\w)[\s:.\-–—]*")


_QTY_SUFFIX_RE = re.compile(r"[\s(]*[x×х]\s*\d+\)?$", re.I)  # хвост «×1», «x 5»


# НОВОЕ: общий префикс предмета «Предмет - Твердый кубик» (с допусками на ошибки OCR).
# Он снимается из названия и сам по себе НЕ делает строку персонажем.
_ITEM_LABEL_RE = re.compile(r"^(?i:пр[еe]дм[еe][тn]\w*|items?)(?!\w)[\s:.\-–—]*")


_LABEL_PATTERNS = {"rank": _RANK_PREFIX_RE, "arc": _ARC_PREFIX_RE, "char": _CHAR_PREFIX_RE,
                   "item": _ITEM_LABEL_RE}


ALL_LABELS = ("rank", "arc", "char", "item")


EDGE_JUNK_TOKENS = {"l", "I", "i", "1", "|", "!"}  # одиночные символы-мусор по краям


def clean_name(text: str) -> str:
    """Чистое название: без даты, обозначений ранга, мусорных символов OCR,
    непечатаемых символов и двойных пробелов."""
    # ИЗМЕНЕНО: дополнительно убирается ранг в скобках «(S)», «[A]»
    text = RANK_PAREN_RE.sub(" ", STAR_TOKEN_RE.sub(" ", DATE_RE.sub(" ", text)))
    text = JUNK_RE.sub(" ", EMOJI_RE.sub(" ", text))
    text = "".join(ch if ch.isprintable() else " " for ch in text)
    text = re.sub(r"\s+", " ", text).strip()
    return re.sub(r"^[\W_]+|[\W_]+$", "", text)


# ИСПРАВЛЕНО: лишнее число между повторяющимися префиксами. OCR читает значок ранга или номер
# строки как цифру: «Дуга - 8 Дуга - Настоящая музыка». Одно-двузначное число в начале
# снимается, только если сразу за ним идёт служебный префикс (название с цифры не страдает).
_LEAD_NUM_RE = re.compile(r"^\d{1,2}(?!\d)[\s.):\-–—]*")


def _peel_labels(text: str, kinds=ALL_LABELS):
    """НОВОЕ: снимает с начала строки служебные префиксы (ранг, «Дуга -», «Персонаж:»),
    повторяющиеся префиксы, лишнее число между ними и хвост «×N».
    Возвращает (очищенный текст, список снятых префиксов: «rank» / «arc» / «char»).
    Префикс не снимается, если после него ничего не останется."""
    text = (text or "").strip()
    found = []
    for _ in range(6):  # несколько проходов: «Дуга - 8 Дуга - Имя» -> «Имя»
        before = text
        for kind in kinds:
            m = _LABEL_PATTERNS[kind].match(text)
            if m and text[m.end():].strip():
                text = text[m.end():].strip()
                found.append(kind)
        m = _LEAD_NUM_RE.match(text)
        if m:
            rest = text[m.end():].strip()
            if rest and any(_LABEL_PATTERNS[k].match(rest) for k in kinds):
                text = rest
        no_qty = _QTY_SUFFIX_RE.sub("", text).strip()
        if no_qty:
            text = no_qty
        if text == before:
            break
    return text, found


def strip_labels(text: str, kinds=ALL_LABELS) -> str:
    """Название без служебных префиксов и хвоста «×N» (см. _peel_labels)."""
    return _peel_labels(text, kinds)[0]


def leading_type(text: str):
    """Тип по ПРЕФИКСУ строки: «arc» («Дуга - …»), «character» («Персонаж: …»),
    «item» («Предмет - …») или None.

    OCR-ФИКС 2: строка сначала очищается от мусора в начале («: Дуга - …»), затем
    пропускаются ранг («S», «Ранг A») и лишнее число перед префиксом, и тип определяется
    по ПЕРВОМУ служебному префиксу. Префикс важнее слов внутри названия и всего, что
    осталось от OCR. «Предмет - …» — это предмет, а не персонаж. Префикс, после которого
    ничего не остаётся, не считается."""
    t = strip_leading_junk(clean_name(text))
    kinds = (("arc", "arc"), ("char", "character"), ("item", "item"))
    for _ in range(6):
        before = t
        for label, result in kinds:
            m = _LABEL_PATTERNS[label].match(t)
            if m and t[m.end():].strip():
                return result
        for rx in (_RANK_PREFIX_RE, _LEAD_NUM_RE):   # ранг / номер перед префиксом
            m = rx.match(t)
            if m and t[m.end():].strip():
                t = strip_leading_junk(t[m.end():])
        if t == before:
            break
    return None


# ---------------------------------------------------------------------------
# НОВОЕ: «Подарок за очки» — бонусная (дополнительная) добыча
# ---------------------------------------------------------------------------
# Строка вида «Подарки за очки: Дуга - Забытое» или «Подарок за очки дуга Забытое» — это
# бонусная добыча за каждые 10 круток, а не обычная крутка. Допуски на ошибки OCR:
# латинские «o»/«a» вместо кириллических, окончание слов, любые разделители после фразы.
# Также распознаётся подпись самой механики: «Дополнительная добыча», «Бонусная добыча»
# и хвост «(бонус 10 круток)». Фраза вырезается из текста — остаётся чистое название.
# ИСПРАВЛЕНО (СТРОГИЙ фильтр): бонусом считается ТОЛЬКО строка с фразой «Подарок за очки».
# Раньше сюда же попадали «Дополнительная добыча» / «(бонус 10 круток)» — из-за этого обычные
# предметы (кубики, планеры, костюмы) могли ошибочно стать бонусными.
# OCR-ФИКС 3: допуски расширены — «Подарок», «Подарки», «Подаро», «Пoдapок» (латиница/цифра 0
# вместо кириллицы), слитное «заочки», окончание слова «очки» любое.
BONUS_MARK_RE = re.compile(
    r"\bп[оo0]д[аa][рp]\w{0,4}\s*[зз3][аa]\s*[оo0]ч\w*[\s:.\-–—]*", re.I)


# Подписи механики бонуса из интерфейса игры: из названия вырезаются, но бонусом строку НЕ делают.
BONUS_NOISE_RE = re.compile(
    r"\b(?:доп\w*\.?|бонусн\w*)\s*добыч\w*[\s:.\-–—]*|\(\s*бонус[^)]*\)?", re.I)


# ---------------------------------------------------------------------------
# OCR-ФИКС 3: словарь исправлений названий БОНУСНЫХ наград («Подарок за очки»).
# Ключ — эталонное слово названия, значение — (итоговое название, ключ типа LOOT_TYPES).
# OCR читает «Дуга» как «Муга», «Мута» и т. п., а название — с опечатками
# («Забытое» -> «Забытоe», «Забытов»). Словарь МОЖНО ДОПОЛНЯТЬ новыми бонусными дугами.
# ---------------------------------------------------------------------------
BONUS_ITEM_CORRECTIONS = {
    "Забытое": ("Дуга - Забытое", "arc"),
}


BONUS_WORD_CUTOFF = 0.72       # минимальное сходство слова названия с эталоном


BONUS_ARC_WORD_CUTOFF = 0.70   # минимальное сходство «Муга» / «Дуг» со словом «Дуга»


BONUS_TYPE_PREFIX = "Бонус (10 круток)"     # префикс колонки «Тип» у бонусной добычи


def _arc_word_like(token: str) -> bool:
    """OCR-ФИКС 3: слово похоже на «Дуга» («Муга», «Дуг», «Дyгa»): 3–5 букв и сходство
    со словом «Дуга» не ниже BONUS_ARC_WORD_CUTOFF. Имена персонажей из состава — нет."""
    if not 3 <= len(token) <= 5 or fold_name(token) in ROSTER_FOLDED:
        return False
    return difflib.SequenceMatcher(None, fold_name(token), fold_name("дуга")).ratio() \
        >= BONUS_ARC_WORD_CUTOFF


def fix_bonus_item_text(text: str) -> str:
    """OCR-ФИКС 3: исправляет искажённое название бонусной награды (текст УЖЕ без фразы
    «Подарок за очки»). Слово из BONUS_ITEM_CORRECTIONS (с опечатками OCR) вместе со всеми
    стоящими перед ним словами, похожими на «Дуга» («Муга Забытое»), заменяется итоговым
    названием («Дуга - Забытое»). Если известного названия нет, а первое слово похоже на
    «Дуга», оно заменяется на «Дуга» («Муга Клинок» -> «Дуга Клинок»), чтобы бонус никогда
    не стал персонажем. Остальной текст (ранг, ×N, дата) не меняется."""
    tokens = list(re.finditer(r"[^\W\d_]+", text or ""))
    for word, (canon, _key) in BONUS_ITEM_CORRECTIONS.items():
        target = fold_name(word)
        for i, tok in enumerate(tokens):
            folded = fold_name(tok.group())
            if len(folded) < 5 or abs(len(folded) - len(target)) > 2:
                continue
            if folded != target and difflib.SequenceMatcher(
                    None, folded, target).ratio() < BONUS_WORD_CUTOFF:
                continue
            start, j = tok.start(), i - 1
            while j >= 0 and _arc_word_like(tokens[j].group()):   # «Дуга - Муга Забытое»
                start, j = tokens[j].start(), j - 1
            return f"{text[:start]}{canon}{text[tok.end():]}"
    if len(tokens) > 1 and _arc_word_like(tokens[0].group()):
        return f"{text[:tokens[0].start()]}Дуга{text[tokens[0].end():]}"
    return text


# Значки и эмодзи (🎲 и т. п.), которые OCR/копирование может оставить в строке
EMOJI_RE = re.compile("[\U0001F000-\U0001FAFF\u2600-\u27BF\u2B00-\u2BFF\uFE0F]+")


def _trim_edge_junk(text: str) -> str:
    """НОВОЕ: убирает одиночные символы-мусор OCR («l», «|», «1»…) по краям названия."""
    words = text.split()
    while len(words) > 1 and words[0] in EDGE_JUNK_TOKENS:
        words.pop(0)
    while len(words) > 1 and words[-1] in EDGE_JUNK_TOKENS:
        words.pop()
    return " ".join(words)


# ---------------------------------------------------------------------------
# OCR-ФИКС 5: СТРОГИЕ правила для «Занку» и «Ирой» (одни и те же на всех трёх вкладках со
# скриншотами: «Скриншот», «Скриншот оптом», «Скриншоты разом» — все они разбирают текст через
# ocr_extract_pulls_ex -> prepare_ocr_row / master_match / parse_ocr_result)
# ---------------------------------------------------------------------------
# OCR-ФИКС 7: ТОЛЬКО строки с точным текстом «Страна сна» или «Подарок за очки» вне гаранта
# (сохраняются в историю, но не прибавляют крутку и не двигают гарант). Остальное — как обычно.
NON_PITY_RE = re.compile(r"страна\s*сна|подарок\s*за\s*очки", re.I)


STRANA_SNA_RE = re.compile(r"страна\s*сна", re.I)


# 1) Строка с ключевым словом предмета / ресурса («кубик», «фрагмент», «passer» …) — ВСЕГДА
#    предмет или ресурс и НИКОГДА не персонаж (мусор вроде «:: passer THepaEAn кубик» раньше
#    нечётким поиском превращался в «Занку»). Ключевые слова МОЖНО ДОПОЛНЯТЬ.
RESOURCE_KEYWORD_RE = re.compile(
    r"к[уyu][б6b][иuinн]?[кk]|\bcubes?\b|ф[рp][аa][гrвv]м|фрагм|fragm|passer|"
    r"т[вb]ерд(?:ый|ыи|ы|ое)?(?!\w)|шулер\w*|потер\w*\s*фр|lost\s*fr|искривл|"
    r"reamnear|tespep|fipas\w*|gpami\w*|зетавя\w*", re.I)


_RESOURCE_SQUASHED_RE = re.compile(
    r"кубик|фрагмент|fragment|passer|reamnear|fipasere|gpamicer|искривлен", re.I)


_CUBE_WORD_RE = re.compile(
    r"к[уyu][б6b][иuinн]?[кk]|\bcubes?\b|passer|reamnear|tespep|т[вb]ерд(?:ый|ыи|ы|ое)?(?!\w)",
    re.I)


# OCR-ФИКС 6: признаки «Фрагмента искривления» (в т. ч. искажения «fipasere Gpamicer»)
_WARP_WORD_RE = re.compile(r"искр|warp|fipas|gpami|зетавя", re.I)


def is_resource_text(text: str) -> bool:
    """OCR-ФИКС 5: в строке есть ключевое слово предмета / ресурса (кубик, фрагмент, passer …).
    Такая строка никогда не сопоставляется с персонажем. «Подарок за очки» сюда не входит:
    бонус может выдать и настоящего персонажа — для него запрещены только нечёткие догадки
    (см. master_match)."""
    t = text or ""
    return bool(RESOURCE_KEYWORD_RE.search(t)
                or _RESOURCE_SQUASHED_RE.search(re.sub(r"\s+", "", t)))


def hard_item_kind(text: str):
    """OCR-ФИКС 6: ЖЁСТКОЕ правило предметов. Строка с ключевым словом («кубик», «твердый»,
    «фрагмент», «искривления», «passer», «reamnear», «fipasere» …) — ВСЕГДА предмет и никогда не
    персонаж. Возвращает вид («solid_cube», «trick_cube», «warp_fragment», «lost_fragment») или
    None. Явная «Дуга - …» исключена. «Подарок за очки» сам по себе ключевым словом не
    является (бонус бывает и дугой/персонажем): для него запрещён только нечёткий подбор."""
    if not is_resource_text(text):
        return None
    if leading_type(strip_leading_junk(text)) == "arc":
        return None
    low = (text or "").lower().replace("ё", "е")
    if _CUBE_WORD_RE.search(low):
        return "trick_cube" if re.search(r"шулер|trick", low) else "solid_cube"
    return "warp_fragment" if _WARP_WORD_RE.search(low) else "lost_fragment"


# 2) «Ирой» с приставшей подписью интерфейса: «персонажиИрой», «персонажИрой»,
#    «8 персонажеиИрой», «персонаженИрой», «Nepconark Hpou» …. Слово «Персонаж» (с любыми
#    искажениями и до 4 лишних букв после него) + имя «Ирой» (с «двойниками» букв).
_IROY_LABEL = r"[пnmм][еeё][рp][сc][оo0][нnh][аa][жxk]"


IROY_UI_RE = re.compile(
    rf"{_IROY_LABEL}[^\W\d_]{{0,4}}?[\s:.\-–—|]*"
    r"[иuiнhnm1l][рpп][оo0][йиiuлn]{1,2}(?![^\W\d_])", re.I | re.U)


IROY_NAME = "Ирой"


IROY_PLAIN_RE = re.compile(r"ирой(?![^\W\d_])", re.I)


_IROY_PREFIX_RE = re.compile(r"персонаж\w*|nepconar\w*|mepconax\w*", re.I)


def strip_iroy_ui_prefix(text: str):
    """OCR-ФИКС 6: (новый текст, найдено ли). Если в строке есть «ирой», ВСЕ приставшие подписи
    интерфейса слева («персонажи», «персонаж», «персонажен», «персонажеи», ведущие цифры,
    знаки) срезаются, остаток — строго «Персонаж: Ирой» + хвост (количество, дата). Если слева
    остались настоящие слова (не подпись), строка не меняется. Работает ДО нечёткого поиска."""
    t = text or ""
    m = IROY_PLAIN_RE.search(t)
    if not m:
        return t, False
    left = t[:m.start()]
    if re.search(r"[^\W\d_]{2,}", _IROY_PREFIX_RE.sub(" ", left)):
        return t, False
    keep = "".join(re.findall(r"[★☆]", left))
    head = f"{keep} " if keep else ""
    return re.sub(r"\s+", " ", f"{head}{CHARACTER_LABEL_WORD}: {IROY_NAME}{t[m.end():]}").strip(), True


def normalize_iroy_text(text: str):
    """OCR-ФИКС 5: (новый текст, найдено ли). Если в тексте есть «Ирой» вместе со словом
    интерфейса «Персонаж» (в любом искажении), мусор слева и приставшая подпись срезаются, а
    остаток становится строго «Персонаж: Ирой» (хвост — количество, дата — не трогается).
    Звёзды ранга слева сохраняются."""
    t = text or ""
    m = IROY_UI_RE.search(t)
    if not m:
        return strip_iroy_ui_prefix(t)         # OCR-ФИКС 6: «8 персонажеиирой» и т. п.
    left = t[:m.start()]
    keep = "".join(re.findall(r"[★☆]", left))
    if re.search(r"[^\W\d_]{2,}", left):              # слева настоящие слова — оставляем их
        keep = left.rstrip()
    head = f"{keep} " if keep else ""
    fixed = f"{head}{CHARACTER_LABEL_WORD}: {IROY_NAME}{t[m.end():]}"
    return re.sub(r"\s+", " ", fixed).strip(), True


# OCR-ФИКС 7: «Занку». Tesseract превращает жёлтый/оранжевый текст «Персонаж - Занку» в мусор вроде
# «Мереспепх - Sexxy». Любая из частей (мереспепх / sexxy / занку и их «двойники» букв), даже
# несколько подряд, превращается в «Персонаж: Занку». Строки с ключевыми словами предметов
# («кубик», «фрагмент» …) не затрагиваются — предметы никогда не становятся персонажем.
ZANKU_NAME = "Занку"


_ZANKU_PART = (r"[mм][еe][рp][еe][сc][пn][еe][пn][xх]|[sS][еe][xх]{1,3}[yу]|"
               r"[зzs3][аa][нh][кk][уy]")


ZANKU_UI_RE = re.compile(
    rf"(?:{_ZANKU_PART})(?:[\s:.\-–—|]*(?:{_ZANKU_PART}))*(?![^\W\d_])", re.I | re.U)


def normalize_zanku_text(text: str):
    """OCR-ФИКС 7: (новый текст, найдено ли). Слева допускаются только подпись «Персонаж»
    (любой вариант), цифры и знаки; результат — «Персонаж: Занку» + хвост (количество, дата).
    В бонусной строке («Подарок за очки») срабатывает только точное имя «Занку»."""
    t = text or ""
    m = ZANKU_UI_RE.search(t)
    if not m or is_resource_text(t):
        return t, False
    if BONUS_MARK_RE.search(t) and not re.fullmatch(r"(?i)занку", m.group().strip()):
        return t, False
    left = t[:m.start()]
    if re.search(r"[^\W\d_]{2,}", _IROY_PREFIX_RE.sub(" ", left)):
        return t, False
    keep = "".join(re.findall(r"[★☆]", left))
    head = f"{keep} " if keep else ""
    return re.sub(r"\s+", " ", f"{head}{CHARACTER_LABEL_WORD}: {ZANKU_NAME}{t[m.end():]}").strip(), True


def clean_character_name(text: str) -> str:
    """НОВОЕ: оставляет ТОЛЬКО чистое имя персонажа: без даты, ранга («S», «Ранг A»,
    «(S)», «5★»), слова «Персонаж», мусора OCR и лишних пробелов.
    OCR-ФИКС 5: «персонажиИрой» / «персонажИрой» -> «Ирой» (подпись интерфейса срезается)."""
    if normalize_iroy_text(text)[1]:
        return IROY_NAME
    if normalize_zanku_text(text)[1]:
        return ZANKU_NAME
    name = strip_labels(clean_name(text), ("rank", "char", "item"))
    name = clean_name(_trim_edge_junk(name))
    return "" if re.fullmatch(r"[x×х]?\s*\d+", name, re.I) else name  # одно число — не имя


def format_duga_name(text: str) -> str:
    """НОВОЕ: приводит название дуги к виду «Дуга - Название». Всё лишнее (дата, ранг,
    слова «Дуга»/«Weapon», мусор OCR) убирается; повторный вызов результат не меняет.
    Если названия нет — возвращает пустую строку (в форме подставится «Дуга»)."""
    name = strip_labels(clean_name(text), ("rank", "arc", "char", "item"))
    name = clean_name(_trim_edge_junk(name))
    snap = snap_known_phrase(name)           # НОВОЕ: «Обнажённый клинок» + мусор -> эталон
    if snap and snap[1] == "arc":
        name = snap[0]
    if (name.lower() in ("дуга", "дуги", "arc", "arcs", "weapon")  # одно слово-тип без названия
            or re.fullmatch(r"[x×х]?\s*\d+", name, re.I)):          # остался только «×1» / число
        name = ""
    return f"{DUGA_PREFIX}{name}" if name else ""


# НОВОЕ: слово-тип в начале названия предмета («Планер Ветер», «Костюм - Алый») — это тип,
# а не часть названия: он показывается в колонке «Тип», поэтому из названия убирается.
_ITEM_PREFIX_RE = re.compile(
    r"^(?i:детали\s+модификации\W*окраска|окраска|планер|костюм|скин(?:\s+на\s+авто)?|"
    r"glider|outfit|skin)(?!\w)[\s:.\-–—]*")


def strip_item_prefix(key, name: str) -> str:
    """Название предмета (костюм, планер, окраска, скин) без слова-типа в начале.
    Если после снятия ничего не остаётся — возвращается пустая строка (подставится
    название типа по умолчанию)."""
    if key not in ("outfit", "glider", "paint", "car_skin"):
        return name
    return clean_name(_ITEM_PREFIX_RE.sub("", name or "", count=1))


def format_glider_name(text: str) -> str:
    """НОВОЕ: приводит название планера к виду «Планер - Название». Слово «Планер», ранг и
    мусор OCR убираются, опечатки исправляются по справочнику GLIDER_NAMES; повторный вызов
    результат не меняет. Названия нет — пустая строка (подставится «Планер»)."""
    name = strip_item_prefix("glider", strip_labels(clean_name(text), ("rank", "item")))
    name = clean_name(_trim_edge_junk(name))
    snap = snap_known_phrase(name, keys=("glider",))
    if snap:
        name = snap[0]
    if name.lower() in ("планер", "glider") or re.fullmatch(r"[x×х]?\s*\d+", name, re.I):
        name = ""
    return f"{GLIDER_PREFIX}{name}" if name else ""


# ИСПРАВЛЕНО (костюмы): слово «Костюм» в НАЧАЛЕ строки (в т.ч. с ошибками OCR: «Kocmom…»)
_OUTFIT_LEAD_RE = re.compile(r"^(?:[кk][оo0][сc][тtm][a-zа-яё0-9|]{0,3}[мm]|outfit)(?![a-zа-яё])", re.I)


def format_outfit_name(text: str) -> str:
    """ИСПРАВЛЕНО (костюмы): приводит название костюма к виду «Костюм - Название». Слово
    «Костюм», ранг и мусор OCR убираются, опечатки исправляются по справочнику OUTFIT_NAMES;
    повторный вызов результат не меняет. Названия нет — пустая строка (подставится «Костюм»)."""
    forced = forced_name_rule(strip_leading_junk(text or ""))   # жёсткое правило искажений OCR
    if forced and forced["category"] == "outfit":
        return forced["label"]
    name = strip_item_prefix("outfit", strip_labels(clean_name(text), ("rank", "item")))
    name = clean_name(_trim_edge_junk(name))
    form = _phrase_form(name) if name else ""
    for known in OUTFIT_NAMES:                      # опечатки по справочнику костюмов
        target = _phrase_form(known)
        if form and (form == target or (abs(len(form) - len(target)) <= 3 and difflib.SequenceMatcher(
                None, form, target).ratio() >= PHRASE_MATCH_CUTOFF)):
            name = known
            break
    if name.lower() in ("костюм", "outfit") or re.fullmatch(r"[x×х]?\s*\d+", name, re.I):
        name = ""
    return f"{OUTFIT_PREFIX}{name}" if name else ""


def finalize_loot_name(key, raw_name: str) -> str:
    """НОВОЕ: итоговое название для формы «Ручная» при переносе из скриншота:
    персонаж — чистое имя; дуга — «Дуга - Название»; у кубиков и фрагментов названия
    нет; у остальных предметов — очищенный текст без ранга."""
    info = LOOT_TYPES.get(key)
    if info is None:
        return clean_name(raw_name)
    if info.get("hide_name"):
        return ""
    if key == "arc":
        return format_duga_name(raw_name)
    if key == "character":
        return clean_character_name(raw_name)
    if key == "glider":
        return format_glider_name(raw_name)           # «Планер - Название»
    if key == "outfit":
        return format_outfit_name(raw_name)           # «Костюм - Название»
    return strip_item_prefix(key, strip_labels(clean_name(raw_name), ("rank", "item")))


def _find_timestamp(text: str):
    """Первая дата в тексте в формате DATE_FMT или None."""
    m = find_valid_date_match(text)
    if m:
        try:
            return _normalize_date(m.group())
        except ValueError:
            pass
    return None


def _only(values):
    """Единственное различное значение из списка (иначе None)."""
    uniq = set(v for v in values if v is not None)
    return next(iter(uniq)) if len(uniq) == 1 else None


# ----------------------------------------------------------------------------
# НОВОЕ: сопоставление распознанного текста с составом персонажей (ROSTER_*)
# ----------------------------------------------------------------------------
# Перед сравнением обе стороны «сворачиваются» в одну форму: кириллические буквы,
# похожие на латинские, заменяются латиницей (поэтому «ЕХЕ» = «EXE», «Xaoc» = «Хаос»),
# а типичные путаницы OCR сводятся к одной букве: ё/э -> е, й -> и, ъ -> ь, щ -> ш, 0 -> о.
OCR_FOLD = str.maketrans({
    "а": "a", "в": "b", "е": "e", "к": "k", "м": "m", "н": "h", "о": "o", "р": "p",
    "с": "c", "т": "t", "у": "y", "х": "x",
    "ё": "e", "э": "e", "й": "и", "ъ": "ь", "щ": "ш", "0": "o",
})


ROSTER_MATCH_CUTOFF = 0.75   # минимальное сходство (difflib) для «прилипания» к имени


ROSTER_AMBIGUITY_GAP = 0.10  # если два имени почти одинаково похожи — не угадываем


ROSTER_MIN_FUZZY_LEN = 4     # короче 4 букв — только точное совпадение (после сворачивания)


def fold_name(text) -> str:
    """Форма имени для нечёткого сравнения (регистр, ё/е, похожие буквы)."""
    return str(text or "").lower().translate(OCR_FOLD)


# {свёрнутое имя: (имя, ранг 5/4)} — строится из ROSTER_KNOWN один раз при запуске
ROSTER_FOLDED = {fold_name(v[0]): (v[0], v[1]) for v in ROSTER_KNOWN.values()}


# ----------------------------------------------------------------------------
# НОВОЕ: эталонные названия дуг и предметов (нечёткий поиск в строке OCR)
# ----------------------------------------------------------------------------
# {название: ключ типа}. Ключ: «arc» — дуга; «solid» / «trick» — кубик (количество 1/5
# определяется отдельно, см. _cube_qty); «lost_fragment» / «warp_fragment» — фрагменты.
# Список МОЖНО ДОПОЛНЯТЬ: добавьте строку «"Название дуги": "arc"» — и OCR будет исправлять
# опечатки именно в этом названии и всегда считать его дугой.
KNOWN_PHRASES = {
    "Обнаженный клинок": "arc",
    # OCR-ФИКС 3: «Дуга - Забытое» (часто выпадает как «Подарок за очки»; OCR читает
    # «Дуга» как «Муга»). Эталон исправляет опечатки и всегда делает строку ДУГОЙ.
    "Забытое": "arc",
    # «дуга Чиетое небо» -> «Дуга - Чистое небо» (опечатки исправляет snap_known_phrase)
    "Чистое небо": "arc",
    "Твердый кубик": "solid",
    "Шулерский кубик": "trick",
    "Потерянный фрагмент": "lost_fragment",
    "Фрагмент искривления": "warp_fragment",
}


# НОВОЕ: мастер-справочники (дуги A ранга и планеры) — те же нечёткие эталоны, что и выше.
# setdefault: уже заданные вручную эталоны («Забытое», «Чистое небо», «Обнаженный клинок»)
# остаются как есть.
for _n in ARC_S_NAMES + ARC_A_NAMES + ARC_B_NAMES:
    KNOWN_PHRASES.setdefault(_n, "arc")


for _n in GLIDER_NAMES:
    KNOWN_PHRASES.setdefault(_n, "glider")


PHRASE_MATCH_CUTOFF = 0.78   # минимальное сходство (difflib) для «прилипания» к эталону


PHRASE_AMBIGUITY_GAP = 0.08  # два эталона почти одинаково похожи — не угадываем


def _phrase_form(text: str) -> str:
    """Форма для сравнения: свёрнутые буквы (fold_name) без пробелов — OCR часто теряет или
    добавляет пробелы («Твердыйкубик», «Потеряный фраг мент»)."""
    return re.sub(r"[\W_]+", "", fold_name(text))


_PHRASE_FOLDED = {_phrase_form(p): (p, key, len(p.split())) for p, key in KNOWN_PHRASES.items()}


# OCR-ФИКС: ключи KNOWN_PHRASES, которые являются ПРЕДМЕТАМИ (не дугами), и более мягкие
# пороги для строк с префиксом «Предмет» (PHRASE_ITEM_CUTOFF) и для «страховки» строк, у
# которых есть дата и количество, но название не распозналось (PHRASE_RECOVER_CUTOFF).
ITEM_PHRASE_KEYS = ("solid", "trick", "lost_fragment", "warp_fragment", "glider")


PHRASE_ITEM_CUTOFF = 0.62


PHRASE_RECOVER_CUTOFF = 0.55


def snap_known_phrase(text: str, cutoff: float = PHRASE_MATCH_CUTOFF, keys=None):
    """Ищет в строке эталонное название из KNOWN_PHRASES, исправляя опечатки OCR.
    Возвращает (эталонное название, ключ типа, сходство) или None.

    Сравниваются «окна» из соседних слов (длиной от n-1 до n+1 слов, где n — число слов в
    эталоне), поэтому лишние слова и мусор вокруг названия («l Твердый кубнк ×1 ¦»)
    отбрасываются, а название берётся чистым. Неоднозначные совпадения не засчитываются.
    keys — необязательный список ключей эталонов, среди которых искать (например,
    ITEM_PHRASE_KEYS — только предметы, без дуг)."""
    tokens = re.findall(r"[^\W_]+", text or "")
    if not tokens:
        return None
    best = {}   # эталон -> (сходство, ключ)
    for folded, (phrase, key, n) in _PHRASE_FOLDED.items():
        if keys is not None and key not in keys:
            continue
        for size in range(max(1, n - 1), n + 2):
            for i in range(0, len(tokens) - size + 1):
                window = _phrase_form(" ".join(tokens[i:i + size]))
                if abs(len(window) - len(folded)) > max(3, len(folded) // 4):
                    continue
                if len(folded) < MASTER_MIN_FUZZY_LEN and (
                        window != folded or folded != _phrase_form(split_garbled_type(text)[1])):
                    continue     # ИСПРАВЛЕНО: короткий эталон («Мы.») — только если это ВСЁ название
                score = 1.0 if window == folded else difflib.SequenceMatcher(
                    None, window, folded).ratio()
                if score >= cutoff and score > best.get(phrase, (0.0, None))[0]:
                    best[phrase] = (score, key)
    if not best:
        return None
    ranked = sorted(best.items(), key=lambda kv: -kv[1][0])
    if len(ranked) > 1 and ranked[0][1][0] - ranked[1][1][0] < PHRASE_AMBIGUITY_GAP:
        return None
    phrase, (score, key) = ranked[0]
    return phrase, key, score


def _roster_variants(text: str) -> list:
    """Что сравнивать с составом: каждое слово строки и склейки соседних слов
    («Блэк бёрд» -> «Блэкбёрд»). Числа, слова-типы и обрывки короче 3 букв пропускаются."""
    tokens = [t for t in re.findall(r"[^\W_]+", text or "")
              if not t.isdigit() and t.lower() not in KEYWORD_SET]
    variants = tokens + [a + b for a, b in zip(tokens, tokens[1:])]
    return [v for v in dict.fromkeys(variants) if len(v) >= 3]


def match_roster_name(text: str, cutoff: float = ROSTER_MATCH_CUTOFF):
    """Ищет в строке имя из состава персонажей (ROSTER_*), исправляя опечатки OCR.
    Возвращает (точное имя, ранг 5/4, сходство) или None. Осторожность против ошибок:
      * сходство ниже cutoff — не засчитывается;
      * у слов короче ROSTER_MIN_FUZZY_LEN допустимо только точное совпадение;
      * если подходят два разных имени с разницей меньше ROSTER_AMBIGUITY_GAP —
        результат неоднозначен, имя не меняется (пользователь выберет сам)."""
    best = {}  # имя -> (лучшее сходство, ранг)
    for variant in _roster_variants(text):
        folded = fold_name(variant)
        for roster_folded, (name, rank) in ROSTER_FOLDED.items():
            if abs(len(folded) - len(roster_folded)) > 2:
                continue
            if folded == roster_folded:
                score = 1.0
            elif min(len(folded), len(roster_folded)) < ROSTER_MIN_FUZZY_LEN:
                continue
            else:
                score = difflib.SequenceMatcher(None, folded, roster_folded).ratio()
            if score >= cutoff and score > best.get(name, (0.0, 0))[0]:
                best[name] = (score, rank)
    if not best:
        return None
    ranked = sorted(best.items(), key=lambda kv: -kv[1][0])
    if len(ranked) > 1 and ranked[0][1][0] - ranked[1][1][0] < ROSTER_AMBIGUITY_GAP:
        return None
    name, (score, rank) = ranked[0]
    return name, rank, score


def parse_ocr_result(raw_text: str, known: dict = None, context: str = None,
                     color_rank: int = None, guess_wish: bool = True,
                     bonus: bool = False, default_loot: str = "character",
                     dice_icon: bool = False) -> dict:
    """Разбирает одну распознанную строку на название, ранг/тип и время.

    known      — {имя в нижнем регистре: (имя, ранг, баннер)} для исправления опечаток
                 OCR и определения типа (персонаж / дуга) по истории;
    context    — полный текст скриншота: из него берётся значение, которого нет в самой
                 строке, но только если оно на скриншоте единственное;
    color_rank — ранг (5/4/3), определённый по цвету рамки/фона (classify_rarity_color);
    guess_wish — определять ли тип «Персонаж» / «Дуга» для строк без типа предмета;
    bonus      — строка уже помечена как бонусная;
    default_loot — тип для строк без префикса и без известного имени: «character» или
                 «arc» (на баннере «Дуга» безымянные строки — это дуги);
    dice_icon  — в строке был значок кубика 🎲 (убран prepare_ocr_row); учитывается только
                 как запасной признак, когда в строке нет никакого названия.

    ИСПРАВЛЕНО (тип и название): тип определяется по ПРЕФИКСУ строки («Дуга - …»,
    «Персонаж: …») раньше, чем по словам внутри названия; повторяющиеся префиксы и лишние
    цифры между ними убираются («Дуга - 8 Дуга - Настоящая музыка» -> «Дуга - Настоящая
    музыка»). НОВОЕ (бонус): фраза «Подарок за очки» (и «Дополнительная добыча») помечает
    запись как бонусную — is_bonus=True, ранг A; сама фраза из названия вырезается.

    Ранг выбирается по приоритету (OCR-ФИКС): бонус («Подарок за очки» — всегда A) -> ЦВЕТ
    ТЕКСТА названия на скриншоте (жёлтый S / фиолетовый A / серый, белый, тёмный B) ->
    ранг, написанный в тексте строки -> фиксированный у вида предмета -> известное имя из
    истории -> состав персонажей -> единственный ранг на скриншоте -> B по умолчанию.
    Цвет строго определяет колонку «Ранг» и цвет строки (кроме кешбэка: у него ранг жёсткий).
    Возвращает {"name", "rarity_type", "rarity", "rarity_src", "loot", "qty",
                "timestamp", "has_time"}:
      name        — ОЧИЩЕННОЕ название (персонаж — чистое имя, дуга — «Дуга - Название»);
      rarity_type — буква «S/A/B» или название типа («Костюм», «Кешбэк (Обычный)»…);
      rarity      — число 5/4/3 (S/A/B);
      rarity_src  — чем определён ранг («текст», «цвет», «история»…);
      loot        — ключ LOOT_TYPES («character», «arc», «outfit»…) или None;
      qty         — «30»/«50» для потерянного фрагмента, иначе None;
      timestamp   — QDateTime найденного времени (если не найдено — текущее системное);
      has_time    — найдено ли время в тексте (False — форму лучше не трогать);
      is_bonus    — бонусная добыча («Подарок за очки»): не расходует гарант;
      type_text   — текст колонки «Тип»: «Дуга», «Персонаж», «Планер», «Бонус (10 круток) - Дуга»…
    """
    known = known or {}
    raw_text = normalize_iroy_text(raw_text)[0]       # OCR-ФИКС 5: чистое «Персонаж: Ирой»
    raw_text = normalize_zanku_text(raw_text)[0]      # OCR-ФИКС 7: чистое «Персонаж: Занку»
    # НОВОЕ: бонусная добыча — признак снимается ДО разбора, чтобы фраза не попала в название
    is_bonus = bonus or bool(BONUS_MARK_RE.search(raw_text))
    if is_bonus:
        raw_text = BONUS_MARK_RE.sub(" ", raw_text)
        # OCR-ФИКС 3: «Муга Забытое» -> «Дуга - Забытое» (словарь BONUS_ITEM_CORRECTIONS)
        raw_text = re.sub(r"\s+", " ", fix_bonus_item_text(raw_text)).strip()
    # подписи вроде «Дополнительная добыча» / «(бонус 10 круток)» убираем, но бонусом не считаем
    raw_text = re.sub(r"\s+", " ", BONUS_NOISE_RE.sub(" ", raw_text)).strip()
    name = clean_name(raw_text)
    # НОВОЕ: эталонное название («Обнаженный клинок», «Твердый кубик»…) вытесняет искажённый
    # текст: мусор OCR вокруг и опечатки исчезают, остаётся чистое название
    snap = snap_known_phrase(strip_labels(name))
    if snap:
        name = snap[0]
    low = name.lower()
    # ИЗМЕНЕНО: сравнение с историей идёт без префиксов («Дуга - », ранг), чтобы
    # «S Хаотика» и «Дуга Клинок» находили «Хаотика» и «Дуга - Клинок»
    base = strip_labels(name).lower()
    index = {strip_labels(k, ("arc",)).lower(): k for k in known}
    hit = difflib.get_close_matches(base, list(index), n=1, cutoff=0.75) if base else []
    hit_key = index[hit[0]] if hit else None
    # ИСПРАВЛЕНО: серая строка (ранг B по цвету текста) не может быть персонажем A/S — они
    # всегда фиолетовые / золотые. Иначе короткая дуга («Мы.») «прилипала» к похожему
    # персонажу из истории (например, «Минт»).
    if (hit_key and color_rank == 3 and known[hit_key][1] in (4, 5)
            and leading_type(raw_text) != "character"):
        hit_key = None
    if hit_key:
        name = known[hit_key][0]
    elif low in KEYWORD_SET:  # в строке только слово-тип, не название
        name = ""

    loot = _loot_from_text(raw_text, dice=dice_icon)
    # ИСПРАВЛЕНО: префикс «Дуга - …» / «Персонаж: …» определяет тип сам и имеет приоритет
    lead = leading_type(raw_text)
    # OCR-ФИКС 5: ключевое слово предмета / ресурса («кубик», «фрагмент», «passer» …) — строка
    # НИКОГДА не персонаж, даже если OCR-мусор похож на имя (например, на «Занку»)
    res_hard = is_resource_text(raw_text) and lead != "arc"
    if lead in ("arc", "character") and not (res_hard and lead == "character"):
        loot = lead
    # ИСПРАВЛЕНО (костюмы): строка, начинающаяся со слова «Костюм» (в т.ч. «Kocmom…»), — ВСЕГДА
    # костюм (тип «Костюм», ранг S), а не персонаж, дуга или планер; то же — эталонное название
    # костюма из справочника OUTFIT_NAMES, даже если префикса в строке нет
    if lead not in ("arc", "character") and (
            _OUTFIT_LEAD_RE.match(strip_leading_junk(clean_name(raw_text)))
            or f"{OUTFIT_PREFIX}{strip_labels(name, ('rank', 'item'))}".lower() in OUTFIT_KNOWN):
        loot = "outfit"
    # НОВОЕ: «Предмет - …» — это предмет. Если вид предмета не распознан, строка НЕ должна
    # становиться персонажем: ниже она пропускается (loot=None)
    item_line = lead == "item" and loot not in ("arc", "character")
    if res_hard and loot in (None, "character"):
        low_r = raw_text.lower().replace("ё", "е")
        if _CUBE_WORD_RE.search(low_r):
            loot = ("trick" if re.search(r"шулер|trick", low_r) else "solid") + _cube_qty(low_r)
        elif (FRAGMENT_KEYWORD_RE.search(raw_text) or _fragment_like_word(raw_text)
              or fragment_stem_hint(raw_text) or _WARP_WORD_RE.search(low_r)):
            loot = "warp_fragment" if _WARP_WORD_RE.search(low_r) else "lost_fragment"
        else:
            loot, item_line = None, True              # предмет с неизвестным видом — не персонаж
    # OCR-ФИКС 3: строгий резерв «Потерянный фрагмент»: испорченная OCR строка с ключевым
    # словом фрагмента или количеством 30 / 50 — это материал, а не персонаж и не дуга
    if loot is None and lead is None and not is_bonus:
        loot = strict_fragment_key(raw_text, _qty_from_raw(raw_text), known)
    stamp = _find_timestamp(raw_text)
    ctx_rank = None
    if context is not None:
        lines = context.splitlines()
        loot = loot or _only(_loot_from_text(l) for l in lines)
        ctx_rank = _only(_rarity_from_text(l) for l in lines)
        # ИЗМЕНЕНО: finditer вместо findall — у DATE_RE теперь именованные группы
        stamp = stamp or _only(_find_timestamp(m.group()) for m in DATE_RE.finditer(context))
    if loot in ("cb_regular", "cb_premium") and re.fullmatch(
            r"(?:(?:кешб\w*|кэшб\w*|cashback|обычн\w*|премиум\w*|премиал\w*|regular|premium)\s*)+",
            name.lower()):
        name = ""  # в строке только описание кешбэка, а не название
    info = LOOT_TYPES.get(loot)
    if info and info.get("hide_name"):  # у кубиков и фрагментов названия нет
        name = ""

    # НОВОЕ: привязка к составу персонажей. Только для строк-персонажей: дуги (слово
    # «дуга»/«weapon») и предметы («Костюм …») пропускаются. Состав важнее истории:
    # опечатка, когда-то сохранённая в истории, не должна «прилипать» повторно.
    roster_hit = None
    if (loot in (None, "character") and not item_line and not snap
            and not ARC_WORD_RE.search(raw_text)):
        roster_hit = match_roster_name(strip_labels(clean_name(raw_text)))
        if roster_hit and color_rank == 3 and lead != "character" and roster_hit[2] < 1.0:
            roster_hit = None     # серая строка не бывает персонажем A/S: нечёткое совпадение не считаем
        if roster_hit:
            name, hit_key = roster_hit[0], None

    # НОВОЕ: строка без типа предмета — это персонаж или дуга. Дугой считаем строку
    # со словом «дуга»/«weapon» либо название, которое в истории лежит на баннере «Дуга».
    if loot is None and guess_wish and name and not item_line:
        is_arc = bool(ARC_WORD_RE.search(raw_text)) or (
            hit_key is not None and known[hit_key][2:3] == (ARC_BANNER,)) or (
            color_rank == 3 and not roster_hit and hit_key is None)   # серый текст — дуга, не персонаж
        if is_arc:
            loot = "arc"
        elif roster_hit or hit_key is not None:   # имя персонажа из состава / истории
            loot = "character"
        elif is_bonus:                            # OCR-ФИКС 3: бонус «Подарок за очки» — дуга,
            loot = "arc"                          # но никогда не персонаж
        else:                                     # иначе — по баннеру, выбранному в списке
            loot = default_loot if default_loot in ("arc", "character") else "character"
        info = LOOT_TYPES[loot]
    # НОВОЕ: очистка названия под определённый тип
    if loot == "arc":
        name = format_duga_name(name)
    elif loot == "character":
        name = clean_character_name(name)
    elif loot == "glider":
        name = format_glider_name(name)          # «Планер - Предвестник»
    elif loot == "outfit":
        name = format_outfit_name(name)          # «Костюм - Бесценная орхидея»
    elif loot and name:
        name = strip_item_prefix(loot, strip_labels(name, ("rank", "item")))
    if item_line and loot is None:
        name = ""                                # неизвестный предмет: не крутка
    if loot in ("arc", "character") and not name:  # после очистки ничего не осталось
        loot, info = None, None

    qty = None
    if loot == "lost_fragment":  # количество потерянных фрагментов: строго 30 или 50
        qty = fragment_qty(_qty_from_raw(raw_text), raw_text)      # OCR-ФИКС 3
    elif loot == "warp_fragment":
        qty = warp_qty(_qty_from_raw(raw_text), raw_text)

    fixed = loot_rarity(info) if info and info["mode"] != "wish" else None
    # бонусная добыча по правилам программы — всегда ранг A (как в форме «Ручная»)
    bonus_rank = 4 if is_bonus and info and info["mode"] == "wish" else None
    # OCR-ФИКС: цвет текста на скриншоте — главный источник ранга (и у круток, и у предметов).
    # Исключения: бонусная добыча (всегда A по правилам игры) и кешбэк (жёсткий ранг).
    color_ok = color_rank in (3, 4, 5) and not (info and info["mode"] == "cashback")
    # НОВОЕ: дуга из справочника A ранга. Цвет может только повысить ранг: «серый» результат
    # цветового анализа (3) у известной дуги считается неопределённым и справочник важнее.
    dict_rank = ARC_KNOWN[name.lower()][1] if loot == "arc" and name.lower() in ARC_KNOWN else None
    if dict_rank and color_rank == 3:
        color_ok = False
    candidates = ((bonus_rank, "бонусная добыча"),
                  (color_rank if color_ok else None, "цвет"),
                  (_rarity_from_text(raw_text), "текст"),
                  (dict_rank, "справочник дуг"),
                  (fixed, "тип предмета"),
                  (known[hit_key][1] if hit_key else None, "история"),
                  (roster_hit[1] if roster_hit else None, "состав персонажей"),
                  (ctx_rank, "скриншот"), (3, "по умолчанию"))
    rarity, rarity_src = next((r, src) for r, src in candidates if r)
    # НОВОЕ: текст колонки «Тип» — по распознанному типу (у предметов — название вида)
    type_text = ""
    if info:
        type_text = (REWARD_KINDS[info["kind"]] if info["mode"] == "reward"
                     and info.get("kind") in REWARD_KINDS else info["label"])
        if is_bonus and info["mode"] != "cashback":
            type_text = f"{BONUS_TYPE_PREFIX} - {type_text}"       # «Бонус (10 круток) - Дуга»
    return {
        # бонус у предметов тоже запоминается (в базе они получают флаг «вне гаранта»)
        "is_bonus": bool(is_bonus and info and info["mode"] != "cashback"),
        "type_text": type_text,
        "name": name,
        # OCR-ФИКС 3: итоговое название записи: «Потерянный фрагмент (30 шт)», «Дуга - Забытое»
        "display_name": (default_reward_name(info["kind"], qty or info.get("detail", ""))
                         if info and info["mode"] == "reward" and not name else name),
        "rarity_type": info["label"] if info and info["mode"] != "wish" else rank_letter(rarity),
        "rarity": rarity,
        "rarity_src": rarity_src,
        "loot": loot,
        "item_label": info["label"] if info and info["mode"] == "reward" else "",  # OCR-ФИКС
        # OCR-ФИКС 2: общий тип записи: «Предмет» / «Дуга» / «Персонаж» (кешбэк — «Кешбэк»)
        "item_type": ("Предмет" if info and info["mode"] == "reward" else
                      "Кешбэк" if info and info["mode"] == "cashback" else
                      info["label"] if info else ""),
        "qty": qty,
        "timestamp": (QDateTime.fromString(stamp, QT_DATE_FMT) if stamp
                      else QDateTime.currentDateTime()),
        "has_time": bool(stamp),
    }


# ----------------------------------------------------------------------------
# НОВОЕ: очистка текста OCR от служебных строк интерфейса игры
# ----------------------------------------------------------------------------
# Фразы интерфейса, которые никогда не бывают названием предмета. Сравнение без учёта
# регистра, «ё/е» и знаков препинания. Список можно дополнять.
OCR_NOISE_PHRASES = (
    "Подробности доски", "История бросков", "Результат броска", "Количество",
    "Время получения", "Повторно воспроизвести анимацию первого входа?",
    "Название предмета",     # НОВОЕ: заголовок столбца таблицы истории
)


# Одиночные заголовки столбцов и кнопки: убираются, только если ВСЯ строка — это слово
# (строка «Ранг S» или «Время 2026-01-31 18:45» под это правило не попадает)
OCR_NOISE_WORDS = {"название", "предмет", "тип", "ранг", "редкость", "время", "дата",
                   "отмена", "закрыть", "назад", "подтвердить", "далее",
                   # заголовки столбцов таблицы дуг и слова колонки «Тип»
                   "дуги", "дуга", "чудо", "коробка", "чудокоробка"}


OCR_NOISE_FUZZY = 0.80      # порог сходства для строк с опечатками OCR


OCR_NOISE_MIN_FUZZY = 8     # нечётко сравниваются только фразы от 8 знаков


OCR_MAX_ROWS = 300          # предел числа строк, разбираемых с одного скриншота


def _norm_ui(text: str) -> str:
    """Форма для сравнения: нижний регистр, ё -> е, без знаков препинания и лишних пробелов."""
    return re.sub(r"[\W_]+", " ", (text or "").lower().replace("ё", "е")).strip()


def _noise_regex(phrase: str):
    """Регулярное выражение фразы: слова через любые разделители, «е» совпадает и с «ё»."""
    words = [re.escape(w).replace("е", "[её]") for w in _norm_ui(phrase).split()]
    return re.compile(r"[\W_]*".join(words), re.I | re.U)


_NOISE_FOLDED = tuple(_norm_ui(p) for p in OCR_NOISE_PHRASES)


_NOISE_REGEXES = tuple(_noise_regex(p) for p in OCR_NOISE_PHRASES)


# ---------------------------------------------------------------------------
# OCR-ФИКС 4: СТРОГИЙ фильтр служебной подсказки интерфейса игры
#   «Здесь отображаются записи о ваших бросках кубика за последние полгода.»
# Слово «кубика» из этой подсказки раньше распознавалось как ключевое слово и строка
# превращалась в фантомную запись «Твердый кубик (1 шт)». Теперь подсказка (целиком, любая
# её часть и любой вариант с опечатками OCR, в том числе разорванная на две строки)
# вырезается из текста ДО разбора строк — её нельзя ни сопоставить по ключевым словам,
# ни превратить в запись. Список шаблонов МОЖНО ДОПОЛНЯТЬ.
# ---------------------------------------------------------------------------
UI_NOTE_TEXT = "Здесь отображаются записи о ваших бросках кубика за последние полгода."


# Шаблоны (регистр не важен, между словами — любые разделители, включая перенос строки):
UI_NOTE_PATTERNS = tuple(re.compile(p, re.I | re.U) for p in (
    # вся фраза или её хвост, содержащий «бросках кубика»
    r"(?:здесь\W+)?(?:отобража\w*\W+)?(?:записи\W+)?(?:о\W+)?(?:ваших\W+)?"
    r"бросках?\W+кубик\w*(?:\W+за\W+последние\W+пол\W?года)?",
    r"(?:здесь\W+)?отобража\w*\W+записи(?:\W+о\W+ваших)?",   # «Здесь отображаются записи»
    r"записи\W+о\W+ваших\W+бросках?",                          # «записи о ваших бросках»
    r"за\W+последние\W+пол\W?года",                            # «за последние полгода»
    r"здесь\W+отобража\w*",                                     # «Здесь отображаются»
))


_UI_NOTE_NORM = _norm_ui(UI_NOTE_TEXT)


UI_NOTE_FUZZY = 0.75        # доля строки, совпадающая с подсказкой (для опечаток OCR)


UI_NOTE_MIN_LEN = 12        # более короткие обрывки нечётко не сравниваются


def strip_ui_notes_lines(lines: list) -> list:
    """OCR-ФИКС 4: предварительный фильтр. Вырезает служебную подсказку из списка строк и
    возвращает список ТОЙ ЖЕ длины (индексы строк, а значит и цвета рангов line_ranks, не
    сдвигаются). Подсказка ищется по склеенному тексту, поэтому находится и тогда, когда OCR
    разорвал её на две строки («… записи о ваших» / «бросках кубика за последние полгода»).
    Вырезанные символы заменяются пробелами; полностью служебные строки становятся пустыми."""
    lines = list(lines)
    joined = "\n".join(lines)
    mask = [False] * len(joined)
    for rx in UI_NOTE_PATTERNS:
        for m in rx.finditer(joined):
            for k in range(m.start(), m.end()):
                mask[k] = True
    out, pos = [], 0
    for ln in lines:
        seg = "".join(" " if mask[pos + k] else ch for k, ch in enumerate(ln))
        out.append(re.sub(r"\s+", " ", seg).strip())
        pos += len(ln) + 1                         # +1 — символ переноса строки
    return out


def is_ui_note_line(line: str) -> bool:
    """OCR-ФИКС 4: строка — служебная подсказка (или её обрывок с опечатками OCR).
    Настоящие строки таблицы содержат дату и под правило не попадают."""
    if any(rx.search(line or "") for rx in UI_NOTE_PATTERNS):
        return True
    if DATE_RE.search(line or ""):
        return False
    norm = _norm_ui(line)
    if len(norm) < UI_NOTE_MIN_LEN:
        return False
    sm = difflib.SequenceMatcher(None, norm, _UI_NOTE_NORM, autojunk=False)
    return sum(b.size for b in sm.get_matching_blocks()) / len(norm) >= UI_NOTE_FUZZY


# Колонка «Тип» в таблице дуг: «Чудо-коробка» / «Чудо коробка» / «Чудокоробка» (+ искажения OCR)
TYPE_COLUMN_RE = re.compile(r"(?<!\w)[чЧ][уyУ][дlл][оo0][\W_]*[кk][оo0][рp][оo0][бb6]\w*", re.I | re.U)


# Заголовки столбцов: «Дуги Тип Время», «Дуга - Тип Время», «Тип Время», «Дуги Тип»
HEADER_COMBO_RE = re.compile(
    r"(?<!\w)(?:д[уy][гr][аиaи]?)?[\s:|\-–—]*т[иu]п[\s:|\-–—]+(?:в[рp][еe]м[яа]|time)(?!\w)"
    r"|(?<!\w)д[уy][гr][аи][\s:|\-–—]+т[иu]п(?!\w)", re.I | re.U)


HEADER_WORDS = {"дуги", "дуга", "тип", "время", "type", "time"}


def strip_type_column(text: str) -> str:
    """Убирает из строки текст колонки «Тип» («Чудо-коробка») и заголовки столбцов
    («Дуги Тип Время»). Если ничего, кроме них, не было — возвращает пустую строку.
    Строки с датой (настоящие записи) сохраняют название и дату."""
    t = re.sub(r"\s+", " ", text or "").strip()
    if not t:
        return ""
    t = TYPE_COLUMN_RE.sub(" ", t)
    t = HEADER_COMBO_RE.sub(" ", t)
    t = re.sub(r"\s+", " ", t).strip(" |¦,;:-–—")
    words = _norm_ui(t).split()
    if not DATE_RE.search(t) and words and all(w in HEADER_WORDS for w in words):
        return ""                                   # остались только заголовки столбцов
    if _norm_ui(t) in ("дуга", "дуги", "чудо", "коробка"):
        return ""                                   # одинокая подпись типа без названия
    return t


def clean_ocr_line(line: str) -> str:
    """Строка без служебного текста интерфейса; пустая строка — если вся строка служебная
    или в ней нет ни слова, ни времени (одиночные цифры, «|», номера страниц)."""
    # OCR-ФИКС 4: служебная подсказка «… записи о ваших бросках кубика …» убирается первой
    line = strip_ui_notes_lines([line or ""])[0]
    if is_ui_note_line(line):
        return ""
    text = strip_type_column(line or "")            # «Чудо-коробка» и заголовки столбцов
    folded = _norm_ui(text)
    if not folded or folded in OCR_NOISE_WORDS:
        return ""
    # строка целиком похожа на служебную фразу (с опечатками OCR)
    for phrase in _NOISE_FOLDED:
        if (len(phrase) >= OCR_NOISE_MIN_FUZZY
                and abs(len(folded) - len(phrase)) <= max(3, len(phrase) // 4)
                and difflib.SequenceMatcher(None, folded, phrase).ratio() >= OCR_NOISE_FUZZY):
            return ""
    # служебная фраза внутри строки (например, заголовки столбцов в одну строку) — вырезаем
    for rx in _NOISE_REGEXES:
        text = rx.sub(" ", text)
    text = re.sub(r"\s+", " ", text).strip()
    if _norm_ui(text) in OCR_NOISE_WORDS:       # остался одиночный заголовок («Название»)
        return ""
    # без слов и без времени строка бесполезна
    if not (re.search(r"[^\W\d_]{2,}", text) or DATE_RE.search(text)):
        return ""
    return text


def filter_ocr_lines(lines: list) -> list:
    """Убирает служебные строки из результата ocr_image ([{"text", "box"}]).
    Рамки (box) остаются у своих строк, поэтому цветовой анализ рангов не сбивается."""
    out = []
    # OCR-ФИКС 4: подсказка вырезается по ВСЕМУ списку сразу (она может быть разорвана на
    # две строки), затем каждая строка очищается обычными правилами
    stripped = strip_ui_notes_lines([ln["text"] for ln in lines])
    for ln, src in zip(lines, stripped):
        text = clean_ocr_line(src)
        if text:
            out.append(dict(ln, text=text))
    return out


# ----------------------------------------------------------------------------
# НОВОЕ: разбор ВСЕХ круток со скриншота
# ----------------------------------------------------------------------------
_QTY_TOKEN_RE = re.compile(r"^[x×х]?\d{1,3}$", re.I)       # «1», «×5», «x30»


# ИСПРАВЛЕНО: кириллическая «С» убрана — это не S, а буква «Сэ»; она давала ложный ранг S
_RANK_TOKENS = {"S": "S", "A": "A", "B": "B", "А": "A", "В": "B"}  # + кириллица А/В


def _split_row_quantity(body: str):
    """(строка без количества, количество или None). Количество — отдельное число в конце
    или начале строки (столбец «Количество»), с «×» или без; слово «шт» отбрасывается."""
    tokens = body.split()
    if len(tokens) > 1 and tokens[-1].lower().strip(".") == "шт":
        tokens.pop()
    qty = None
    if len(tokens) > 1 and _QTY_TOKEN_RE.match(tokens[-1]):
        qty = re.sub(r"\D", "", tokens.pop())
    elif len(tokens) > 1 and _QTY_TOKEN_RE.match(tokens[0]):
        qty = re.sub(r"\D", "", tokens.pop(0))
    return " ".join(tokens), qty


def _split_row_rank(body: str):
    """(строка без буквы ранга, буква S/A/B или None). Одиночная заглавная буква ранга в
    начале или конце строки (столбец «Ранг»); разделители «|» убираются."""
    tokens = [t for t in body.split() if t.strip("|¦") != ""]
    letter = None
    if len(tokens) > 1 and tokens[-1].strip(".,:;") in _RANK_TOKENS:
        letter = _RANK_TOKENS[tokens.pop().strip(".,:;")]
    elif len(tokens) > 1 and tokens[0].strip(".,:;") in _RANK_TOKENS:
        letter = _RANK_TOKENS[tokens.pop(0).strip(".,:;")]
    return " ".join(tokens), letter


def prepare_ocr_row(line: str):
    """НОВОЕ: ЕДИНАЯ предобработка строки списка перед разбором — одинаковая для ВСЕХ строк
    пакета (и верхних, и нижних), поэтому правила больше не расходятся.
    Убирает значок кубика (запоминая его наличие) и одиночный мусор OCR по краям.
    Возвращает (строка, был_ли_значок_кубика). Звёзды ранга (★) не трогаются."""
    text = strip_type_column(line or "")
    has_dice = bool(DICE_RE.search(text))
    text = re.sub(r"\s+", " ", DICE_RE.sub(" ", text)).strip()
    # OCR-ФИКС 5: «8 персонажеиИрой» / «персонажиИрой» -> «Персонаж: Ирой» ДО отделения
    # количества (одиночная цифра слева не должна стать количеством) и до любых словарей
    text = normalize_iroy_text(text)[0]
    text = normalize_zanku_text(text)[0]            # OCR-ФИКС 7: «Мереспепх - Sexxy» -> Занку
    # OCR-ФИКС 2: мусор, двоеточия и знаки препинания в начале строки срезаются ДО разбора
    # («: Прут …»), затем разделяется слипшийся префикс «предметтолерянны …»
    text = split_fused_item_label(strip_leading_junk(text))
    return strip_leading_junk(text), has_dice


def split_ocr_line(line: str) -> dict:
    """НОВОЕ: делит строку скриншота на название, количество и дату (регулярными выражениями).

    Пример: «Дуга - Настоящая музыка 1 30 апр. 2026 г. 12:03:36» ->
        {"body": "Дуга - Настоящая музыка", "qty": "1",
         "raw_date": "30 апр. 2026 г. 12:03:36", "stamp": "2026-04-30 12:03:36"}
    Порядок действий:
      1) DATE_RE находит дату (числовую или русскую) — она вырезается из строки целиком;
      2) из остатка отделяется количество — отдельное число в конце/начале (_split_row_quantity);
      3) остаток — «чистое» название (дальнейшая очистка — в parse_ocr_result).
    stamp — дата в формате DATE_FMT или None, если даты нет / она не разобралась
    (raw_date при этом сохраняется — её можно показать пользователю)."""
    text = re.sub(r"\s+", " ", line or "").strip()
    m = find_valid_date_match(text)
    raw_date = m.group().strip() if m else ""
    stamp = _find_timestamp(raw_date) if raw_date else None
    # OCR-ФИКС: ПОСЛЕ даты в таблице ничего полезного нет — только мусор OCR от значков и
    # рамок («Ub», «|»). Он мешал найти количество: «… Фравмени 50 Ub». Оставляем лишь
    # числа (на случай другого порядка столбцов) и настоящие слова (от 3 букв).
    tail = ""
    if m:
        tail = " ".join(t for t in text[m.end():].split()
                        if _QTY_TOKEN_RE.match(t) or re.search(r"[^\W\d_]{3,}", t))
    rest = f"{text[:m.start()]} {tail}" if m else text
    rest = strip_leading_junk(re.sub(r"\s+", " ", rest)).strip(" |¦,;:")  # OCR-ФИКС 2
    body, qty = _split_row_quantity(rest)
    return {"body": body, "qty": qty, "raw_date": raw_date, "stamp": stamp}


# ---------------------------------------------------------------------------
# НОВОЕ: СЛОВАРИ ИСПРАВЛЕНИЙ OCR (фрагменты, персонажи) — единое место для дополнений
# ---------------------------------------------------------------------------
# Склеенные и искажённые написания слов «Потерянный» / «Фрагмент»: «подерянныФравмени»,
# «олерянны Фрапмента», «Фрапмента», «Фравмени» и т. п. Ищутся КАК ПОДСТРОКА (пробелы и
# регистр не важны, допускается одна-две опечатки), поэтому слитное написание тоже находится.
FRAGMENT_STEMS = ("фрагмент", "фрагмен", "фрапмент", "фравмен", "потерян", "подерян",
                  "олерянн", "толерян")


FRAGMENT_STEM_CUTOFF = 0.74


# Мусор OCR, который на самом деле — имя персонажа. Ключ — точное имя из состава, значение —
# известные искажения (регистр и пробелы не важны). Например «Mepconax Sarap» — это
# «Персонаж Эдгар», прочитанный с латинскими «двойниками» букв. ДОПОЛНЯЙТЕ по мере появления.
CHARACTER_OCR_ALIASES = {
    # ИЗМЕНЕНО: «Плане ладшии младшего босса» / «младшего босса» — это искажённый планер
    # «Младший босс младшего босса» (см. FORCED_NAME_RULES), а не Эдгар: из алиасов убраны.
    "Эдгар": ("Mepconax Sarap", "Sarap"),
    # ИСПРАВЛЕНО (персонажи): «Персонаж Занку» читается как «NepconarkKgrsanky»
    "Занку": ("NepconarkKgrsanky", "Nepconark Kgrsanky", "Kgrsanky", "Zanky", "Sanky"),
    # «Ирой» — искажения со слитной подписью «Персонаж» (Nepconark / Mepconax + имя)
    "Ирой": ("NepconarkIpoii", "NepconarkHpou", "Mepconax Hpou", "Nepconark Ipoii"),
}


CHARACTER_ALIAS_CUTOFF = 0.84    # строгий порог: короткие алиасы почти не допускают опечаток


CHARACTER_LABEL_CUTOFF = 0.60    # сходство слова с «Персонаж» (искажённая подпись типа)


CHARACTER_LABEL_WORD = "Персонаж"


def _letters_form(text: str) -> str:
    """Только буквы в «свёрнутом» виде (fold_name): без пробелов, цифр и знаков."""
    return re.sub(r"[\W\d_]+", "", fold_name(text))


def _fuzzy_contains(hay: str, needle: str, cutoff: float) -> bool:
    """needle встречается в hay точно или с опечатками (скользящее окно длиной n-1…n+1)."""
    if not hay or not needle:
        return False
    if needle in hay:
        return True
    n = len(needle)
    for size in sorted({max(3, n - 1), n, n + 1}):
        for i in range(0, len(hay) - size + 1):
            if difflib.SequenceMatcher(None, hay[i:i + size], needle).ratio() >= cutoff:
                return True
    return False


def fragment_stem_hint(text: str) -> bool:
    """В тексте есть искажённое «Потерянный» / «Фрагмент» (в том числе слитно)."""
    hay = _letters_form(text)
    return any(_fuzzy_contains(hay, _letters_form(s), FRAGMENT_STEM_CUTOFF)
               for s in FRAGMENT_STEMS)


# ---------------------------------------------------------------------------
# НОВОЕ: МАСТЕР-СПРАВОЧНИК названий и поиск эталонного названия ВНУТРИ строки OCR
# ---------------------------------------------------------------------------
# Единый словарь канонических названий: персонажи S/A (ROSTER_*), дуги S/A (ARC_*_NAMES),
# планеры (GLIDER_NAMES), костюмы (OUTFIT_NAMES), предметы («Потерянный фрагмент»,
# «Твердый кубик» …). Дополнительные названия берутся из двух мест:
#   * файл master_names.json (рядом с main.py или в assets/) — см. формат ниже;
#   * база данных: названия костюмов / планеров / окрасок / скинов из таблицы rewards
#     (названия персонажей и дуг из истории НЕ берутся: опечатка, когда-то сохранённая
#     в истории, не должна «прилипать» повторно).
# Формат master_names.json (все ключи необязательны; элемент — строка или {"name", "rank"}):
#   {"characters": [{"name": "Адлер", "rank": "A"}], "arcs": ["Забытое"], "gliders": [],
#    "outfits": [], "paints": [], "skins": [], "items": []}
# Если в строке OCR найдено эталонное название (точно или с опечатками, среди мусора,
# номеров и лишних символов), ВСЯ строка заменяется чистым каноническим названием с
# префиксом типа («Персонаж: Адлер», «Дуга - Забытое», «Планер - Предвестник»,
# «Костюм - …», «Предмет - Потерянный фрагмент»). Тип, ранг и количество затем
# определяются обычным разбором (parse_ocr_result) уже по чистому названию.
# Конвейер один на все три вкладки («Скриншот», «Скриншот оптом», «Скриншоты разом»):
# все они разбирают текст через ocr_extract_pulls_ex.
MASTER_JSON_NAME = "master_names.json"


MASTER_ITEM_KINDS = ("solid_cube", "trick_cube", "lost_fragment", "warp_fragment")


# Виды предметов из базы, чьи названия пополняют справочник: вид -> слово-префикс
MASTER_DB_KINDS = {"outfit": "Костюм", "glider": "Планер", "paint": "Окраска",
                   "car_skin": "Скин на авто"}


MASTER_JSON_KEYS = {"characters": "character", "arcs": "arc", "gliders": "glider",
                    "outfits": "outfit", "paints": "paint", "skins": "car_skin", "items": "item"}


MASTER_MIN_FUZZY_LEN = 4     # название короче 4 букв — только точное совпадение


MASTER_MIN_GLUED_LEN = 5     # слитный поиск («ПодарокзаочкиАдлер») — только для названий от 5 букв


# слова-подписи типов: помогают выбрать между одинаковыми названиями разных типов
MASTER_CATEGORY_WORDS = {"character": "персонаж", "arc": "дуга", "glider": "планер",
                         "outfit": "костюм", "paint": "окраска", "car_skin": "скин"}


_MASTER_STATE = {"json": [], "db": [], "index": None}


def _master_label(category: str, name: str) -> str:
    """Каноническая строка для разбора: префикс типа + чистое название."""
    if category == "character":
        return f"{CHARACTER_LABEL_WORD}: {name}"
    if category == "arc":
        return f"{DUGA_PREFIX}{name}"
    if category == "glider":
        return f"{GLIDER_PREFIX}{name}"
    if category == "item":
        return f"Предмет - {name}"
    return f"{MASTER_DB_KINDS[category]} - {name}"          # костюм / окраска / скин


def _master_rank(value):
    """Ранг из JSON («S», «A», «B», 5, 4, 3) -> 5 / 4 / 3 или None."""
    if isinstance(value, str):
        value = LETTER_RANKS.get(value.strip().upper().translate(CYR_TO_LAT), value)
    try:
        value = int(value)
    except (TypeError, ValueError):
        return None
    return value if value in RARITIES else None


def _load_master_json() -> list:
    """Читает master_names.json (если есть). Любая ошибка файла игнорируется — программа
    работает по встроенным спискам."""
    roots = [app_dir()] + ([Path(_DATA_DIR)] if _DATA_DIR is not None else [])
    for root in roots:
        for path in (root / MASTER_JSON_NAME, root / "assets" / MASTER_JSON_NAME):
            try:
                data = json.loads(path.read_text(encoding="utf-8-sig"))
            except (OSError, ValueError):
                continue
            if not isinstance(data, dict):
                continue
            out = []
            for key, category in MASTER_JSON_KEYS.items():
                for item in data.get(key) or ():
                    name = item.get("name") if isinstance(item, dict) else item
                    rank = _master_rank(item.get("rank")) if isinstance(item, dict) else None
                    name = clean_name(str(name or ""))
                    if category == "arc":
                        name = strip_labels(name, ("arc",))
                    elif category in MASTER_DB_KINDS:
                        name = strip_item_prefix(category, name)
                    if len(name) >= 2:
                        out.append((category, name, rank))
            return out
    return []


def refresh_master_names(rewards=None) -> None:
    """Перечитывает дополнительные названия: master_names.json и названия костюмов /
    планеров / окрасок / скинов из базы (rewards). Вызывается при запуске и при каждом
    обновлении данных окна."""
    db, seen = [], set()
    for r in rewards or ():
        kind = r.get("kind")
        if kind not in MASTER_DB_KINDS:
            continue
        name = strip_item_prefix(kind, clean_name(r.get("name") or ""))
        if (len(name) < 3 or name.lower() == REWARD_KINDS.get(kind, "").lower()
                or (kind, name.lower()) in seen):
            continue
        seen.add((kind, name.lower()))
        db.append((kind, name, None))
    _MASTER_STATE.update({"json": _load_master_json(), "db": db, "index": None})
    _MASTER_CACHE.clear()


def master_index() -> list:
    """Список эталонов {category, name, label, form, ntok, rank_hint}; строится один раз и
    перестраивается после refresh_master_names."""
    if _MASTER_STATE["index"] is not None:
        return _MASTER_STATE["index"]
    index, seen = [], set()

    def add(category, name, rank_hint=None):
        form = _phrase_form(name)
        if not form or (category, form) in seen:
            return
        seen.add((category, form))
        index.append({"category": category, "name": name, "form": form,
                      "label": _master_label(category, name),
                      "ntok": len(name.split()), "rank_hint": rank_hint})

    for name, _rank, _banner in ROSTER_KNOWN.values():          # персонажи S и A
        add("character", name)
    for full, _rank, _banner in ARC_KNOWN.values():             # дуги S и A
        add("arc", full[len(DUGA_PREFIX):])
    for name in GLIDER_NAMES:
        add("glider", name)
    for phrase, key in KNOWN_PHRASES.items():                   # вручную добавленные эталоны
        if key in ("arc", "glider"):                            # («Забытое», «Чистое небо» …)
            add(key, phrase)
    for name in OUTFIT_NAMES:                                   # костюмы: тип «Костюм», ранг S
        add("outfit", name, OUTFIT_RANK)
    for kind in MASTER_ITEM_KINDS:                              # предметы и ресурсы
        add("item", REWARD_KINDS[kind])
    for category, name, rank in _MASTER_STATE["json"] + _MASTER_STATE["db"]:
        static_rank = None
        if category == "character" and name.lower() in ROSTER_KNOWN:
            static_rank = True
        elif category == "arc" and f"{DUGA_PREFIX}{name}".lower() in ARC_KNOWN:
            static_rank = True
        add(category, name, None if static_rank else rank)
    _MASTER_STATE["index"] = index
    return index


# ---------------------------------------------------------------------------
# НОВОЕ: ЖЁСТКИЕ ПРАВИЛА для названий, которые OCR искажает до неузнаваемости
# ---------------------------------------------------------------------------
# Каждое правило: эталон (category + name из мастер-справочника) и признаки в строке OCR:
#   strong    — [(слово, порог сходства)]: достаточно ОДНОГО похожего слова строки
#               (сравнение через fold_name: латинские «двойники» букв, ё/е, й/и не мешают;
#               слова склеиваются с соседними, поэтому «На стоящая» тоже находится);
#   strong_re — регулярные выражения: достаточно одного совпадения;
#   weak / weak_re — слабые признаки: срабатывают, только если совпали минимум ДВА из них;
#   rank      — если задан, ранг принудительный (цвет на скриншоте игнорируется).
# Правило срабатывает безусловно: строка целиком заменяется эталонным названием.
# ДОПОЛНЯЙТЕ по мере появления новых искажений.
FORCED_NAME_RULES = (
    {   # «Забетонированное» (искажение OCR) -> «Дуга - Забытое»; «Забытые» (другая дуга) не трогаем
        "category": "arc", "name": "Забытое",
        "strong_re": (r"(?i)(?<!\w)заб[еёe]тон\w*",),
    },
    {   # «Младний Gees», «иладнюго Geese», «Пленер - Младний…» -> планер A ранга
        "category": "glider", "name": "Младший босс младшего босса", "rank": 4,
        "strong": (("младший", 0.62), ("младшего", 0.62), ("босс", 0.74), ("босса", 0.74)),
        "strong_re": (r"(?i)(?<!\w)[мmи]\s?л[аa]\s?д[нhшщ]\w*", r"(?i)(?<!\w)и?л[аa]дш\w*",
                      r"(?i)(?<!\w)[бb6][оo0][сc]{2}[аa]?(?!\w)"),
        "weak_re": (r"(?i)(?<![a-z])g[e3]{1,2}s[e3]?s?(?![a-z])",
                    r"(?i)(?<!\w)(?:пл[еёe]н[еe]р\w*|plane\w*)"),
    },
    {   # «олори», «овори», «Хотори» (Tesseract теряет «Х» и путает «т» с «л» / «в») ->
        # персонаж Хотори (ивентовый S ранга). Только для строк-персонажей (без префикса
        # «Дуга» / «Предмет»): ранг принудительный — S, цвет на скриншоте не важен.
        "category": "character", "name": "Хотори", "rank": 5,
        "strong": (("хотори", 0.80),),
        "strong_re": (r"(?i)(?<!\w)[хx]?[оo0][тtлlвb][оo0][рp][иi](?!\w)",),
    },
    {
        "category": "glider", "name": "Предвестник", "rank": 4,
        "strong": (("предвестник", 0.66),),
        "strong_re": (r"(?i)(?<!\w)пр[еe]дв[еe]\w*", r"(?i)\w*[вb][еe]стн[иi][кk](?!\w)",
                      r"(?i)(?<!\w)predvestn\w*"),
    },
    {
        "category": "item", "name": "Фрагмент искривления", "rank": 5,
        "qty": ("30", "16", "4"), "qty_default": "30", "any_lead": True,
        "strong": (("фрагмент искривления", 0.72), ("искривления", 0.74)),
        "strong_re": (r"(?i)стран[аa]\s*сн[аa]", r"(?i)f[il1]?pas[ea]re?",
                      r"(?i)g?[pр]am[il1]c[ea]r", r"(?i)зетав\w*", r"(?i)\w*яхест\w*",
                      r"(?i)фрагмент\s*иск\w*"),
    },
    {
        "category": "item", "name": "Твердый кубик", "rank": 5,
        "qty": ("1", "5"), "qty_default": "1", "any_lead": True,
        "exclude_re": (r"(?i)шул\w*", r"(?i)trick", r"(?i)ш[уy]л[еe]р"),
        "strong": (("кубик", 0.75), ("твердый кубик", 0.74)),
        "strong_re": (r"(?i)re[a-z]{0,2}mn?ear", r"(?i)tesp[ea]p", r"(?i)care{1,2}r",
                      r"(?i)(?<![a-z])pass[ea]r", r"(?i)th?[ea]pa[ea]?[aе]?n", r"(?i)(?<!\w)кубик\w*"),
    },
    {   # «Онасная игpa», «Опаснаяигра», «Дуга - 0пасная игра» -> «Дуга - Опасная игра»
        "category": "arc", "name": "Опасная игра",
        "strong": (("опасная", 0.72), ("опасная игра", 0.75)),
        "weak": (("игра", 0.75),), "weak_re": (r"(?i)(?<!\w)[оo0][пn]?[аa]с\w{0,4}",),
    },
    {   # ИСПРАВЛЕНО: «Мы.» OCR читает как «Мини», «Мыни», «Миы», «MbI» — «Мини» ещё и похоже на
        # персонажа «Минт» (0.75), из-за чего дуга становилась персонажем. «Минт» не затрагивается.
        "category": "arc", "name": "Мы.", "need_lead": "arc",
        "strong_re": (r"(?i)(?<![a-zа-яё0-9])[мm](?:ы|b[l1I]|[иu]ни|[иu]ыи?|[иu]{2})\.?(?![a-zа-яё0-9])",),
    },
    {   # ИСПРАВЛЕНО: «Обнаженный клинок» — искажения слова «клинок» / «обнаженный»
        "category": "arc", "name": "Обнаженный клинок",
        # «Ненасытный клинок» — отдельная дуга S: слово «клинок» само по себе её не превращает
        "exclude_re": (r"(?i)расколот\w*", r"(?i)[аa]с[ыi]тн\w*"),
        "strong": (("обнаженный клинок", 0.72), ("обнаженный", 0.78)),
        "strong_re": (r"(?i)(?<![a-zа-яё])обн[аa]ж\w*", r"(?i)(?<![a-zа-яё])[кk][лnl][иu][нh][оo0][кk](?![a-zа-яё])"),
    },
    {   # «Hастоящая музыкa», «Настояшая муэыка» -> «Дуга - Настоящая музыка»
        "category": "arc", "name": "Настоящая музыка",
        "strong": (("настоящая", 0.72), ("музыка", 0.75), ("настоящая музыка", 0.75)),
    },
    {   # ИСПРАВЛЕНО (костюмы): «Костюм - Бесценная орхидея» Tesseract читает как
        # «Kocmomilbeectiennanlopxvines» (слитно, кириллица/латиница вперемешку) ->
        # ЖЁСТКО «Костюм - Бесценная орхидея», тип «Костюм», ранг S (цвет на скриншоте не важен).
        # Срабатывает на любой из признаков (проверяется и сама строка, и строка без пробелов):
        #   * «Kocmomil…» — искажённое слово «Костюм», слипшееся с названием;
        #   * искажённое «Бесценная» («beectiennan», «Becuennan», «Бесценная»);
        #   * ИЛИ вместе: искажённое «Костюм» + искажённое «орхидея» («opxvines», «opxuneA»).
        # Одно «орхидея» БЕЗ слова «Костюм» не срабатывает: это планер «Орхидеевый бриз».
        "category": "outfit", "name": "Бесценная орхидея", "rank": OUTFIT_RANK, "squash": True,
        "strong": (("бесценная орхидея", 0.70), ("бесценная", 0.70)),
        "strong_re": (
            # «Kocmomil» + буквы названия (костюм слитно с названием)
            r"(?i)[кk][оo0][сc][тtm][a-zа-яё0-9|]{0,3}[мm][il1|!]{1,2}[a-zа-яё]{3,}",
            # «бесценная» с ошибками OCR: b/б, ее/е, c/с, 0-4 любые буквы (ti/ц), nn/нн, a/а/я
            r"(?i)[бb6][eеё]{1,2}[cс][a-zа-яё]{0,4}[nнh]{1,2}[aаяr]",
        ),
        "weak_re": (
            r"(?i)[кk][оo0][сc][тtm][a-zа-яё0-9|]{0,3}[мm]",          # «Костюм» / «Kocmom»
            r"(?i)[оo0][pрr1l][xх×k][iиvuнn]",                         # «орхи…» / «opxv…»
        ),
    },
)


# ---------------------------------------------------------------------------
# ИСПРАВЛЕНО (персонажи): ЖЁСТКИЕ ПРАВИЛА для имён персонажей, которые OCR искажает до мусора
# ---------------------------------------------------------------------------
# Пример: «Персонаж Занку» -> «NepconarkKgrsanky»: слово «Персонаж» превращается в «Nepconark»
# (слитно с именем), а имя — в «Kgrsanky». Работают три уровня (от жёсткого к мягкому):
#   1) CHARACTER_FORCED_PATTERNS — вручную заданные регулярные выражения для имени (ДОПОЛНЯЙТЕ
#      по мере появления новых искажений: добавьте регулярку в кортеж нужного имени);
#   2) регулярные выражения, которые строятся АВТОМАТИЧЕСКИ для ВСЕХ персонажей состава
#      (ROSTER_*): каждая буква заменяется классом «двойников» кириллица / латиница;
#   3) словарь CHARACTER_OCR_ALIASES (резерв, нечёткое сравнение — см. _master_scan).
# Результат — «Персонаж: <имя>» и ранг состава (S / A) принудительно, цвет не важен.
CHAR_LABEL_GARBLE_RE = re.compile(
    r"(?i)^[\W_]*[nmиuhп][eеё3][pрr][cсs][oо0][nнh][aаa][жxkr]{1,2}[\W_]*")


CHARACTER_FORCED_PATTERNS = {
    # «Занку»: Kgrsanky, Zanky, 3анку, Sанку (з -> s/z/3, у -> y/u)
    "Занку": (r"(?i)[sз3z5][aа][nнh][kк][yуu]",
              r"(?i)(?<![a-zа-яё])[zз3][aа][nнh][kк]"),
    # «Ирой»: Ipou, Hpoii, Upoi, Ипой (и -> u/h/n/m, й -> ii/u/и)
    "Ирой": (r"(?i)(?<![a-zа-яё])[иuнhnm1l][pр][oо0][иiйuлn]{1,2}(?![a-zа-яё])",
             r"(?i)(?<![a-zа-яё])[иuнhnm1l][pр][oо0]\s?[иiйuлn]"),
}


# «двойники» букв: какие символы Tesseract подставляет вместо кириллической буквы
_CHAR_LOOKALIKE = {
    "а": "аa", "б": "бb6", "в": "вbv", "г": "гr", "д": "дdg", "е": "еёeэ", "ё": "ёеeэ",
    "ж": "жxk", "з": "зz3sэ", "и": "иuнnhi", "й": "йиiuл", "к": "кk", "л": "лl1", "м": "мm",
    "н": "нhn", "о": "оo0", "п": "пnh", "р": "рp", "с": "сc", "т": "тtm", "у": "уyu",
    "ф": "фf", "х": "хxk", "ц": "цu", "ч": "чn4", "ш": "шw", "щ": "щw", "ъ": "ъb", "ы": "ыb",
    "ь": "ьb", "э": "эe3", "ю": "юio", "я": "яr",
}


_CHAR_LOOKALIKE["ы"] = "ыbl1I"      # ИСПРАВЛЕНО: «ы» OCR читает как «bl» / «bI»


_CHAR_RE_CACHE = {}


def _char_lookalike_body(name: str, gap: bool) -> str:
    """Тело регулярного выражения «имя с двойниками букв»; gap — допускается лишняя буква между
    соседними буквами (OCR вставляет мусор в длинные имена)."""
    parts = []
    for ch in name.lower():
        chars = _CHAR_LOOKALIKE.get(ch, ch)
        parts.append("[" + re.escape("".join(dict.fromkeys(chars))) + "]")
    return ("[a-zа-яё]?" if gap else "").join(parts)


def _char_regexes(name: str):
    """(в границах слова, с начала строки, вся строка) — регулярные выражения имени."""
    cached = _CHAR_RE_CACHE.get(name)
    if cached is None:
        body = _char_lookalike_body(name, gap=len(name) >= 5)
        cached = _CHAR_RE_CACHE[name] = (
            re.compile(rf"(?i)(?<![a-zа-яё]){body}(?![a-zа-яё])"),
            re.compile(rf"(?i)^{body}"),
            re.compile(rf"(?i)^{_char_lookalike_body(name, gap=False)}$"))
    return cached


def garbled_character_name(text: str, lead=None):
    """ИСПРАВЛЕНО (персонажи): (имя из состава, жёсткое ли совпадение) или None. «Жёсткое» —
    сработало ручное правило CHARACTER_FORCED_PATTERNS или слитная искажённая подпись
    «Nepconark…» + имя; мягкое — автоматическая регулярка «двойников» для длинного имени
    (5+ букв). Дуги, планеры и предметы (явный префикс) не затрагиваются."""
    if lead in ("arc", "item") or not text:
        return None
    t = strip_leading_junk(text)
    label = CHAR_LABEL_GARBLE_RE.match(t)
    tail = clean_name(t[label.end():] if label else t)
    squashed = re.sub(r"\s+", "", tail)
    if not squashed:
        return None
    for name, patterns in CHARACTER_FORCED_PATTERNS.items():       # 1) ручные правила
        if any(re.search(p, h) for p in patterns for h in (tail, squashed)):
            return name, True
    labeled = bool(label) or lead == "character"
    for name, _rank, _banner in ROSTER_KNOWN.values():              # 2) автоматические
        bounded, prefix, whole = _char_regexes(name)
        if whole.match(squashed) and (labeled or len(name) >= 4):
            return name, labeled
        if labeled and prefix.match(squashed):                       # «NepconarkKgrsanky»
            return name, True
        if len(name) >= 5 and bounded.search(tail):
            return name, False
    return None


_RULE_RE_CACHE = {}


# Слова-«шум», которые никогда не бывают названием: подарок / очки / предмет / подписи бонуса
_MASTER_NOISE_RE = re.compile(
    r"(?<!\w)(?:п[оo0]д[аa][рp]\w{0,4}|за\s+очки|очки|пр[еe]дм[еe]т\w*)(?!\w)", re.I)


def _rule_word_hit(tokens: list, word: str, cutoff: float) -> bool:
    """Есть ли среди слов строки (и склеек соседних слов) слово, похожее на эталонное."""
    target = _phrase_form(word)
    variants = tokens + [a + b for a, b in zip(tokens, tokens[1:])]
    for v in variants:
        f = _phrase_form(v)
        if len(f) < 4 or abs(len(f) - len(target)) > max(2, len(target) // 3):
            continue
        if f == target or difflib.SequenceMatcher(None, f, target).ratio() >= cutoff:
            return True
    return False


def _rule_re_hit(pattern: str, text: str) -> bool:
    rx = _RULE_RE_CACHE.get(pattern)
    if rx is None:
        rx = _RULE_RE_CACHE[pattern] = re.compile(pattern)
    return bool(rx.search(text))


def forced_name_rule(text: str, lead=None):
    """Жёсткое правило: возвращает эталон-словарь master_index() для строки, в которой
    есть признаки искажённого названия из FORCED_NAME_RULES, иначе None."""
    tokens = re.findall(r"[^\W_]+", text or "")
    if not tokens:
        return None
    allowed = {"arc": ("arc",), "character": ("character",),
               "item": ("glider", "arc", "outfit", "item")}.get(lead)
    squashed = re.sub(r"\s+", "", text or "")      # для слитных искажений («Kocmomil beec…»)
    for rule in FORCED_NAME_RULES:
        if allowed is not None and rule["category"] not in allowed and not rule.get("any_lead"):
            continue
        if rule.get("need_lead") and lead != rule["need_lead"]:
            continue                      # правило только для строк с явным префиксом («Дуга - …»)
        if any(_rule_re_hit(rx, text) for rx in rule.get("exclude_re", ())):
            continue
        # правило с "squash": регулярные выражения проверяются и по строке без пробелов
        hay = (text, squashed) if rule.get("squash") else (text,)
        strong = (any(_rule_word_hit(tokens, w, c) for w, c in rule.get("strong", ()))
                  or any(_rule_re_hit(rx, h) for rx in rule.get("strong_re", ()) for h in hay))
        weak = (sum(1 for w, c in rule.get("weak", ()) if _rule_word_hit(tokens, w, c))
                + sum(1 for rx in rule.get("weak_re", ()) if any(_rule_re_hit(rx, h) for h in hay)))
        if strong or weak >= 2:
            for e in master_index():
                if e["category"] == rule["category"] and e["name"] == rule["name"]:
                    return dict(e, force_rank=rule.get("rank"), qty_options=rule.get("qty"),
                                qty_default=rule.get("qty_default"))
    return None


_MASTER_CACHE = {}


# ИСПРАВЛЕНО (баннер дуг): в этом баннере выпадают только дуги (и предметы: кубики, фрагменты).
# Персонажи, костюмы, планеры, окраски / детали модификации и скины на авто выпасть не могут,
# поэтому в режиме «только дуги» они исключаются из всех справочников и правил.
ARC_BANNER_BLOCKED_LOOT = ("character", "outfit", "glider", "paint", "car_skin")


ARC_BANNER_ALLOWED_CATEGORIES = ("arc", "item")


# префиксы типов, которых в баннере дуг быть не может: «Персонаж:», «Костюм -», «Планер -»,
# «Окраска», «Скин на авто», «Детали модификации -» (с типичными искажениями OCR)
_ARC_BLOCKED_PREFIX_RE = re.compile(
    r"^\W*(?:[пnm][еeё][рp][сc][оo0][нnh][аa][жxk]\w*|[кk][оo0][сc][тt][юуy][мm]\w*"
    r"|[пn][лl][аa][нh][еeё][рp]\w*|[оo0][кk][рp][аa][сc][кk]\w*|[сc][кk][иi][нh]\w*"
    r"|[дd][еeё][тt][аa][лl][иi]\s+[мm][оo0][дd]\w*|[мm][оo0][дd][иi][фf]\w*)"
    r"(?:\s+[нh][аa]\s+[аa][вb][тt][оo0])?[\s:.\-–—|]*", re.I | re.U)


def strip_arc_blocked_prefix(body: str) -> str:
    """Баннер дуг: убирает префикс запрещённого типа («Персонаж: Мы.» -> «Мы.»)."""
    t = _ARC_BLOCKED_PREFIX_RE.sub("", body or "", count=1).strip()
    return t or (body or "")


def master_match(body: str, arc_only: bool = False):
    """Ищет в строке OCR эталонное название из мастер-справочника (как подстроку, точно или
    с опечатками). Возвращает {"label", "name", "category", "score", "matched", "rank"} или
    None. label — чистое каноническое название с префиксом типа; matched — фрагмент строки,
    по которому найдено совпадение; score — сходство (1.0 — точное).

    Осторожность: сравниваются «окна» из соседних слов (мусор и номера вокруг отбрасываются),
    у названий короче MASTER_MIN_FUZZY_LEN допустимо только точное совпадение, при почти
    одинаковых кандидатах разных названий результат не засчитывается. Явный префикс строки
    («Дуга - …», «Персонаж: …», «Предмет - …») ограничивает типы кандидатов. Точное название
    важнее словаря искажений CHARACTER_OCR_ALIASES, а словарь — важнее нечёткого поиска."""
    key = (body, True) if arc_only else body
    cached = _MASTER_CACHE.get(key)
    if cached is not None:
        return dict(cached[0]) if cached[0] else None
    result = _master_match_uncached(body, arc_only)
    if arc_only and result and result.get("category") not in ARC_BANNER_ALLOWED_CATEGORIES:
        result = None                       # персонаж / костюм / планер / окраска в баннере дуг — нет
    if len(_MASTER_CACHE) > 4000:
        _MASTER_CACHE.clear()
    _MASTER_CACHE[key] = (dict(result) if result else None,)
    return dict(result) if result else None


def _master_match_uncached(body: str, arc_only: bool = False):
    """Тело master_match без кэша (см. описание выше). arc_only — баннер дуг: только дуги и
    предметы (кубики, фрагменты), без персонажей, костюмов, планеров и окрасок."""
    if arc_only:
        body = strip_arc_blocked_prefix(body)
    plain = clean_lookup_text(body or "") or strip_leading_junk(body or "")
    # OCR-ФИКС 5 (Ирой): «8 персонажеиИрой» / «персонажиИрой» -> строго «Персонаж: Ирой», ранг
    # состава принудительный (цвет не важен). Проверка идёт ДО словарей и нечёткого поиска.
    plain, iroy_hit = normalize_iroy_text(plain)
    if iroy_hit and not arc_only:
        entry = next((e for e in master_index()
                      if e["category"] == "character" and e["name"] == IROY_NAME), None)
        if entry:
            rank = ROSTER_KNOWN[IROY_NAME.lower()][1]
            return {"label": entry["label"], "name": IROY_NAME, "category": "character",
                    "score": 1.0, "matched": plain, "rank": rank, "force_rank": rank}
    plain, zanku_hit = normalize_zanku_text(plain)      # OCR-ФИКС 7: Занку (S)
    if zanku_hit and not arc_only:
        entry = next((e for e in master_index()
                      if e["category"] == "character" and e["name"] == ZANKU_NAME), None)
        if entry:
            rank = ROSTER_KNOWN[ZANKU_NAME.lower()][1]
            return {"label": entry["label"], "name": ZANKU_NAME, "category": "character",
                    "score": 1.0, "matched": plain, "rank": rank, "force_rank": rank}
    lead = leading_type(plain)             # тип по префиксу — до того, как префиксы будут сняты
    if arc_only and lead != "item":
        lead = "arc"                       # баннер дуг: строка без предметного префикса — дуга
    # OCR-ФИКС 5 (Занку): строка с ключевым словом предмета / ресурса ищется ТОЛЬКО среди
    # предметов (персонажи исключены: lead="item" не допускает категорию «character»)
    if lead != "arc" and is_resource_text(plain):
        lead = "item"
    elif arc_only and lead == "arc" and not plain:
        return None
    bonus_soft = bool(BONUS_MARK_RE.search(plain))   # «Подарок за очки»: только точные имена
    # НОВОЕ: перед сравнением из строки убираются «Подарок за очки», «Предмет», подписи бонуса
    # и ранг в начале — они не должны мешать нечёткому поиску названия
    stripped = BONUS_NOISE_RE.sub(" ", BONUS_MARK_RE.sub(" ", plain))
    stripped = strip_leading_junk(_MASTER_NOISE_RE.sub(" ", stripped))
    stripped = strip_leading_junk(strip_labels(re.sub(r"\s+", " ", stripped), ("rank", "item")))
    # жёсткие правила для искажённых названий (Опасная игра, Настоящая музыка, планер)
    forced = forced_name_rule(stripped, lead) or (
        forced_name_rule(plain, lead) if stripped != plain else None)
    if forced:
        return {"label": forced["label"], "name": forced["name"],
                "category": forced["category"], "score": 1.0, "matched": stripped or plain,
                "rank": forced.get("rank_hint"), "force_rank": forced.get("force_rank"),
                "qty_options": forced.get("qty_options"),
                "qty_default": forced.get("qty_default")}
    result = _master_scan(stripped, lead, arc_only)
    if result is None and stripped != plain:      # слитное «ПодарокзаочкиАдлер» съедено целиком
        result = _master_scan(plain, lead, arc_only)
    # ИСПРАВЛЕНО (персонажи): жёсткие правила имён («NepconarkKgrsanky» -> Занку). Жёсткое
    # совпадение важнее поиска по справочнику; мягкое — только если справочник ничего не нашёл
    # или нашёл персонажа (так дуга / планер не превращаются в персонажа)
    garbled = None if arc_only else (garbled_character_name(stripped, lead) or (
        garbled_character_name(plain, lead) if stripped != plain else None))
    if garbled and garbled[0].lower() in (stripped or plain).lower():
        garbled = None                      # имя прочитано точно — обычный разбор, ничего не форсируем
    if bonus_soft:
        garbled = None                      # OCR-ФИКС 5: в бонусной строке персонажа не «угадываем»
        if result and result["category"] == "character" and result["score"] < 1.0:
            result = None                   # нечёткое совпадение с персонажем — не засчитываем
    if garbled and (garbled[1] or result is None or result["category"] == "character"):
        entry = next((e for e in master_index()
                      if e["category"] == "character" and e["name"] == garbled[0]), None)
        if entry:
            rank = ROSTER_KNOWN[garbled[0].lower()][1]
            return {"label": entry["label"], "name": entry["name"], "category": "character",
                    "score": 1.0 if garbled[1] else 0.9, "matched": stripped or plain,
                    "rank": rank, "force_rank": rank}
    # ИСПРАВЛЕНО (костюмы): встроенные костюмы (OUTFIT_NAMES) — всегда ранг S, цвет не важен
    if result and result["category"] == "outfit" and result["name"] in OUTFIT_NAMES:
        result["force_rank"] = OUTFIT_RANK
    return result


MASTER_GLUED_FUZZY_LEN = 7        # нечёткий слитный поиск — только для названий от 7 букв


MASTER_GLUED_FUZZY_BONUS = 0.07   # порог сходства строже обычного (меньше ложных срабатываний)


def _glued_fuzzy(glued: str, folded: str, cutoff: float) -> float:
    """Нечёткий поиск названия в строке без пробелов (OCR слепил или разорвал слова и добавил
    лишние буквы): скользящее окно длиной len(folded) ± 1. 0.0 — совпадения нет."""
    n, best = len(folded), 0.0
    matcher = difflib.SequenceMatcher(None, autojunk=False)
    matcher.set_seq2(folded)
    for size in (n, n - 1, n + 1):
        for i in range(0, max(0, len(glued) - size) + 1):
            matcher.set_seq1(glued[i:i + size])
            if matcher.real_quick_ratio() < cutoff or matcher.quick_ratio() < cutoff:
                continue
            best = max(best, matcher.ratio())
    return best if best >= cutoff else 0.0


def _master_scan(text: str, lead=None, arc_only: bool = False):
    """Поиск эталона в уже подготовленной строке (см. master_match)."""
    tokens = re.findall(r"[^\W_]+", text)
    if not tokens:
        return None
    allowed = {"arc": ("arc",), "character": ("character",),
               "item": ("glider", "outfit", "paint", "car_skin", "item", "arc")}.get(lead)
    if arc_only:
        allowed = ARC_BANNER_ALLOWED_CATEGORIES      # баннер дуг: только дуги и предметы
    glued = _phrase_form(text)
    whole = _phrase_form(split_garbled_type(text)[1])   # название без префикса типа
    found = []                                  # (сходство, длина формы, эталон, фрагмент)
    for e in master_index():
        if allowed and e["category"] not in allowed:
            continue
        folded, n = e["form"], e["ntok"]
        cutoff = ROSTER_MATCH_CUTOFF if e["category"] == "character" else PHRASE_MATCH_CUTOFF
        best, where = 0.0, ""
        for size in range(max(1, n - 1), n + 2):
            for i in range(0, len(tokens) - size + 1):
                part = tokens[i:i + size]
                window = _phrase_form(" ".join(part))
                if window == folded:
                    if len(folded) < MASTER_MIN_FUZZY_LEN and folded != whole:
                        continue    # ИСПРАВЛЕНО: «Мы» внутри «Мы вместе» — не дуга «Мы.»
                    score = 1.0
                elif (len(folded) < MASTER_MIN_FUZZY_LEN
                      or abs(len(window) - len(folded)) > max(2, len(folded) // 4)):
                    continue
                else:
                    score = difflib.SequenceMatcher(None, window, folded).ratio()
                    if score < cutoff:
                        continue
                if score > best:
                    best, where = score, " ".join(part)
        if not best and len(folded) >= MASTER_MIN_GLUED_LEN and folded in glued:
            best, where = 1.0, text                     # слитное написание без пробелов
        if not best and len(folded) >= MASTER_GLUED_FUZZY_LEN and len(glued) >= len(folded) - 1:
            best, where = _glued_fuzzy(glued, folded, cutoff + MASTER_GLUED_FUZZY_BONUS), text
        if best:
            found.append((best, len(folded), e, where))
    found.sort(key=lambda t: (-t[0], -t[1]))
    exact = [t for t in found if t[0] >= 1.0]
    pick = None
    if exact:
        top = [t for t in exact if t[1] == exact[0][1]]
        if len({t[2]["category"] for t in top}) > 1:    # одно название у разных типов
            low = fold_name(text)
            top = [t for t in top
                   if fold_name(MASTER_CATEGORY_WORDS.get(t[2]["category"], "~~")) in low]
        if len({t[2]["category"] for t in top}) == 1:
            pick = top[0]
    else:
        # словарь известных искажений имён персонажей («Mepconax Sarap» -> Эдгар)
        if lead is None:
            hay = _letters_form(text)
            for name, aliases in CHARACTER_OCR_ALIASES.items():
                if any(_fuzzy_contains(hay, _letters_form(a), CHARACTER_ALIAS_CUTOFF)
                       for a in aliases):
                    entry = next((e for e in master_index()
                                  if e["category"] == "character" and e["name"] == name), None)
                    if entry:
                        return {"label": entry["label"], "name": name, "category": "character",
                                "score": CHARACTER_ALIAS_CUTOFF, "matched": text, "rank": None}
        if found:
            ranked = {}
            for t in found:                               # лучший результат по каждому названию
                ranked.setdefault((t[2]["category"], t[2]["name"]), t)
            ranked = sorted(ranked.values(), key=lambda t: (-t[0], -t[1]))
            if len(ranked) == 1 or ranked[0][0] - ranked[1][0] >= PHRASE_AMBIGUITY_GAP:
                pick = ranked[0]
    if not pick:
        return None
    score, _n, e, where = pick
    return {"label": e["label"], "name": e["name"], "category": e["category"],
            "score": score, "matched": where, "rank": e["rank_hint"]}


# ---------------------------------------------------------------------------
# ИСПРАВЛЕНО: ОГРАНИЧЕННОЕ СОПОСТАВЛЕНИЕ названия по типу строки и цвету (рангу)
# ---------------------------------------------------------------------------
# Проблема: у строк с цветной обводкой (розовые A, золотые S) Tesseract портит и название, и
# слово-тип («Муга», «Пленер», «Nepconax»), а общий поиск по справочнику требует высокого
# сходства и отбрасывает такие строки. Но у строки известны ТИП (префикс «Дуга» / «Планер» /
# «Персонаж», даже искажённый) и РАНГ (цвет текста) — значит, искать надо не среди всех
# названий, а только среди названий этого типа и ранга: у A-персонажей 6 имён, у дуг B ранга
# 4 названия, у планеров 9. В таком маленьком наборе безопасно принимать и сильно искажённое
# написание, если оно заметно ближе к одному названию, чем к остальным.
SNAP_TYPE_WORDS = {"arc": "дуга", "glider": "планер", "character": "персонаж", "item": "предмет"}


SNAP_TYPE_CUTOFF = 0.60       # похожесть первого слова на слово-тип («Муга», «Пленер»)


SNAP_NAME_CUTOFF = 0.50       # минимальное сходство названия с эталоном внутри набора


SNAP_NAME_CUTOFF_LONG = 0.60  # то же для длинных названий (от 8 букв)


SNAP_MARGIN = 0.12            # отрыв лучшего эталона от второго — иначе не угадываем


SNAP_SHORT_FORM = 3           # название из ≤3 букв («Мы.») — отдельное правило (см. ниже)


_SNAP_HEAD_RE = re.compile(r"^\s*([^\s\-–—:|]{2,12})\s*(?:[\-–—:|]\s*|\s+)(.+)$")


# Путаницы Tesseract на ЦВЕТНЫХ строках с чёрной обводкой (розовый / золотой шрифт): буквы
# сливаются в «пятна» — «Минт» читается как «Maar» (и/н -> a, т -> r). Используются только при
# сопоставлении внутри набора «тип + ранг» (constrained_master_match), где вариантов единицы.
_STYLED_CONFUSION = {"и": "aeu", "н": "ah", "т": "rm", "к": "rk", "л": "an", "п": "n", "д": "a",
                     "я": "ar", "ь": "b", "ы": "bl", "а": "ao", "о": "ao", "е": "ec", "с": "ce"}


def _lookalike_cost(got: str, want: str) -> float:
    """Цена замены символа OCR на нужную букву: 0 — «двойник» (о/o/0, н/h/n, я/r…),
    0.35 — типичная путаница шрифта с обводкой (и -> a, т -> r)."""
    if got == want:
        return 0.0
    if got in _CHAR_LOOKALIKE.get(want, "") or fold_name(got) == fold_name(want):
        return 0.0
    if got.lower() in _STYLED_CONFUSION.get(want.lower(), ""):
        return 0.35
    return 1.0


def lookalike_similarity(raw: str, target: str) -> float:
    """Сходство 0..1: расстояние Левенштейна, где замена на «двойник» буквы бесплатна, а
    лишний знак препинания / цифра (мусор OCR) стоит вдвое дешевле лишней буквы."""
    a = re.sub(r"[\s.\-–—:|_]+", "", (raw or "").lower())
    b = re.sub(r"[\s.\-–—:|_]+", "", (target or "").lower())
    if not a or not b:
        return 0.0
    prev = [float(j) for j in range(len(b) + 1)]
    for i, ca in enumerate(a, 1):
        cur = [float(i)]
        junk = 0.5 if not ca.isalpha() else 1.0
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + junk,                       # лишний символ в OCR
                           cur[j - 1] + 1.0,                     # потерянная буква
                           prev[j - 1] + _lookalike_cost(ca, cb)))
        prev = cur
    return max(0.0, 1.0 - prev[-1] / max(len(a), len(b)))


def split_garbled_type(body: str):
    """(тип, остаток): тип — «arc» / «glider» / «character» / «item» / None по первому слову
    строки, даже искажённому («Муга», «Пленер», «Nepconax»); остаток — название без него."""
    t = strip_leading_junk(clean_name(body or ""))
    t = strip_leading_junk(_MASTER_NOISE_RE.sub(" ", BONUS_MARK_RE.sub(" ", t)))
    t = re.sub(r"\s+", " ", t).strip()
    head = _SNAP_HEAD_RE.match(t)
    if head:
        word, rest = head.group(1), head.group(2)
        best, kind = 0.0, None
        for k, ref in SNAP_TYPE_WORDS.items():
            score = lookalike_similarity(word, ref)
            if score > best:
                best, kind = score, k
        if kind and best >= SNAP_TYPE_CUTOFF and rest.strip():
            return kind, re.sub(r"\s+", " ", rest).strip()
    return None, t


def _snap_rank_of(entry: dict):
    """Ранг эталона мастер-справочника (5 / 4 / 3) или None, если он не задан."""
    cat, name = entry["category"], entry["name"]
    if cat == "character":
        info = ROSTER_KNOWN.get(name.lower())
        return info[1] if info else entry.get("rank_hint")
    if cat == "arc":
        info = ARC_KNOWN.get(f"{DUGA_PREFIX}{name}".lower())
        return info[1] if info else entry.get("rank_hint")
    if cat == "glider":
        return FIXED_RARITY.get("glider", 4)
    return entry.get("rank_hint")


def constrained_master_match(body: str, color=None, arc_only: bool = False):
    """Сопоставление с мастер-справочником ТОЛЬКО среди названий нужного типа и ранга.
    Возвращает словарь как master_match() или None. Вызывается после обычного поиска, если он
    ничего не нашёл. Тип берётся из (возможно искажённого) префикса строки, ранг — из цвета.
    Без явного префикса работает лишь для серых строк (ранг B): это всегда дуги."""
    kind, name = split_garbled_type(body)
    if arc_only:                        # баннер дуг: любая строка — только дуга (цвет задаёт ранг)
        if kind in ("character", "outfit", "glider", "paint", "car_skin"):
            name = strip_arc_blocked_prefix(body)
        kind, strict = "arc", kind in (None, "item")
    elif kind in (None, "item"):
        if color != 3:
            return None
        kind = "arc"                    # серая строка без читаемого префикса — дуга B ранга
        strict = True
    else:
        strict = False
    letters = re.sub(r"[\W_]+", "", name)
    if not letters:
        return None
    pool = []
    for e in master_index():
        if e["category"] != kind:
            continue
        rank = _snap_rank_of(e)
        if color and rank and rank != color:
            continue                    # цвет строки уже определил ранг — чужие ранги не нужны
        pool.append(e)
    if not pool:
        return None
    scored = []
    for e in pool:
        target = e["name"]
        score = lookalike_similarity(name, target)
        # OCR часто теряет начало / конец слова: сравниваем и с «обрезанным» названием
        if len(re.sub(r"[\W_]+", "", target)) >= 4:
            score = max(score, lookalike_similarity(name, target[:-1]) - 0.05,
                        lookalike_similarity(name, target[1:]) - 0.05)
        need = SNAP_NAME_CUTOFF_LONG if len(target) >= 8 else SNAP_NAME_CUTOFF
        if len(re.sub(r"[\W_]+", "", target)) <= SNAP_SHORT_FORM:
            need = 0.99                 # короткое название («Мы.») — только точное (см. ниже)
        if strict:
            need += 0.1
        if score >= need:
            scored.append((score, e))
    scored.sort(key=lambda t: -t[0])
    pick = None
    if scored and (len(scored) == 1 or scored[0][0] - scored[1][0] >= SNAP_MARGIN):
        pick = scored[0]
    elif not scored and len(letters) <= SNAP_SHORT_FORM + 1 and kind == "arc" and color == 3:
        # крошечный обрывок серой дуги не похож ни на одно длинное название: это короткая дуга
        # («Мы.») — выбираем её, только если такая в наборе ровно одна
        # и только если в строке есть признак искажения (латиница / цифра / «|»): чисто
        # кириллическое «Мир» или «Мыс» — это другое слово, а не испорченное «Мы.»
        short = [e for e in pool if len(re.sub(r"[\W_]+", "", e["name"])) <= SNAP_SHORT_FORM]
        if (len(short) == 1 and re.search(r"[A-Za-z0-9|!]", name)
                and lookalike_similarity(name, short[0]["name"]) >= 0.5):
            pick = (0.5, short[0])
    if not pick:
        return None
    score, e = pick
    return {"label": e["label"], "name": e["name"], "category": e["category"],
            "score": min(score, 0.99), "matched": name, "rank": None}


refresh_master_names()          # встроенные списки + master_names.json (если файл есть)


def apply_ocr_corrections(body: str, qty=None, known: dict = None):
    """НОВОЕ: единый шаг исправлений названия строки (вызывается из ocr_extract_pulls, то есть
    одинаково для вкладок «Скриншот» и «Скриншот оптом»). Возвращает каноническую строку
    или None, если исправлять нечего:
      * искажённое имя персонажа («Mepconax Sarap», «Плане ладшии младшего босса») ->
        «Персонаж: Эдгар» (словарь CHARACTER_OCR_ALIASES); искажённая подпись «Персонаж»
        + имя, похожее на состав, -> «Персонаж: <имя из состава>»;
      * «подерянныФравмени», «олерянны Фрапмента», «Фрапмента», «Фравмени» ->
        «Предмет - Потерянный фрагмент» (количество 30 / 50 берётся из строки);
      * дуги («дуга Чиетое небо») исправляет snap_known_phrase (KNOWN_PHRASES) в parse_ocr_result.
    Явные префиксы («Дуга - …», «Персонаж: …») и бонусы «Подарок за очки» не затрагиваются."""
    clean = strip_leading_junk(body or "")
    if not clean or BONUS_MARK_RE.search(clean):
        return None
    lead = leading_type(clean)
    if lead == "arc" or snap_known_phrase(clean, keys=("arc",) + ITEM_PHRASE_KEYS):
        return None                                    # эталонная дуга / предмет — не трогаем
    hay = _letters_form(clean)
    # OCR-ФИКС 5: строка с ключевым словом предмета / ресурса никогда не превращается в персонажа
    if lead is None and not is_resource_text(clean):
        for name, aliases in CHARACTER_OCR_ALIASES.items():
            if any(_fuzzy_contains(hay, _letters_form(a), CHARACTER_ALIAS_CUTOFF)
                   for a in aliases):
                return f"{CHARACTER_LABEL_WORD}: {name}"
        tokens = clean.split()
        if len(tokens) >= 2:                           # искажённая подпись «Персонаж» + имя
            first = _letters_form(tokens[0])
            if (6 <= len(first) <= 10 and not fragment_stem_hint(tokens[0])
                    and difflib.SequenceMatcher(None, first, _letters_form(
                        CHARACTER_LABEL_WORD)).ratio() >= CHARACTER_LABEL_CUTOFF):
                rest = " ".join(tokens[1:])
                hit = match_roster_name(rest)
                name = hit[0] if hit else clean_character_name(rest)
                if name:
                    return f"{CHARACTER_LABEL_WORD}: {name}"
    if lead in (None, "item") and fragment_stem_hint(clean):
        name = strip_labels(clean_name(clean), ("rank", "item"))
        if not _is_real_name(name, known):
            kind = "warp_fragment" if re.search(r"искр|warp", clean.lower()) else "lost_fragment"
            return f"Предмет - {REWARD_KINDS[kind]}"
    return None


# ---------------------------------------------------------------------------
# НОВОЕ: ЕДИНЫЙ КОНВЕЙЕР OCR для вкладок «Скриншот» и «Скриншот оптом»
# ---------------------------------------------------------------------------
def run_ocr_pipeline(path: str) -> dict:
    """Шаг 1 (тяжёлый, выполняется в фоновом потоке): подготовка изображения, Tesseract,
    очистка мусора и служебных строк, определение ранга по цвету текста.
    Возвращает {"lines", "text", "ranks", "glob"}. Бросает OcrError.

    Двухконвейерная схема: ТЕКСТ строк — конвейер Б (ocr_image: улучшенная копия строки ->
    Tesseract); РАНГ — конвейер А (detect_rarity_colors: пиксели неизменённого снимка по
    рамке названия). Конвейеры независимы: конвейер Б меняет только текст строки."""
    info = {}
    lines = filter_ocr_lines(ocr_image(path, info=info))  # конвейер Б: текст
    PAGE_INFO[path] = info.get("page")                   # номер страницы «N/M» (или None)
    PAGE_ALTS[path] = info.get("page_alts") or []
    ranks, glob = detect_rarity_colors(path, lines)      # конвейер А: ранг по цвету (без изменений)
    return {"lines": lines, "text": "\n".join(ln["text"] for ln in lines),
            "ranks": ranks, "glob": glob, "page": info.get("page"),
            "confs": [line_confidence(ln) for ln in lines]}     # НОВОЕ: уверенность по строкам


def parse_screenshot_text_ex(text: str, known: dict, ranks=None, glob=None,
                             default_loot: str = "character", confs=None):
    """Шаг 2 (лёгкий, в окне): разбор текста в записи — фильтр подсказок интерфейса, чистка
    строк, словари исправлений, ранги, типы, время. Цвета и уверенность по строкам годятся,
    только пока число строк не изменилось. Возвращает (записи, число пропущенных строк,
    нераспознанные строки для «Редактора нераспознанных строк»)."""
    n = len((text or "").splitlines())
    ranks = ranks if ranks is not None and n == len(ranks) else None
    confs = confs if confs is not None and n == len(confs) else None
    return ocr_extract_pulls_ex(text, known, ranks, glob, default_loot, confs)


def parse_screenshot_text(text: str, known: dict, ranks=None, glob=None,
                          default_loot: str = "character"):
    """Совместимая обёртка (вкладка «Скриншот»): возвращает (записи, число пропущенных строк)."""
    pulls, skipped, _rows = parse_screenshot_text_ex(text, known, ranks, glob, default_loot)
    return pulls, skipped


def ocr_extract_pulls(text: str, known: dict, line_ranks: list = None,
                      global_rank: int = None, default_loot: str = "character"):
    """Совместимая обёртка: (список круток, число пропущенных строк) — см. ocr_extract_pulls_ex."""
    pulls, skipped, _rows = ocr_extract_pulls_ex(text, known, line_ranks, global_rank,
                                                 default_loot)
    return pulls, skipped


def _next_row_lacks_stamp(lines: list, i: int) -> bool:
    for j in range(i + 1, len(lines)):
        cleaned = clean_ocr_line(lines[j])
        if not cleaned:
            continue
        cleaned, _dice = prepare_ocr_row(cleaned)
        if not cleaned:
            continue
        part = split_ocr_line(cleaned)
        return bool(re.search(r"[^\W\d_]{2,}", part["body"])) and part["stamp"] is None
    return False


def _is_recognized_row(body: str) -> bool:
    """НОВОЕ: строка без даты всё равно настоящая запись, если в ней есть распознанное
    название: явный префикс «Дуга - Название» / «Персонаж: Имя» или совпадение с
    мастер-справочником (персонажи, дуги, планеры, костюмы, предметы)."""
    clean = strip_leading_junk(body or "")
    if leading_type(clean) in ("arc", "character") and strip_labels(
            clean_name(clean), ("rank", "arc", "char", "item")):
        return True
    # ИСПРАВЛЕНО: обрывок без даты и префикса («мини» — мусор из заголовка) нечётким совпадением
    # («мини» ~ «Минт») записью не становится: нужно точное совпадение с эталоном
    found = master_match(body)
    return found is not None and found["score"] >= 1.0


# OCR-ФИКС 6: страница истории NTE — ровно 5 записей одной крутки; все 5 строк имеют ОДНО время
OCR_PAGE_SIZE = 5


OCR_PAGE_COMPLETE = True       # достраивать недостающие строки страницы (False — отключить)


def inherit_page_dates(rows: list) -> None:
    """OCR-ФИКС 6: наследование даты пула. Строки скриншота — одна крутка: у строки без
    прочитанной даты (или с системной датой «сегодня», подставленной вместо неверной) время берётся
    у ближайшей строки с самым частым достоверным временем. Если к дню приклеилась цифра
    количества («15 май» вместо «1 | 5 май»), день исправляется по общей дате страницы."""
    stamped = [r for r in rows if r["stamp"]]
    if not stamped:
        return
    # День-буква («Б май» — это 5 или 6 мая) — слабое свидетельство: если на странице есть
    # строки с ЯСНО прочитанным днём, выбирается вариант, совпадающий с ними (по времени
    # суток — сильнее, по дате — слабее). Раньше «Б» всегда становилась 6-м числом и даже
    # перебивала настоящие «5 май» при подсчёте большинства.
    firm = [r for r in stamped if not soft_day_stamps(r.get("raw_date") or "")]
    if firm:
        firm_full = Counter(r["stamp"] for r in firm)
        firm_date = Counter(r["stamp"][:10] for r in firm)
        for r in stamped:
            alts = soft_day_stamps(r.get("raw_date") or "")
            if not alts:
                continue
            best = max(alts, key=lambda a: (firm_full.get(a, 0), firm_date.get(a[:10], 0)))
            if firm_full.get(best, 0) or firm_date.get(best[:10], 0):
                r["stamp"] = best
    # Строки с ОДИНАКОВЫМ временем суток (ЧЧ:ММ:СС) — одна крутка; если у меньшинства из них
    # OCR исказил цифру дня («13 май» прочитано как «15 май»), берём дату большинства.
    by_clock = {}
    for r in stamped:
        by_clock.setdefault(r["stamp"][11:], []).append(r)
    for clock, group in by_clock.items():
        dates = Counter(r["stamp"][:10] for r in group)
        if len(dates) < 2:
            continue
        (major, major_n), (_second, second_n) = dates.most_common(2)
        if major_n >= 2 and major_n > second_n:
            for r in group:
                if r["stamp"][:10] != major:
                    r["stamp"] = f"{major} {clock}"
                    r["date_fixed"] = True
    today = datetime.now().strftime("%Y-%m-%d")
    top_date = Counter(r["stamp"][:10] for r in stamped).most_common(1)[0][0]
    for r in stamped:
        if r["stamp"][:10] == top_date:
            continue
        alt = alt_day_stamp(r["raw_date"])
        if alt and alt[:10] == top_date:
            r["stamp"] = alt
        elif r["stamp"][:10] == today and len(stamped) >= 2:
            r["stamp"] = None                       # похоже на подставленную системную дату
    good = [r for r in rows if r["stamp"]]
    if not good:
        return
    cnt = Counter(r["stamp"] for r in good)
    best = max(cnt.values())
    for r in rows:
        if r["stamp"]:
            continue
        src = min((g for g in good if cnt[g["stamp"]] == best),
                  key=lambda g: abs(g["line"] - r["line"]))
        r["stamp"], r["date_inherited"], r["no_date"] = src["stamp"], True, False


def fill_missing_rows(rows: list, arc_mode: bool = False) -> list:
    """OCR-ФИКС 6: полнота страницы. 1) Строка только со временем (название не прочитано —
    тёмные/фиолетовые строки вроде «Планер - Предвестник») получает название по цвету строки:
    золото — не угадывается (уйдёт в редактор), серый — повтор единственного «Потерянного
    фрагмента» страницы, иначе «Планер - Предвестник». 2) Если найдено 3–4 строки из 5: одной
    недостающей строке при единственном «Потерянном фрагменте» достраивается его дубль (второй
    такой же ряд Tesseract пропускает), в остальных случаях в редактор добавляются пустые
    строки-заглушки с общим временем страницы. Все достроенные строки помечаются для проверки."""
    for r in rows:
        if not r.get("missing"):
            continue
        if arc_mode:
            continue         # баннер дуг: «Планер» / «Фрагмент» не выпадают — строка уйдёт в редактор
        col = r["color"]
        if col == 5:
            continue                                     # S-ранг не угадываем
        lost = [x for x in rows if not x.get("missing") and hard_item_kind(x["body"]) == "lost_fragment"]
        if col == 3 and len(lost) == 1:
            r["body"], r["qty"] = lost[0]["body"], lost[0]["qty"]
            r["guess"], r["guess_note"] = True, "текст строки не прочитан: достроен повтор «Потерянного фрагмента»"
        else:
            r["body"], r["guess"] = "Планер - Предвестник", True
    n = len(rows)
    if not (OCR_PAGE_COMPLETE and 3 <= n < OCR_PAGE_SIZE):
        return rows
    stamps = [r["stamp"] for r in rows if r["stamp"]]
    batch = Counter(stamps).most_common(1)[0][0] if stamps else None
    lost = [r for r in rows if hard_item_kind(r["body"]) == "lost_fragment" and not r.get("guess")]
    missing = OCR_PAGE_SIZE - n
    note = f"достроена строка: на странице должно быть {OCR_PAGE_SIZE} записей, найдено {n}"
    if missing == 1 and len(lost) == 1 and not arc_mode:
        dup = dict(lost[0], line=lost[0]["line"] + 0.5, guess=True, conf=None, guess_note=note)
        rows.append(dup)
    else:
        last = max(r["line"] for r in rows)
        for k in range(missing):
            rows.append({"body": "", "qty": None, "stamp": batch, "raw_date": "", "color": None,
                         "bonus": False, "dice": False, "line": last + 0.5 * (k + 1),
                         "conf": None, "placeholder": True})
    rows.sort(key=lambda r: r["line"])
    return rows


def ocr_extract_pulls_ex(text: str, known: dict, line_ranks: list = None,
                         global_rank: int = None, default_loot: str = "character",
                         line_confs: list = None):
    """Разбирает весь текст скриншота и возвращает (список круток, число пропущенных строк,
    список нераспознанных строк). НОВОЕ: line_confs[i] — уверенность OCR строки i; у каждой
    записи появляются «line» (номер строки текста — место в раскладке скриншота), «conf»,
    «weak» (причины проверки) и «needs_review» (строку надо проверить глазами).

    Строки очищаются от служебного текста (clean_ocr_line) и разбираются по одной:
    каждая строка со словами — отдельная запись (название, ранг, тип, количество).
    Время берётся из самой строки; строка только со временем относится к предыдущей записи
    без времени («название / время» друг под другом), а если такой нет — к следующей
    («время / название»). line_ranks[i] — ранг по цвету рядом со строкой i (индексы — по
    строкам text); global_rank — ранг по цвету всего снимка, он используется только когда на
    снимке одна запись (в списке он не различает строки).
    Каждый элемент — словарь parse_ocr_result + «known» (имя есть в истории/составе) и
    «doubtful» (нет времени, имя неизвестно, а у других строк время есть — возможно, это
    мусор OCR; такие строки в списке не отмечаются). Порядок — как на скриншоте."""
    rows, pending = [], None

    def orphan(pd):
        """OCR-ФИКС 6: метка времени без названия — строка, текст которой OCR не прочитал."""
        st, rd, ln, col, cf, dc = pd
        rows.append({"body": "", "qty": None, "stamp": st, "raw_date": rd, "color": col,
                     "bonus": False, "dice": dc, "line": ln, "conf": cf, "missing": True})
    # OCR-ФИКС 4: служебная подсказка интерфейса вырезается ДО разбора строк (число строк и
    # их индексы не меняются — цвета рангов line_ranks остаются на своих местах)
    ui_lines = strip_ui_notes_lines((text or "").splitlines())
    for i, raw in enumerate(ui_lines):
        line = clean_ocr_line(raw)
        if not line:
            continue
        line, has_dice = prepare_ocr_row(line)      # единые правила для каждой строки
        if not line:
            continue
        # ИЗМЕНЕНО: название, количество и дата отделяются одной функцией (split_ocr_line),
        # поэтому дата и количество больше не попадают в название предмета
        part = split_ocr_line(line)
        stamp, body, qty, raw_date = part["stamp"], part["body"], part["qty"], part["raw_date"]
        # СТРОГО: бонусом считается только строка, в которой САМА есть «Подарок за очки»
        # (заголовок на соседней строке на следующие записи не влияет)
        bonus_here = bool(BONUS_MARK_RE.search(body))
        if not re.search(r"[^\W\d_]{2,}", body):       # строка только со временем
            if stamp:
                color_here = line_ranks[i] if line_ranks and i < len(line_ranks) else None
                if (color_here == 4 and default_loot != "arc"      # в таблице дуг «Планер» не гадаем
                        and not (rows and rows[-1]["stamp"] is None and not rows[-1]["qty"])
                        and not _next_row_lacks_stamp(ui_lines, i)):
                    rows.append({"body": "Планер - Предвестник", "qty": None, "stamp": stamp,
                                 "raw_date": raw_date, "color": color_here, "bonus": False,
                                 "dice": has_dice, "line": i,
                                 "conf": line_confs[i] if line_confs and i < len(line_confs)
                                 else None, "guess": True})
                elif rows and rows[-1]["stamp"] is None:
                    rows[-1]["stamp"], rows[-1]["raw_date"] = stamp, raw_date
                else:
                    if pending:
                        orphan(pending)
                    pending = (stamp, raw_date, i, color_here, 
                               line_confs[i] if line_confs and i < len(line_confs) else None,
                               has_dice)
            continue
        if stamp is None and pending:
            (stamp, raw_date), pending = pending[:2], None
        elif pending and stamp:
            orphan(pending)
            pending = None
        color = line_ranks[i] if line_ranks and i < len(line_ranks) else None
        conf = line_confs[i] if line_confs and i < len(line_confs) else None
        rows.append({"body": body, "qty": qty, "stamp": stamp, "raw_date": raw_date,
                     "color": color, "bonus": bonus_here, "dice": has_dice,
                     "line": i, "conf": conf})
    if pending:
        orphan(pending)
    rows.sort(key=lambda r: r["line"])
    rows = rows[:OCR_MAX_ROWS]
    # OCR-ФИКС 4: ЧИСТЫЙ пакет. Если на снимке есть таблица (хотя бы у одной строки найдена
    # дата), то настоящая запись — это строка с названием И датой. Строки без даты (остатки
    # заголовков, подсказок, мусор OCR) в список предпросмотра не попадают. Если дат нет
    # вообще (текст набран вручную), строки разбираются как раньше.
    dropped = 0
    if any(r["stamp"] or r["raw_date"] for r in rows):
        # ИСПРАВЛЕНО: раньше строка без прочитанной даты отбрасывалась всегда — так пропадали
        # настоящие записи («Дуга - Настоящая музыка», «Дуга - Опасная игра», персонажи), у
        # которых OCR испортил дату. Теперь без даты остаются строки с РАСПОЗНАННЫМ названием
        # (явный префикс «Дуга - …» / «Персонаж: …» или совпадение с мастер-справочником):
        # они попадают в список с пометкой «время не найдено». Мусор без названия отбрасывается.
        valid = []
        for r in rows:
            if r["stamp"] or r["raw_date"]:
                valid.append(r)
            elif _is_recognized_row(r["body"]):
                r["no_date"] = True
                valid.append(r)
        dropped, rows = len(rows) - len(valid), valid
        # OCR-ФИКС 6: одна страница = одна крутка: общая дата и достройка недостающих строк
        inherit_page_dates(rows)
        rows = fill_missing_rows(rows, arc_mode=(default_loot == "arc"))
        inherit_page_dates(rows)               # у достроенных строк время тоже общее

    timed = sum(1 for r in rows if r["stamp"])
    out, skipped_rows = [], []
    for r in rows:
        body, qty = r["body"], r["qty"]
        body, letter = _split_row_rank(_trim_edge_junk(body))
        # OCR-ФИКС 7: «Страна сна» — признак «вне гаранта»; фраза вырезается из названия
        sna = bool(STRANA_SNA_RE.search(body))
        if sna:
            body = re.sub(r"\s+", " ", STRANA_SNA_RE.sub(" ", body)).strip(" -–—:|") or body
        raw_body, fallbacks = body, []     # прочитанное название и запасные правила (для проверки)
        raw = body + (f" Ранг {letter}" if letter else "") + (f" ×{qty}" if qty else "")
        color = r["color"] or (global_rank if len(rows) == 1 else None)
        # НОВОЕ: МАСТЕР-СПРАВОЧНИК. Если в строке есть эталонное название (персонаж, дуга,
        # планер, костюм, предмет) — вся строка заменяется чистым каноническим названием:
        # мусор OCR, номера и «Подарок за очки» вокруг исчезают (бонус уже запомнен в r["bonus"]).
        # Один и тот же шаг работает на всех трёх вкладках со скриншотами.
        arc_mode = default_loot == "arc"       # баннер дуг: персонажи, костюмы, планеры не выпадают
        # ИСПРАВЛЕНО: в таблице бросков («Эксклюзивная доска») персонажи и дуги идут вперемешку, а
        # выбран может быть баннер «Дуги»: «Персонаж - Минт» превращался в «Дуга - Минт». Цветная
        # строка (персонажи — фиолетовые / золотые, серые — всегда дуги), которая точно совпала с
        # персонажем / планером / костюмом из справочника, остаётся самим собой.
        if arc_mode and color in (4, 5):
            _cand = strip_arc_blocked_prefix(body)
            _mm = master_match(_cand)
            if (_mm and _mm.get("category") in ("character", "glider", "outfit")
                    and _mm["score"] >= 0.85):
                arc_mode = False
        if arc_mode:
            body = strip_arc_blocked_prefix(body)
        hard_kind = hard_item_kind(body)       # OCR-ФИКС 6: ключевые слова предметов
        master = None if hard_kind else master_match(body, arc_only=arc_mode)
        # ИСПРАВЛЕНО: серая строка (ранг B по цвету) — не персонаж A/S: персонажи всегда фиолетовые
        # или золотые. Нечёткое совпадение такой строки с персонажем («Мы.» -> «Минт») отбрасывается,
        # иначе жёсткий ранг персонажа перекрывал цвет и дуга превращалась в персонажа.
        if (master and master.get("category") == "character" and color == 3
                and master["score"] < 1.0 and leading_type(body) != "character"):
            master = None
        # ИСПРАВЛЕНО: обычный поиск не нашёл название (искажённая строка с цветной обводкой) —
        # ищем среди названий ТОЛЬКО нужного типа (префикс строки) и ранга (цвет текста)
        if master is None and not hard_kind:
            master = constrained_master_match(body, color, arc_only=arc_mode)
            if master:
                fallbacks.append("название подобрано по типу и рангу строки")
        if master:
            body, raw_body = master["label"], master["matched"]
            if master["score"] < 1.0:
                fallbacks.append("название исправлено по мастер-справочнику")
            if master["rank"] and not letter:         # ранг из master_names.json
                letter = RANK_LETTERS[master["rank"]]
            if master.get("qty_options") and qty not in master["qty_options"]:
                qty = master["qty_default"]
            if master.get("force_rank"):              # жёсткое правило (планер — всегда A)
                color, letter = None, RANK_LETTERS[master["force_rank"]]
            raw = body + (f" Ранг {letter}" if letter else "") + (f" ×{qty}" if qty else "")
        # НОВОЕ: словари исправлений (фрагменты, имена персонажей) — единый шаг для обеих вкладок
        fixed = None if (master or hard_kind or arc_mode) else apply_ocr_corrections(body, qty, known)
        if fixed:
            body = fixed
            fallbacks.append("название исправлено по словарю")
            raw = body + (f" Ранг {letter}" if letter else "") + (f" ×{qty}" if qty else "")
        # OCR-ФИКС 2: искажённый предмет («: Прут Фочеарякитый Фрезия 50») жёстко становится
        # «Предмет - Потерянный фрагмент» и никогда не попадает в персонажи
        forced = (f"Предмет - {REWARD_KINDS[hard_kind]}" if hard_kind
                  else forced_item_label(body, qty, known))
        if forced:
            if not (hard_kind and _loot_from_text(strip_leading_junk(body))):
                fallbacks.append("предмет определён по запасному правилу")
            raw = forced + (f" ×{qty}" if qty else "") + (f" Ранг {letter}" if letter else "")
        p = parse_ocr_result(raw, known, color_rank=color, bonus=r["bonus"],
                             default_loot=default_loot, dice_icon=r["dice"])
        # OCR-ФИКС («страховка»): у записи таблицы есть и дата, и количество, а тип не
        # определился (например, «Предмет» с искажённым названием) — пробуем узнать предмет
        # по самому мягкому порогу, а не терять строку
        if not p["loot"] and r["stamp"] and qty and not r["bonus"]:
            label = recover_item_loot(body)
            if label:
                fallbacks.append("предмет угадан по мягкому порогу")
                p = parse_ocr_result(f"{label} ×{qty}", known, color_rank=color,
                                     bonus=r["bonus"], default_loot=default_loot)
        # баннер дуг: что бы ни определилось (персонаж, костюм, планер, окраска, скин) — это
        # не может выпасть; строка переразбирается как дуга по очищенному названию
        if arc_mode and p["loot"] in ARC_BANNER_BLOCKED_LOOT:
            alt = strip_arc_blocked_prefix(r["body"])
            fallbacks.append("в баннере дуг персонажи, костюмы и планеры не выпадают")
            p = parse_ocr_result(f"{DUGA_PREFIX}{alt}" + (f" Ранг {letter}" if letter else ""),
                                 known, color_rank=color, bonus=r["bonus"],
                                 default_loot="arc", dice_icon=r["dice"])
            if p["loot"] in ARC_BANNER_BLOCKED_LOOT:
                p["loot"] = None
        # OCR-ФИКС 3: последний рубеж — мусорная строка с количеством 30 / 50 или ключевым
        # словом фрагмента НЕ может остаться персонажем / дугой: переразбираем как предмет
        if p["loot"] in ("character", "arc") and not r["bonus"] and not p["is_bonus"]:
            fkey = strict_fragment_key(body, qty, known)
            if fkey:
                fallbacks.append("материал определён по запасному правилу")
                p = parse_ocr_result(f"Предмет - {REWARD_KINDS[fkey]}"
                                     + (f" ×{qty}" if qty else "")
                                     + (f" Ранг {letter}" if letter else ""),
                                     known, color_rank=color, default_loot=default_loot)
        if not p["loot"] or (p["name"] and len(p["name"]) < 2):
            # не крутка (или мусор OCR): строка уходит в «Редактор нераспознанных строк»
            skipped_rows.append({"line": r["line"], "body": r["body"], "qty": r["qty"],
                                 "stamp": r["stamp"], "raw_date": r["raw_date"],
                                 "conf": r["conf"], "bonus": r["bonus"], "color": r["color"]})
            continue
        if r["stamp"]:
            p["timestamp"] = QDateTime.fromString(r["stamp"], QT_DATE_FMT)
            p["has_time"] = True
        # НОВОЕ: сырая дата и количество со снимка — для подсказок в списке и отладки
        p["raw_date"], p["amount"] = r["raw_date"], qty
        # имена из состава персонажей тоже считаются «известными»
        p["known"] = (p["name"].lower() in known or p["name"].lower() in ROSTER_KNOWN
                      or p["name"].lower() in ARC_KNOWN or p["name"].lower() in OUTFIT_KNOWN)
        p["doubtful"] = (not p["known"] and not p["has_time"] and timed >= 2
                         and p["loot"] in ("character", "arc"))
        # НОВОЕ: оценка надёжности строки — уверенность OCR, запасные правила, нечёткое сходство
        conf, reasons = r["conf"], []
        if conf is not None and conf < OCR_REVIEW_CONF:
            reasons.append(f"низкая уверенность OCR: {conf:.0f}%")
        if fallbacks and (conf is None or conf < OCR_FALLBACK_CONF):
            reasons.append(fallbacks[0])
        sim = master["score"] if master else _name_similarity(raw_body, p)
        if sim is not None and sim < FUZZY_REVIEW_SIM:
            reasons.append(f"нечёткое совпадение названия: {sim:.0%}")
        if p["doubtful"]:
            reasons.append("нет времени, имя неизвестно")
        if r.get("guess"):
            reasons.append(r.get("guess_note")
                           or "текст строки не прочитан: планер определён по цвету строки")
        if r.get("date_fixed"):
            reasons.append("дата исправлена по соседним строкам с тем же временем")
        if r.get("no_date") and not p["has_time"]:
            reasons.append("время не найдено — проверьте дату")
        if sna and LOOT_TYPES[p["loot"]]["mode"] == "wish":
            p["is_bonus"] = True                  # крутка (персонаж/дуга) вне гаранта
            p["type_text"] = f"{BONUS_TYPE_PREFIX} - {p['type_text']}"
        p["no_pity"] = bool(sna or p["is_bonus"])
        p.update(line=r["line"], conf=conf, weak=reasons, needs_review=bool(reasons),
                 body_raw=r["body"])
        out.append(p)
    return out, len(rows) - len(out) + dropped, skipped_rows


def _name_similarity(raw_body: str, p: dict):
    """НОВОЕ: сходство (0..1) прочитанного названия с итоговым — чем меньше, тем сильнее OCR
    «исправили» словарём / нечётким поиском. None — сравнивать нечего. Название предметов без
    имени (кубики, фрагменты) сравнивается с названием вида («Потерянный фрагмент»)."""
    info = LOOT_TYPES.get(p.get("loot"))
    if info is None:
        return None
    if info.get("hide_name") and info.get("kind") in REWARD_KINDS:
        target = REWARD_KINDS[info["kind"]]
    else:
        target = strip_labels(p.get("name") or "")
    raw = strip_labels(clean_name(strip_leading_junk(raw_body or "")))
    if not raw or not target:
        return None
    a, b = fold_name(raw), fold_name(target)
    if not a or not b:
        return None
    return 1.0 if a == b else difflib.SequenceMatcher(None, a, b).ratio()


def ocr_candidates(text: str, known: dict, line_ranks: list = None,
                   global_rank: int = None) -> list:
    """Совместимая обёртка: список разобранных круток скриншота (см. ocr_extract_pulls)."""
    return ocr_extract_pulls(text, known, line_ranks, global_rank)[0]


def bottom_to_top_order(pulls: list) -> list:
    """Порядок записи пакета в базу: СНИЗУ ВВЕРХ (от старых к новым).

    ИСПРАВЛЕНО. В истории игры самая верхняя строка выпала ПОЗЖЕ всех (новейшая), самая
    нижняя — РАНЬШЕ всех (старейшая). Чтобы временная линия и счёт гаранта были верными,
    старые записи должны попасть в базу первыми, а новые — последними, поэтому список
    строк скриншота просто разворачивается: идём с последней строки к первой.

    Порядок НЕ зависит от распознанных времён: у десятикратного броска все записи имеют
    одно и то же время, и только позиция строки на скриншоте различает их. Исходный список
    не меняется — возвращается новая копия."""
    return list(reversed(pulls))


# ----------------------------------------------------------------------------
# База данных
# ----------------------------------------------------------------------------
def _wish_key(r: dict) -> tuple:
    return (r["banner"], r["rarity"], r["name"], r["pulled_at"], int(r.get("is_bonus", 0)),
            r.get("arc_kind", "") or "", r.get("cashback", "") or "")


def _reward_key(r: dict) -> tuple:
    # имя берём через reward_display_name, чтобы старые записи с пустым именем
    # корректно сравнивались с новыми (у которых имя по умолчанию заполнено)
    return (r["kind"], reward_display_name(r), r["detail"], r["obtained_at"],
            r.get("banner", "") or "")


def enforce_bonus_rules(rec: dict) -> dict:
    """НОВОЕ: правила бонусной добычи на уровне базы. Запись с is_bonus=1 всегда ранга A,
    без типа S дуги и без кешбэка — иначе она могла бы попасть в статистику S или
    сломать гарант. Обычные записи возвращаются без изменений."""
    if not rec.get("is_bonus"):
        return rec
    return dict(rec, rarity=4, arc_kind="", cashback="")


def _insert_sql(table: str, cols: tuple) -> str:
    return (f"INSERT INTO {table} ({', '.join(cols)}) "
            f"VALUES ({', '.join(':' + c for c in cols)})")


class Database:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.conn = None
        self.profile_id = 0   # НОВОЕ: id активного профиля (0 — профилей ещё нет)
        try:
            self.conn = sqlite3.connect(str(self.path))
            self.conn.row_factory = sqlite3.Row
            self._init_schema()
            self.load_active()
        except sqlite3.Error as e:
            if self.conn:
                self.conn.close()
                self.conn = None
            raise DatabaseError(f"Не удалось открыть базу данных:\n{self.path}\n\n{e}") from e

    def _ensure_columns(self, table: str, columns: dict):
        have = {r[1] for r in self.conn.execute(f"PRAGMA table_info({table})")}
        for col, ddl in columns.items():
            if col not in have:
                self.conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {ddl}")

    def _init_schema(self):
        """Создаёт таблицы и мигрирует старые базы.
        Старые столбцы (например, «featured») остаются нетронутыми."""
        with self.conn:
            run = self.conn.execute
            run("""CREATE TABLE IF NOT EXISTS wishes (
                       id INTEGER PRIMARY KEY AUTOINCREMENT,
                       banner TEXT NOT NULL,
                       rarity TEXT NOT NULL,
                       name TEXT NOT NULL,
                       pulled_at TEXT NOT NULL,
                       is_bonus INTEGER NOT NULL DEFAULT 0,
                       arc_kind TEXT NOT NULL DEFAULT '',
                       cashback TEXT NOT NULL DEFAULT ''
                   )""")
            run("""CREATE TABLE IF NOT EXISTS rewards (
                       id INTEGER PRIMARY KEY AUTOINCREMENT,
                       kind TEXT NOT NULL,
                       name TEXT NOT NULL DEFAULT '',
                       detail TEXT NOT NULL DEFAULT '',
                       obtained_at TEXT NOT NULL,
                       banner TEXT NOT NULL DEFAULT '',
                       no_pity INTEGER NOT NULL DEFAULT 0
                   )""")
            run("CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
            run("""CREATE TABLE IF NOT EXISTS profiles (
                       id INTEGER PRIMARY KEY AUTOINCREMENT,
                       name TEXT NOT NULL,
                       created_at TEXT NOT NULL DEFAULT ''
                   )""")
            self._ensure_columns("wishes", {"is_bonus": "INTEGER NOT NULL DEFAULT 0",
                                            "arc_kind": "TEXT NOT NULL DEFAULT ''",
                                            "cashback": "TEXT NOT NULL DEFAULT ''"})
            self._ensure_columns("rewards", {"banner": "TEXT NOT NULL DEFAULT ''",
                                             "no_pity": "INTEGER NOT NULL DEFAULT 0",
                                             "rarity": "TEXT NOT NULL DEFAULT ''"})  # OCR-ФИКС
            # НОВОЕ: seq — порядковый номер записи внутри пакетного импорта. Нужен, чтобы
            # крутки и предметы с ОДНИМ временем (десятикратный бросок) сохраняли порядок
            # скриншота: они лежат в разных таблицах, и по id их не сравнить. У старых и
            # вручную добавленных записей seq = 0 — их порядок не меняется.
            self._ensure_columns("wishes", {"seq": "INTEGER NOT NULL DEFAULT 0"})
            self._ensure_columns("rewards", {"seq": "INTEGER NOT NULL DEFAULT 0"})
            # НОВОЕ: batch_id — номер пакетного импорта (0 — запись не из пакета). Нужен для
            # кнопки «Отменить последний импорт».
            self._ensure_columns("wishes", {"batch_id": "INTEGER NOT NULL DEFAULT 0"})
            self._ensure_columns("rewards", {"batch_id": "INTEGER NOT NULL DEFAULT 0"})
            # НОВОЕ: profile_id — владелец записи. 0 — запись из старой базы без профилей:
            # её получает первый созданный профиль (см. create_profile).
            self._ensure_columns("wishes", {"profile_id": "INTEGER NOT NULL DEFAULT 0"})
            self._ensure_columns("rewards", {"profile_id": "INTEGER NOT NULL DEFAULT 0"})
            # Миграция рангов: старые числа 5/4/3 -> буквы S/A/B (выполняется один раз,
            # затрагивает только строки, где ранг ещё хранится числом)
            run("""UPDATE wishes SET rarity = CASE rarity WHEN 5 THEN 'S' WHEN 4 THEN 'A'
                                                       WHEN 3 THEN 'B' END
                   WHERE typeof(rarity) = 'integer' AND rarity IN (3, 4, 5)""")
            for table in ("wishes", "rewards"):  # перенос старых ключей баннеров
                for old, new in LEGACY_BANNERS.items():
                    run(f"UPDATE {table} SET banner = ? WHERE banner = ?", (new, old))
            # переименование персонажей: «Акане» -> «Аканэ Рин» (записи, привязки предметов)
            run("UPDATE wishes SET name = ? WHERE name = ?", ("Аканэ Рин", "Акане"))
            run("UPDATE rewards SET detail = ? WHERE detail = ? AND kind IN ('outfit', 'glider', 'paint')",
                ("Аканэ Рин", "Акане"))
            run("CREATE INDEX IF NOT EXISTS idx_wishes_time ON wishes(pulled_at, id)")
            run("CREATE INDEX IF NOT EXISTS idx_rewards_time ON rewards(obtained_at, id)")
            run("CREATE INDEX IF NOT EXISTS idx_wishes_profile ON wishes(profile_id, pulled_at, id)")
            run("CREATE INDEX IF NOT EXISTS idx_rewards_profile ON rewards(profile_id, obtained_at, id)")

    def close(self):
        if self.conn:
            self.conn.close()
            self.conn = None

    # ---------- общие операции ----------
    def _select(self, sql: str, params=(), err: str = "Ошибка чтения базы данных") -> list:
        try:
            return [dict(r) for r in self.conn.execute(sql, params).fetchall()]
        except sqlite3.Error as e:
            raise DatabaseError(f"{err}:\n{e}") from e

    def _write(self, sql: str, seq=None, err: str = "Ошибка записи в базу данных") -> None:
        try:
            with self.conn:
                if seq is None:
                    self.conn.execute(sql)
                else:
                    self.conn.executemany(sql, seq)
        except sqlite3.Error as e:
            raise DatabaseError(f"{err}:\n{e}") from e

    @staticmethod
    def _new_only(records: list, existing: list, key) -> list:
        """Записи, которых ещё нет в базе (с учётом количества одинаковых копий)."""
        have, seen, out = Counter(map(key, existing)), Counter(), []
        for r in records:
            k = key(r)
            seen[k] += 1
            if seen[k] > have[k]:
                out.append(r)
        return out

    # ---------- настройки (запоминание введённого времени и т.п.) ----------
    def _scoped_key(self, key: str) -> str:
        """Ключ настройки, привязанный к активному профилю."""
        return f"p{self.profile_id}:{key}"

    def get_setting(self, key: str, default=None, scoped: bool = False):
        """scoped=True — настройка принадлежит активному профилю (время формы, отметки баннеров)."""
        if scoped:
            key = self._scoped_key(key)
        try:
            row = self.conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
            return row["value"] if row else default
        except sqlite3.Error:
            return default

    def set_setting(self, key: str, value: str, scoped: bool = False) -> bool:
        if scoped:
            key = self._scoped_key(key)
        try:
            self._write("INSERT INTO settings (key, value) VALUES (?, ?) "
                        "ON CONFLICT(key) DO UPDATE SET value = excluded.value", [(key, value)])
            return True
        except DatabaseError:
            return False

    # ---------- НОВОЕ: профили ----------
    def list_profiles(self) -> list:
        """Все профили (по порядку создания) с числом круток и предметов в каждом."""
        return self._select(
            "SELECT p.id, p.name, "
            "(SELECT COUNT(*) FROM wishes w WHERE w.profile_id = p.id) AS wishes_n, "
            "(SELECT COUNT(*) FROM rewards r WHERE r.profile_id = p.id) AS rewards_n "
            "FROM profiles p ORDER BY p.id ASC", err="Ошибка чтения профилей")

    def profile_count(self) -> int:
        try:
            return int(self.conn.execute("SELECT COUNT(*) FROM profiles").fetchone()[0])
        except sqlite3.Error:
            return 0

    def active_profile(self):
        for prof in self.list_profiles():
            if prof["id"] == self.profile_id:
                return prof
        return None

    def check_profile_name(self, name: str, exclude_id=None) -> str:
        """Проверяет никнейм и возвращает его в чистом виде; иначе DatabaseError."""
        clean = " ".join(str(name or "").split())
        if not clean:
            raise DatabaseError("Никнейм не может быть пустым.")
        if len(clean) > PROFILE_NAME_MAX:
            raise DatabaseError(f"Никнейм слишком длинный (не более {PROFILE_NAME_MAX} символов).")
        for prof in self.list_profiles():
            if prof["id"] != exclude_id and prof["name"].casefold() == clean.casefold():
                raise DatabaseError("Профиль с таким никнеймом уже существует.")
        return clean

    def create_profile(self, name: str) -> int:
        """Создаёт профиль. Если это первый профиль — он забирает все старые записи
        (profile_id = 0) и сохранённые настройки времени формы / отметки баннеров.
        Если активного профиля ещё нет, новый становится активным."""
        clean = self.check_profile_name(name)
        first = self.profile_count() == 0
        try:
            with self.conn:
                cur = self.conn.execute("INSERT INTO profiles (name, created_at) VALUES (?, ?)",
                                        (clean, datetime.now().strftime(DATE_FMT)))
                pid = int(cur.lastrowid)
                if first:
                    self.conn.execute("UPDATE wishes SET profile_id = ? WHERE profile_id = 0", (pid,))
                    self.conn.execute("UPDATE rewards SET profile_id = ? WHERE profile_id = 0", (pid,))
                    prefix = f"p{pid}:"
                    self.conn.execute(
                        "INSERT OR IGNORE INTO settings (key, value) "
                        "SELECT ? || key, value FROM settings WHERE key = ? "
                        "OR substr(key, 1, ?) = ?",
                        (prefix, TIME_SETTING_KEY, len(BANNER_ACTIVATED_PREFIX),
                         BANNER_ACTIVATED_PREFIX))
        except sqlite3.Error as e:
            raise DatabaseError(f"Не удалось создать профиль:\n{e}") from e
        if self.profile_id == 0:
            self.set_active_profile(pid)
        return pid

    def rename_profile(self, pid: int, name: str) -> str:
        clean = self.check_profile_name(name, exclude_id=pid)
        self._write("UPDATE profiles SET name = ? WHERE id = ?", [(clean, pid)],
                    "Не удалось переименовать профиль")
        return clean

    def delete_profile(self, pid: int) -> None:
        """Удаляет профиль вместе с его крутками, предметами и настройками. Последний
        оставшийся профиль удалить нельзя. Если удалён активный — активным становится первый."""
        ids = [p["id"] for p in self.list_profiles()]
        if pid not in ids:
            raise DatabaseError("Профиль не найден.")
        if len(ids) <= 1:
            raise DatabaseError("Нельзя удалить единственный профиль.")
        try:
            with self.conn:
                self.conn.execute("DELETE FROM wishes WHERE profile_id = ?", (pid,))
                self.conn.execute("DELETE FROM rewards WHERE profile_id = ?", (pid,))
                prefix = f"p{pid}:"
                self.conn.execute("DELETE FROM settings WHERE substr(key, 1, ?) = ?",
                                  (len(prefix), prefix))
                self.conn.execute("DELETE FROM profiles WHERE id = ?", (pid,))
        except sqlite3.Error as e:
            raise DatabaseError(f"Не удалось удалить профиль:\n{e}") from e
        if self.profile_id == pid:
            self.set_active_profile(next(i for i in ids if i != pid))

    def set_active_profile(self, pid: int) -> None:
        if pid not in [p["id"] for p in self.list_profiles()]:
            raise DatabaseError("Профиль не найден.")
        self.profile_id = pid
        self.set_setting(ACTIVE_PROFILE_KEY, str(pid))

    def load_active(self) -> None:
        """Определяет активный профиль по сохранённой настройке (иначе — первый профиль)."""
        try:
            ids = [r[0] for r in self.conn.execute("SELECT id FROM profiles ORDER BY id ASC")]
        except sqlite3.Error:
            ids = []
        try:
            pid = int(self.get_setting(ACTIVE_PROFILE_KEY))
        except (TypeError, ValueError):
            pid = 0
        if pid not in ids:
            pid = ids[0] if ids else 0
        self.profile_id = pid
        if pid and self.get_setting(ACTIVE_PROFILE_KEY) != str(pid):
            self.set_setting(ACTIVE_PROFILE_KEY, str(pid))

    # ---------- крутки (включая кешбэк и бонусы) ----------
    def fetch_all(self) -> list:
        """Все крутки в хронологическом порядке (старые первыми).
        Записи удалённого баннера «Новичковый» не возвращаются."""
        marks = ",".join("?" for _ in BANNERS)
        rows = self._select(
            f"SELECT id, seq, {', '.join(WISH_COLS)} FROM wishes "
            f"WHERE profile_id = ? AND banner IN ({marks}) "
            "ORDER BY pulled_at ASC, seq ASC, id ASC", (self.profile_id,) + tuple(BANNERS))
        for r in rows:  # в базе буква S/A/B, в программе — числовой ранг 5/4/3
            r["rarity"] = rank_from_db(r["rarity"])
        return rows

    def add_many(self, records: list) -> int:
        # числовой ранг -> буква S/A/B перед записью в базу
        rows = [dict(enforce_bonus_rules(r), rarity=RANK_LETTERS[enforce_bonus_rules(r)["rarity"]],
                     profile_id=self.profile_id) for r in records]
        self._write(_insert_sql("wishes", WISH_COLS + ("profile_id",)), rows)
        return len(records)

    def import_records(self, records: list):
        """Добавляет записи, пропуская существующие. Возвращает (добавлено, пропущено)."""
        to_add = self._new_only(records, self.fetch_all(), _wish_key)
        added = self.add_many(to_add) if to_add else 0
        return added, len(records) - added

    def delete_ids(self, ids: list) -> None:
        self._write("DELETE FROM wishes WHERE id = ? AND profile_id = ?",
                    [(i, self.profile_id) for i in ids], "Ошибка удаления")

    def clear_all(self) -> None:
        self._write("DELETE FROM wishes WHERE profile_id = ?", [(self.profile_id,)],
                    err="Ошибка очистки базы данных")

    # ---------- предметы (кубики, костюмы, планеры, скины) ----------
    def fetch_rewards(self) -> list:
        return self._select(
            f"SELECT id, seq, {', '.join(REWARD_COLS)} FROM rewards WHERE profile_id = ? "
            "ORDER BY obtained_at ASC, seq ASC, id ASC", (self.profile_id,),
            err="Ошибка чтения наград")

    def add_rewards(self, records: list) -> int:
        self._write(_insert_sql("rewards", REWARD_COLS + ("profile_id",)),
                    [dict(_reward_row(r), profile_id=self.profile_id) for r in records],
                    "Ошибка записи награды")
        return len(records)

    def import_rewards(self, records: list):
        to_add = self._new_only(records, self.fetch_rewards(), _reward_key)
        added = self.add_rewards(to_add) if to_add else 0
        return added, len(records) - added

    def import_batch(self, wishes: list, rewards: list):
        """Пакетное добавление круток и предметов ОДНОЙ транзакцией — либо записывается
        всё, либо (при ошибке) ничего.

        ИСПРАВЛЕНО: фильтр дубликатов убран. В игре несколько круток и наград могут выпасть в
        одну и ту же секунду, поэтому записи с одинаковым названием, типом и временем — разные
        записи, и в базу попадают ВСЕ переданные строки (раньше совпадающие с уже имеющимися
        молча отбрасывались через _new_only).

        Порядок: wishes и rewards приходят в порядке записи (bottom_to_top_order — старые
        первыми); относительный номер rec["seq"] сохраняет это чередование. Возвращает
        (круток добавлено, предметов добавлено)."""
        try:
            with self.conn:
                # Номера seq выдаются ПОСЛЕ всех существующих: при одинаковом времени
                # записи пакета идут после прежних, а между собой — в порядке пакета.
                base = 1 + max(
                    self.conn.execute("SELECT COALESCE(MAX(seq), 0) FROM wishes").fetchone()[0],
                    self.conn.execute("SELECT COALESCE(MAX(seq), 0) FROM rewards").fetchone()[0])
                batch = 1 + max(
                    self.conn.execute("SELECT COALESCE(MAX(batch_id), 0) FROM wishes").fetchone()[0],
                    self.conn.execute("SELECT COALESCE(MAX(batch_id), 0) FROM rewards").fetchone()[0])
                if wishes:
                    self.conn.executemany(
                        _insert_sql("wishes", WISH_COLS + ("seq", "batch_id", "profile_id")),
                        [dict(enforce_bonus_rules(r),
                              rarity=RANK_LETTERS[enforce_bonus_rules(r)["rarity"]],
                              seq=base + int(r.get("seq", 0)), batch_id=batch,
                              profile_id=self.profile_id)
                         for r in wishes])
                if rewards:
                    self.conn.executemany(
                        _insert_sql("rewards", REWARD_COLS + ("seq", "batch_id", "profile_id")),
                        [dict(_reward_row(r), seq=base + int(r.get("seq", 0)), batch_id=batch,
                              profile_id=self.profile_id)
                         for r in rewards])
        except sqlite3.Error as e:
            raise DatabaseError(f"Ошибка пакетной записи:\n{e}") from e
        return len(wishes), len(rewards)

    def last_batch_id(self) -> int:
        """Номер последнего пакетного импорта, записи которого ещё есть в базе (0 — нет)."""
        try:
            pid = (self.profile_id,)
            return int(max(
                self.conn.execute("SELECT COALESCE(MAX(batch_id), 0) FROM wishes "
                                  "WHERE profile_id = ?", pid).fetchone()[0],
                self.conn.execute("SELECT COALESCE(MAX(batch_id), 0) FROM rewards "
                                  "WHERE profile_id = ?", pid).fetchone()[0]))
        except sqlite3.Error:
            return 0

    def batch_counts(self, batch_id: int) -> tuple:
        """(круток, предметов) в пакетном импорте batch_id."""
        try:
            return (self.conn.execute("SELECT COUNT(*) FROM wishes "
                                      "WHERE batch_id = ? AND profile_id = ?",
                                      (batch_id, self.profile_id)).fetchone()[0],
                    self.conn.execute("SELECT COUNT(*) FROM rewards "
                                      "WHERE batch_id = ? AND profile_id = ?",
                                      (batch_id, self.profile_id)).fetchone()[0])
        except sqlite3.Error:
            return (0, 0)

    def delete_batch(self, batch_id: int) -> tuple:
        """Удаляет все записи пакетного импорта одной транзакцией. Возвращает (круток, предметов)."""
        counts = self.batch_counts(batch_id)
        try:
            with self.conn:
                self.conn.execute("DELETE FROM wishes WHERE batch_id = ? AND profile_id = ?",
                                  (batch_id, self.profile_id))
                self.conn.execute("DELETE FROM rewards WHERE batch_id = ? AND profile_id = ?",
                                  (batch_id, self.profile_id))
        except sqlite3.Error as e:
            raise DatabaseError(f"Ошибка отмены импорта:\n{e}") from e
        return counts

    def delete_reward_ids(self, ids: list) -> None:
        self._write("DELETE FROM rewards WHERE id = ? AND profile_id = ?",
                    [(i, self.profile_id) for i in ids], "Ошибка удаления")

    def clear_rewards(self) -> None:
        self._write("DELETE FROM rewards WHERE profile_id = ?", [(self.profile_id,)],
                    err="Ошибка очистки наград")

    # ---------- резервные копии ----------
    def backup_to(self, dst_path: str) -> None:
        if Path(dst_path).resolve() == self.path.resolve():
            raise DatabaseError("Нельзя сохранить копию поверх рабочей базы.")
        dst = None
        try:
            dst = sqlite3.connect(dst_path)
            self.conn.backup(dst)
        except sqlite3.Error as e:
            raise DatabaseError(f"Не удалось создать резервную копию:\n{e}") from e
        finally:
            if dst:
                dst.close()

    def restore_from(self, src_path: str) -> None:
        if Path(src_path).resolve() == self.path.resolve():
            raise DatabaseError("Выбран файл текущей базы данных.")
        src = None
        try:
            src = sqlite3.connect(src_path)
            cols = {r[1] for r in src.execute("PRAGMA table_info(wishes)")}
            if not {"banner", "rarity", "name", "pulled_at"} <= cols:
                raise DatabaseError("Выбранный файл не является базой NTE Wish Tracker.")
            src.backup(self.conn)
            self.conn.row_factory = sqlite3.Row
            self._init_schema()  # миграция копий из старых версий
            self.load_active()   # НОВОЕ: активный профиль берётся из восстановленной базы
        except sqlite3.Error as e:
            raise DatabaseError(f"Не удалось восстановить базу данных:\n{e}") from e
        finally:
            if src:
                src.close()


# ----------------------------------------------------------------------------
# Статистика и история
# ----------------------------------------------------------------------------
def build_timeline(rows: list, rewards: list) -> list:
    """Единая хронология круток и предметов (старые первыми). Предметы приводятся
    к тому же виду, что и крутки; src отличает источник ("wish" / "reward").
    ИЗМЕНЕНО: у предметов добавлено поле aliases — синонимы для поиска иконки
    (тип предмета и его название)."""
    events = [dict(r, src="wish") for r in rows]
    events += [dict(r, src="reward", rarity=reward_rarity(r), name=reward_display_name(r),
                    pulled_at=r["obtained_at"], is_bonus=0, arc_kind="", cashback="",
                    aliases=(r["kind"], REWARD_KINDS.get(r["kind"], "")))
               for r in rewards]
    # ИСПРАВЛЕНО: при одинаковом времени порядок задаёт seq (номер в пакетном импорте), и
    # только потом — старое правило (предметы раньше круток, затем id)
    events.sort(key=lambda e: (e["pulled_at"], e.get("seq", 0), e["src"] == "wish", e["id"]))
    return events


def _blank_stats() -> dict:
    return {"total": 0, "r3": 0, "r4": 0, "r5": 0, "bonus": 0,
            "counter": 0, "counter_std": 0, "counter_ev": 0,
            "pities": [], "last5": None, "last4": None,
            "items": Counter(), "qty": Counter(), "cash": Counter()}


def _count_item(s: dict, e: dict):
    """Учёт предмета в сводке пула. items — число записей по типам, qty — суммарное
    количество (кубики, фрагменты), cash — кешбэк. Считается всегда, в том числе для
    предметов вне гаранта."""
    if e["src"] == "reward":
        if e["kind"] == "cashback":
            s["cash"][e["detail"]] += 1
        else:
            s["items"][e["kind"]] += 1
            if e["kind"] in QTY_OPTIONS:
                s["qty"][e["kind"]] += _safe_int(e["detail"])
    elif e["cashback"]:
        s["cash"][e["cashback"]] += 1


def is_non_pity_event(e: dict) -> bool:
    """OCR-ФИКС 7: запись вне гаранта: бонус («Подарок за очки»), предмет с флагом no_pity
    («Страна сна» — фрагмент искривления) либо старая запись, в названии которой есть точный
    текст «Страна сна» / «Подарок за очки». Все остальные записи считаются как обычно."""
    if e.get("is_bonus"):
        return True
    if e.get("src") == "reward" and (e.get("no_pity") or e.get("kind") in NO_PITY_KINDS):
        return True
    return bool(NON_PITY_RE.search(f"{e.get('name') or ''} {e.get('detail') or ''}"))


def compute_stats(events: list):
    """
    events — хронология (build_timeline). Возвращает (stats по баннерам,
    {(src, id): данные счётчиков на момент записи}).

    Для каждого баннера отдельно ведутся счётчики ОСНОВНЫХ круток (кешбэк и, при
    ITEMS_COUNT_AS_PULL, предметы — тоже крутки):
      counter     — круток с прошлой S (любой) — гарант персонажей;
      counter_std — круток с прошлой S дуги ЛЮБОГО вида (стандартной или ивентовой), цель: 60;
      counter_ev  — круток с прошлой ИВЕНТОВОЙ S дуги, цель: 80 (стандартная S дуга его не сбрасывает).
    Предметы увеличивают счётчики, но НИКОГДА их не сбрасывают и не входят в
    статистику S/A; предметы с флагом no_pity (фрагмент искривления) не меняют
    счётчики вообще. Бонусные записи (is_bonus) НЕ увеличивают счётчики и общее
    число круток — они учитываются отдельно в s["bonus"].
    """
    stats = {key: _blank_stats() for key in BANNERS}
    pity_at = {}

    def snapshot(s):
        return {"bonus": False, "n": s["total"], "p5": s["counter"],
                "cs": s["counter_std"], "ce": s["counter_ev"]}

    for e in events:
        s = stats.get(e["banner"])
        if s is None:  # старые предметы без баннера и скрытые баннеры
            continue
        ref = (e["src"], e["id"])
        _count_item(s, e)
        if e["is_bonus"] or (e["src"] == "wish" and is_non_pity_event(e)):
            s["bonus"] += 1
            pity_at[ref] = {"bonus": True}
            continue
        # OCR-ФИКС 7: «Страна сна» / «Подарок за очки» остаются в истории, но НЕ прибавляют
        # крутку и не двигают гарант; все остальные предметы — по ITEMS_COUNT_AS_PULL.
        if e["src"] == "reward" and (is_non_pity_event(e) or not ITEMS_COUNT_AS_PULL):
            continue

        s["total"] += 1
        for k in COUNTERS:
            s[k] += 1
        if e["banner"] != ARC_BANNER:             # гарант персонажей: строго не больше 90
            s["counter"] = min(s["counter"], PITY_CHAR_HARD)
        pity_at[ref] = snapshot(s)
        if e["src"] == "reward":  # предмет: гарант не сбрасывается, статистика ранга не меняется
            continue

        s[f"r{e['rarity']}"] += 1
        if e["rarity"] == 5:
            s["pities"].append(s["counter"])
            s["counter"] = 0
            if e["banner"] == ARC_BANNER:
                s["counter_std"] = 0
                if arc_kind_by_name(e.get("name"), e.get("arc_kind") or "") == "event":
                    s["counter_ev"] = 0
            s["last5"] = e
        elif e["rarity"] == 4:
            s["last4"] = e
    return stats, pity_at


def history_entries(events: list, pity_at: dict) -> list:
    """Единая история: крутки (в т.ч. кешбэк и бонусы) + предметы, новые сверху.
    kind: main / cashback / bonus / item. ИЗМЕНЕНО: в записи добавлено поле aliases
    (синонимы для иконки; у обычных круток пустое)."""
    out = []
    for e in events:
        info, is_item = pity_at.get((e["src"], e["id"]), {}), e["src"] == "reward"
        if info.get("bonus"):
            kind, n, pity = "bonus", "+", "—"
        elif info:
            kind = "item" if is_item else ("cashback" if e["cashback"] else "main")
            n = str(info["n"])
            pity = (f"С:{info['cs']} · И:{info['ce']}" if e["banner"] == ARC_BANNER
                    else str(info["p5"]))
        else:  # предмет без баннера (старая запись) или счётчики для предметов отключены
            kind, n, pity = "item", "•", "—"
        if is_item:
            type_text = " ".join(t for t in (REWARD_KINDS.get(e["kind"], e["kind"]),
                                             reward_detail_text(e)) if t)
            if e.get("no_pity"):
                type_text += " · вне гаранта"
        else:
            type_text = wish_type_text(e)
        out.append({"src": e["src"], "id": e["id"], "banner": e["banner"] or None,
                    "banner_text": BANNERS.get(e["banner"], "—"), "rarity": e["rarity"],
                    "name": e["name"], "type": type_text, "date": e["pulled_at"],
                    "n": n, "pity": pity, "kind": kind, "p5": info.get("p5", 0),
                    "cs": info.get("cs", 0), "ce": info.get("ce", 0),
                    "arc_kind": e.get("arc_kind") or "",
                    "aliases": tuple(e.get("aliases", ()))})
    out.reverse()
    return out


def export_wish(r: dict) -> dict:
    """Запись крутки для экспорта: ранг выводится буквой S/A/B."""
    rec = {k: r[k] for k in WISH_COLS}
    rec["rarity"] = rank_letter(r["rarity"])
    return rec


# ----------------------------------------------------------------------------
# НОВОЕ: тёмная тема в стиле «стекло» (Glassmorphism)
# ----------------------------------------------------------------------------
# Принципы:
#   * все обычные виджеты ПРОЗРАЧНЫ (QWidget { background: transparent }), поэтому
#     сквозь них виден градиентный фон окна (MainWindow.paintEvent);
#   * «стеклянные» панели (вкладки, группы, карточки, таблицы, поля) — полупрозрачная
#     белая/тёмная заливка rgba(...) + тонкая светлая рамка rgba(255,255,255,40)
#     + скругление 12–16 px;
#   * всплывающие окна (диалоги, меню, выпадающие списки, календарь, подсказки) остаются
#     НЕПРОЗРАЧНЫМИ — иначе текст стал бы нечитаемым на фоне рабочего стола.
# Размытия фона QSS не умеет, поэтому «матовость» имитируется градиентом, лёгким
# «бликом» (светлый градиент слева-сверху) и яркими пятнами света на фоне окна.
# Тени задаются в коде: add_glass_shadow() / apply_glass_shadows().
STYLE = """
QWidget { background: transparent; color: #e6e6ea; font-size: 13px; }
QMainWindow, QDialog { background-color: #0d0f1d; }
QScrollArea { border: none; background: transparent; }

/* --- непрозрачные всплывающие элементы --- */
QToolTip { background-color: #1b1e30; color: #e6e6ea; border: 1px solid rgba(255, 255, 255, 60);
           padding: 4px 6px; }
QMenu { background-color: #1b1e30; border: 1px solid rgba(255, 255, 255, 50); padding: 4px; }
QMenu::item { padding: 6px 22px; border-radius: 6px; }
QMenu::item:selected { background-color: rgba(255, 215, 64, 60); }
QCalendarWidget, QCalendarWidget QWidget { background-color: #1b1e30; }
QCalendarWidget QAbstractItemView { selection-background-color: rgba(255, 215, 64, 70); }
QListView { background-color: #1b1e30; border: 1px solid rgba(255, 255, 255, 50); }  /* подсказка названий */
QStatusBar { background-color: rgba(255, 255, 255, 10); border-top: 1px solid rgba(255, 255, 255, 30); }

/* --- вкладки --- */
QTabWidget::pane { background-color: rgba(255, 255, 255, 10); border: 1px solid rgba(255, 255, 255, 40);
                   border-radius: 16px; top: -1px; }
QTabBar::tab { background: rgba(255, 255, 255, 12); padding: 9px 20px;
               border: 1px solid rgba(255, 255, 255, 30); border-bottom: none;
               border-top-left-radius: 12px; border-top-right-radius: 12px;
               margin-right: 3px; color: #a8adbb; }
QTabBar::tab:hover { background: rgba(255, 255, 255, 24); color: #e6e6ea; }
QTabBar::tab:selected { background: rgba(255, 255, 255, 32); color: #ffd740;
                        border-color: rgba(255, 255, 255, 60); }

/* --- кнопки --- */
QPushButton { background-color: rgba(255, 255, 255, 22); border: 1px solid rgba(255, 255, 255, 55);
              border-radius: 10px; padding: 8px 16px; }
QPushButton:hover { background-color: rgba(255, 255, 255, 40); border-color: #ffd740; }
QPushButton:pressed { background-color: rgba(255, 255, 255, 12); }
QPushButton:disabled { color: #6c7080; background-color: rgba(255, 255, 255, 8);
                       border-color: rgba(255, 255, 255, 25); }
QPushButton#primary { background-color: rgba(212, 160, 23, 220); color: #ffffff; font-weight: bold;
                      border: 1px solid rgba(255, 224, 130, 120); }
QPushButton#primary:hover { background-color: rgba(235, 183, 40, 240); }
QPushButton#danger { background-color: rgba(200, 50, 70, 170); border: 1px solid rgba(255, 130, 140, 90); }
QPushButton#danger:hover { background-color: rgba(225, 65, 85, 200); }
QToolButton { background-color: rgba(255, 255, 255, 22); border: 1px solid rgba(255, 255, 255, 55);
              border-radius: 10px; padding: 4px; }
QToolButton:hover { background-color: rgba(255, 255, 255, 40); border-color: #ffd740; }
QToolButton:pressed { background-color: rgba(255, 255, 255, 12); }
QToolButton:disabled { background-color: rgba(255, 255, 255, 8); border-color: rgba(255, 255, 255, 25); }

/* --- поля ввода (тёмное «стекло» — текст остаётся читаемым) --- */
QLineEdit, QComboBox, QDateTimeEdit, QSpinBox, QDoubleSpinBox { background-color: rgba(8, 10, 24, 120);
              border: 1px solid rgba(255, 255, 255, 40); border-radius: 10px;
              padding: 6px 10px; min-height: 20px; }
QLineEdit:focus, QComboBox:focus, QDateTimeEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus { border-color: #ffd740; }
QComboBox:disabled { color: #6c7080; }
QComboBox QAbstractItemView { background-color: #1b1e30; selection-background-color: rgba(255, 215, 64, 60);
              border: 1px solid rgba(255, 255, 255, 50); }
QPlainTextEdit { background-color: rgba(8, 10, 24, 110); border: 1px solid rgba(255, 255, 255, 40);
              border-radius: 12px; }
QListWidget { background-color: rgba(8, 10, 24, 110); border: 1px solid rgba(255, 255, 255, 40);
              border-radius: 12px; }
QListWidget::item { padding: 3px; border-radius: 6px; }
QListWidget::item:selected { background-color: rgba(255, 215, 64, 55); }
QCheckBox { background: transparent; spacing: 8px; }

/* --- таблицы --- */
QTableWidget { background-color: rgba(8, 10, 24, 100); gridline-color: rgba(255, 255, 255, 18);
               border: 1px solid rgba(255, 255, 255, 40); border-radius: 12px;
               selection-background-color: rgba(255, 215, 64, 55); }
QTableCornerButton::section { background: transparent; border: none; }
QHeaderView::section { background-color: rgba(255, 255, 255, 22); color: #d4d8e4; padding: 7px; border: none;
                       border-right: 1px solid rgba(255, 255, 255, 20); font-weight: bold; }

/* --- контейнеры и плитки --- */
QGroupBox { background-color: rgba(255, 255, 255, 15); border: 1px solid rgba(255, 255, 255, 40);
            border-radius: 16px; margin-top: 14px; padding: 12px 10px 10px 10px; font-weight: bold; }
QGroupBox::title { subcontrol-origin: margin; left: 14px; padding: 0 6px; color: #ffd740; }
QFrame#card { background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                  stop:0 rgba(255, 255, 255, 36), stop:1 rgba(255, 255, 255, 10));
              border: 1px solid rgba(255, 255, 255, 45); border-radius: 14px; }
/* --- СТЕКЛЯННЫЕ верхние карточки вкладки «Стафф» (make_stat_card) --- */
QFrame#statCard { background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                      stop:0 rgba(255, 255, 255, 46), stop:1 rgba(255, 255, 255, 12));
                  border: 1px solid rgba(255, 255, 255, 64);
                  border-top: 1px solid rgba(255, 255, 255, 120);
                  border-radius: 12px; }
QLabel#statTitle { color: #c6cadb; font-size: 13px; font-weight: 600; }
QLabel#statValue { font-size: 34px; font-weight: bold; }
QLabel { background: transparent; }
QLabel#cardTitle { color: #b4b9c9; font-size: 12px; }
QLabel#cardValue { color: #ffd740; font-size: 24px; font-weight: bold; }
QLabel#pity4Value { color: #e2adf0; font-size: 15px; font-weight: bold; }
QLabel#rewardTitle { font-size: 14px; font-weight: bold; }
QLabel#hint { color: #9498aa; }
QLabel#musicValue { color: #b4b9c9; font-size: 12px; }

/* --- плитки персонажей и плашки кубиков (вкладка «Стафф») --- */
QFrame#tile { background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                  stop:0 rgba(255, 255, 255, 30), stop:1 rgba(255, 255, 255, 8));
              border: 1px solid rgba(255, 255, 255, 26); border-radius: 14px; }
QLabel#tileName { color: #ffffff; font-size: 13px; font-weight: bold; }
QLabel#tileValue { font-size: 22px; font-weight: bold; }
QFrame#chip { background-color: rgba(255, 255, 255, 18); border: 1px solid rgba(255, 255, 255, 45);
              border-radius: 10px; }
QLabel#chipText { color: #e6e6ea; font-size: 12px; font-weight: normal; }

/* --- полосы прогресса, прокрутка, ползунки --- */
QProgressBar { background-color: rgba(255, 255, 255, 18); border: 1px solid rgba(255, 255, 255, 40);
               border-radius: 5px; }
QProgressBar::chunk { background-color: #b66cff; border-radius: 4px; }
QScrollBar:vertical { background: transparent; width: 12px; margin: 2px; }
QScrollBar::handle:vertical { background: rgba(255, 255, 255, 55); border-radius: 5px; min-height: 24px; }
QScrollBar::handle:vertical:hover { background: rgba(255, 255, 255, 90); }
QScrollBar:horizontal { background: transparent; height: 12px; margin: 2px; }
QScrollBar::handle:horizontal { background: rgba(255, 255, 255, 55); border-radius: 5px; min-width: 24px; }
QScrollBar::handle:horizontal:hover { background: rgba(255, 255, 255, 90); }
QScrollBar::add-line, QScrollBar::sub-line { height: 0; width: 0; }
QScrollBar::add-page, QScrollBar::sub-page { background: transparent; }
QSlider::groove:horizontal { height: 4px; background: rgba(255, 255, 255, 40); border-radius: 2px; }
QSlider::sub-page:horizontal { background: #d4a017; border-radius: 2px; }
QSlider::handle:horizontal { background: #ffd740; width: 12px; height: 12px;
                             margin: -5px 0; border-radius: 6px; }
QSlider::handle:horizontal:hover { background: #ffe58a; }
QSlider::groove:horizontal:disabled { background: rgba(255, 255, 255, 20); }
QSlider::sub-page:horizontal:disabled { background: rgba(255, 255, 255, 40); }
QSlider::handle:horizontal:disabled { background: #5a5f70; }
"""


BAR_NORMAL = ""


BAR_SOFT = "QProgressBar::chunk { background-color: #ff9800; border-radius: 4px; }"


BAR_HARD = "QProgressBar::chunk { background-color: #e53935; border-radius: 4px; }"


# ----------------------------------------------------------------------------
# НОВОЕ: помощники стиля «стекло» — тени и фон окна
# ----------------------------------------------------------------------------
GLASS_SHADOWS = True  # False — отключить тени (если нужна максимальная скорость отрисовки)


# ----------------------------------------------------------------------------
# НОВОЕ: пользовательский фон приложения (размытое «матовое стекло»)
# ----------------------------------------------------------------------------
BACKGROUND_NAME = "background"                          # assets/background.png | .jpg ...


BACKGROUND_EXTS = (".png", ".jpg", ".jpeg", ".webp")    # порядок = приоритет


BACKGROUND_BLUR_RADIUS = 28.0                           # сила размытия (пиксели рабочей копии)


BACKGROUND_WORK_SIDE = 960                              # размытие делается на копии до 960 px


BACKGROUND_OVERLAY = QColor(15, 15, 25, 191)            # rgba(15, 15, 25, 0.75)


_BG_STATE = {"loaded": False, "pm": None}               # кэш размытой картинки


_STYLE_STATE = {"bg": None}                             # какой стиль сейчас применён


# Доп. стиль, когда есть картинка: полупрозрачные «стёкла» чуть плотнее и темнее, чтобы
# текст оставался чётким и контрастным на любом фоне (правила переопределяют STYLE).
STYLE_ON_BACKGROUND = """
QFrame#statCard { background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                      stop:0 rgba(60, 66, 104, 150), stop:1 rgba(22, 24, 48, 130));
                  border: 1px solid rgba(255, 255, 255, 72);
                  border-top: 1px solid rgba(255, 255, 255, 130); border-radius: 12px; }
QTabWidget::pane { background-color: rgba(10, 12, 28, 95); }
QGroupBox { background-color: rgba(12, 14, 30, 125); border: 1px solid rgba(255, 255, 255, 50); }
QFrame#card { background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                  stop:0 rgba(46, 50, 82, 165), stop:1 rgba(20, 22, 44, 150)); }
QFrame#tile { background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                  stop:0 rgba(44, 48, 78, 160), stop:1 rgba(18, 20, 40, 145)); }
QFrame#chip { background-color: rgba(12, 14, 30, 150); }
QTabBar::tab { background: rgba(14, 16, 34, 170); }
QTabBar::tab:selected { background: rgba(52, 56, 92, 205); }
QLineEdit, QComboBox, QDateTimeEdit, QSpinBox, QDoubleSpinBox { background-color: rgba(8, 10, 24, 175); }
QPlainTextEdit, QListWidget { background-color: rgba(8, 10, 24, 175); }
QTableWidget { background-color: rgba(8, 10, 24, 175); }
QHeaderView::section { background-color: rgba(40, 44, 74, 215); }
QProgressBar { background-color: rgba(8, 10, 24, 150); }
QStatusBar { background-color: rgba(8, 10, 24, 150); }
"""


def find_background_path():
    """Ищет assets/background.png (затем .jpg, .jpeg, .webp) рядом со скриптом и рядом с
    базой данных (также в icons/). Возвращает Path или None."""
    roots = [app_dir()] + ([Path(_DATA_DIR)] if _DATA_DIR is not None else [])
    for ext in BACKGROUND_EXTS:
        for root in roots:
            for base in ICON_DIR_NAMES:
                path = root / base / f"{BACKGROUND_NAME}{ext}"
                if path.is_file():
                    return path
    return None


def reset_background_cache():
    _BG_STATE["loaded"], _BG_STATE["pm"] = False, None


def apply_app_style(app):
    """Применяет STYLE (+ STYLE_ON_BACKGROUND, если есть картинка фона). Таблица стилей
    переустанавливается только при смене состояния «фон есть / нет» — это дорогая операция."""
    has_bg = find_background_path() is not None
    if _STYLE_STATE["bg"] == has_bg:
        return
    _STYLE_STATE["bg"] = has_bg
    app.setStyleSheet(STYLE + (STYLE_ON_BACKGROUND if has_bg else ""))


# ----------------------------------------------------------------------------
# НОВОЕ: помощники раздела «Стафф» — цвет гаранта, плитки персонажей, плашки кубиков
# ----------------------------------------------------------------------------
# ИЗМЕНЕНО: какие кубики показываются на подвкладке каждого пула (механика гачи):
# на ивентовом баннере выпадают только Твердые кубики, на стандартном — только Шулерские,
# с баннера «Дуги» кубики не падают вовсе. Старый общий «cube» виден, только если такие
# записи уже есть (чтобы не прятать старые данные).
CUBE_TITLES = {"solid_cube": "Твердые кубики", "trick_cube": "Шулерские кубики",
               "cube": "Кубики (старые записи)"}


POOL_CUBES = {
    EVENT_BANNER: ("solid_cube", "cube"),
    STANDARD_BANNER: ("trick_cube", "cube"),
    ARC_BANNER: (),
}


def roster_key(name) -> str:
    """Ключ сравнения имён персонажей: без регистра, «ё» = «е» (Блэкбёрд = блэкберд)."""
    return str(name or "").strip().lower().replace("ё", "е")


def pity_color(pulls: int, hard: int = PITY_CHAR_HARD) -> str:
    """Цвет числа круток на персонажа — плавный градиент по оттенку HSV:
    1 крутка — зелёный, середина гаранта — жёлтый/оранжевый, жёсткий гарант (hard,
    по умолчанию 90) — красный. Значения вне диапазона обрезаются."""
    t = 0.0 if hard <= 1 else (pulls - 1) / (hard - 1)
    t = min(max(t, 0.0), 1.0)
    return QColor.fromHsvF((1.0 - t) / 3.0, 0.80, 0.95).name()  # оттенок 120° -> 0°


def clear_grid(grid):
    """Удаляет все виджеты из сетки (перед перестроением)."""
    while grid.count():
        wdg = grid.takeAt(0).widget()
        if wdg is not None:
            wdg.deleteLater()


def roster_counts(history: list, key: str) -> dict:
    """{(ранг, roster_key(имя)): [имя, сколько раз выпал]} — персонажи S и A ранга пула
    key из круток и бонусов. Заглушки («Персонаж», «Дуга»), дуги, предметы и кешбэк
    не учитываются."""
    counts = {}
    for e in history:
        if e["banner"] != key or e["kind"] not in ("main", "bonus") or e["rarity"] not in (4, 5):
            continue
        name = e["name"] or ""
        if name in ("Персонаж", "Дуга") or name.startswith(DUGA_PREFIX):
            continue
        slot = counts.setdefault((e["rarity"], roster_key(name)), [name, 0])
        slot[1] += 1
    return counts


def arc_roster_counts(history: list) -> dict:
    counts = {}
    for e in history:
        if e["banner"] != ARC_BANNER or e["kind"] not in ("main", "bonus") \
                or e["rarity"] not in (4, 5):
            continue
        name = e["name"] or ""
        if not name.startswith(DUGA_PREFIX):
            continue
        slot = counts.setdefault((e["rarity"], roster_key(name)), [name, 0])
        slot[1] += 1
    return counts


# ----------------------------------------------------------------------------
# Раздел «Стафф»: страница одного пула
# ----------------------------------------------------------------------------
# ----------------------------------------------------------------------------
# НОВОЕ: панель баннеров («Текущий ивентовый персонаж» и «Реран персонажа»)
# ----------------------------------------------------------------------------
def banner_countdown(entry, now):
    """Отсчёт баннера -> (текст, подсказка, вид), вид: «live» / «ended» / «none».

    Идёт, осталось сутки и больше -> «До конца: 5 дн. 12 ч.»
    Идёт, осталось меньше суток   -> «Осталось: 03 ч. 45 мин.»
    Ещё не начался                -> «Начнётся через …»
    Срок вышел                    -> «Баннер завершён»
    Нет баннера / времени конца   -> «Время не указано» (интернета нет, JSON без даты)"""
    if not entry:
        return BANNER_NO_TIME_TEXT, "", "none"
    start, end = entry.get("start"), entry.get("end")
    if end and now >= end:
        return BANNER_ENDED_TEXT, f"Завершился {end:%d.%m.%Y %H:%M}", "ended"
    if start and now < start:
        return (f"Начнётся через {format_remaining((start - now).total_seconds())}",
                f"Начало: {start:%d.%m.%Y %H:%M}", "live")
    if end:
        left = (end - now).total_seconds()
        prefix = "До конца:" if left >= 86400 else "Осталось:"
        return f"{prefix} {format_remaining(left)}", f"Окончание: {end:%d.%m.%Y %H:%M}", "live"
    return BANNER_NO_TIME_TEXT, "", "none"


def _banner_art_folders() -> list:
    """Папки с артом в порядке приоритета: assets/banners/, затем assets/characters/ (и
    icons/...). Каждая просматривается рядом со скриптом и рядом с базой данных."""
    roots = [app_dir()] + ([Path(_DATA_DIR)] if _DATA_DIR is not None else [])
    return [root / base / sub for sub in BANNER_ART_DIRS
            for root in roots for base in ICON_DIR_NAMES]


def _find_art(variants: list):
    """Первый файл арта, имя которого совпало с одним из вариантов (png/jpg/jpeg/webp).
    Сначала точное имя, затем нестрогое сравнение (регистр, «_» / «-», «ё» = «е»)."""
    wanted = {roster_key(v) for v in variants}
    for folder in _banner_art_folders():
        if not folder.is_dir():
            continue
        for v in variants:
            for ext in ICON_EXTS:
                if (folder / (v + ext)).is_file():
                    return folder / (v + ext)
        try:
            for f in folder.iterdir():
                if f.suffix.lower() in ICON_EXTS and roster_key(f.stem) in wanted:
                    return f
        except OSError:
            pass
    return None


def _search_banner_art(name: str, generic=()):
    """Ищет файл арта: СНАЧАЛА по имени персонажа (Лакримоза.png / Лакримоза.jpg …), и только
    если такого нет — по общим именам generic (для рерана — rerun.png). Так арт конкретного
    персонажа всегда важнее общей заглушки."""
    specific = list(dict.fromkeys(_name_variants(name) + _name_variants(name.replace("ё", "е"))))
    common = list(dict.fromkeys(v for g in generic for v in _name_variants(g)))
    for variants in (specific, common):
        found = _find_art(variants) if variants else None
        if found is not None:
            return found
    return None


def banner_pull_window(entry):
    """ОБНОВЛЕНО: окно учёта круток баннера -> (start_time, end_time) из banners.json.
    Это поля «start» / «end» записи баннера (event_start_time / event_end_time,
    rerun_start_time / rerun_end_time, start_time / end_time и т. д. — см. parse_banner_payload).
    Если в JSON нет даты старта, нижней границей служит момент, когда приложение впервые
    увидело баннер (entry["activated"]), — иначе в счётчик попали бы ВСЕ старые крутки пула.
    Отсутствие даты окончания означает «без верхней границы»."""
    if not entry:
        return None, None
    return entry.get("start") or entry.get("activated"), entry.get("end")


def _history_datetime(value):
    """Дата записи истории (pulled_at) -> naive datetime или None, если не распознана."""
    dt = parse_banner_datetime(value)
    if dt is None:
        try:
            dt = datetime.strptime(str(value), DATE_FMT)
        except (TypeError, ValueError):
            return None
    return dt


def banner_period_stats(history: list, banner_key: str, start, end) -> dict:
    """ОБНОВЛЕНО: статистика баннера СТРОГО за его период -> {"pulls", "s", "pity"}.

    Считаются только обычные крутки (kind == "main": без бонусов, кешбэка и предметов) пула
    banner_key, у которых ДАТА ЗАПИСИ (pulled_at) лежит в окне  start <= дата <= end  (обе
    границы включительно; None — граница не задана). Крутки до start (в том числе добавленные
    «задним числом»), после end и с нераспознанной датой НЕ входят ни в одно значение:
      pulls — «Круток за период»;
      s     — сколько из них S (ранг 5);
      pity  — «До гаранта: X/90»: число круток пула после последней S (хронологически, до
              конца окна); гарант переносится между баннерами и сбрасывается только выпавшей S.
    Функция универсальна: окно целиком берётся из start / end записи banners.json, поэтому
    при смене персонажей и дат в JSON никакой код менять не нужно."""
    rows, all_rows = [], []
    for e in reversed(history):               # history — «новые сверху»; идём от старых к новым
        # OCR-ФИКС 7: считаются обычные крутки и предметы, занявшие крутку (n — число);
        # «Страна сна» / «Подарок за очки» (kind bonus, n = «•») не входят никуда
        counted_item = e["kind"] == "item" and str(e.get("n", "•")).isdigit()
        if e["banner"] != banner_key or (e["kind"] != "main" and not counted_item):
            continue
        if NON_PITY_RE.search(e.get("name") or ""):
            continue
        dt = _history_datetime(e["date"])
        if dt is None or (end and dt > end):
            continue                          # после окончания баннера (или дата не распознана)
        rarity = e["rarity"] if e["kind"] == "main" else 0
        all_rows.append((dt, rarity))         # для гаранта: все крутки пула до конца окна
        if start and dt < start:
            continue                          # до старта — в «круток за период» не входит
        rows.append((dt, rarity))
    rows.sort(key=lambda r: r[0])             # сортировка устойчивая: равное время — по порядку записи
    all_rows.sort(key=lambda r: r[0])
    pulls, s_count, pity = 0, 0, 0
    for _dt, rarity in rows:
        pulls += 1
        if rarity == 5:
            s_count += 1
    # ИСПРАВЛЕНО: гарант ПЕРЕНОСИТСЯ между баннерами пула — число круток после последней S
    # (за всё время, а не только в окне); сбрасывается только выпадением S
    for _dt, rarity in all_rows:
        pity += 1
        if rarity == 5:                       # предметы (rarity 0) гарант не сбрасывают
            pity = 0                          # S сбрасывает гарант
    if banner_key != ARC_BANNER:
        pity = min(pity, PITY_CHAR_HARD)      # гарант персонажей — не больше 90
    return {"pulls": pulls, "s": s_count, "pity": pity}


def arc_period_stats(history: list, start, end) -> dict:
    """Статистика баннера дуг: «круток за период» и S — только в окне [start; end];
    счётчики гарантов (std — стандартная S дуга, ev — ивентовая S дуга) ПЕРЕНОСЯТСЯ между
    баннерами: считаются по всем круткам пула до конца окна и сбрасываются только выпавшей S."""
    rows, all_rows = [], []
    for e in reversed(history):
        counted_item = e["kind"] == "item" and str(e.get("n", "•")).isdigit()
        if e["banner"] != ARC_BANNER or (e["kind"] != "main" and not counted_item):
            continue
        if NON_PITY_RE.search(e.get("name") or ""):
            continue
        dt = _history_datetime(e["date"])
        if dt is None or (end and dt > end):
            continue
        is_main = e["kind"] == "main"
        kind = arc_kind_by_name(e.get("name"), e.get("arc_kind") or "") if is_main else ""
        row = (dt, e["rarity"] if is_main else 0, kind)
        all_rows.append(row)
        if start and dt < start:
            continue
        rows.append(row)
    rows.sort(key=lambda r: r[0])
    all_rows.sort(key=lambda r: r[0])
    pulls, s_count, std, ev = 0, 0, 0, 0
    for _dt, rarity, _kind in rows:
        pulls += 1
        if rarity == 5:
            s_count += 1
    for _dt, rarity, kind in all_rows:
        std += 1
        ev += 1
        if rarity == 5:
            std = 0
            if kind == "event":
                ev = 0
    return {"pulls": pulls, "s": s_count, "std": std, "ev": ev}


def count_banner_period_pulls(history: list, banner_key: str, start, end):
    """Совместимая обёртка: («Круток за период», из них S) — см. banner_period_stats."""
    st = banner_period_stats(history, banner_key, start, end)
    return st["pulls"], st["s"]


# ----------------------------------------------------------------------------
# НОВОЕ: фоновая анимация вкладки «Стафф» (снежинки / листочки / звёздочки)
# ----------------------------------------------------------------------------
class _Particle:
    __slots__ = ("x", "y", "x0", "size", "vx", "vy", "angle", "spin", "phase", "omega",
                 "amp", "swing", "alpha", "color")


_SPRITE_PATHS = {}


# ----------------------------------------------------------------------------
# Главное окно
# ----------------------------------------------------------------------------
# ----------------------------------------------------------------------------
# НОВОЕ: фоновый запрос текущего ивентового баннера
# ----------------------------------------------------------------------------
_LIVE_OCR_THREADS = set()     # НОВОЕ: потоки OCR, пережившие закрытие окна


_LIVE_BANNER_THREADS = set()  # потоки, пережившие закрытие окна (чтобы Qt не уничтожил их «на ходу»)


def parse_banner_datetime(value, end_of_day: bool = False):
    """Превращает значение из JSON в НАИВНОЕ местное datetime (или None, если не распознано).

    Понимает: ISO-строки (дата или дата+время, «Z»/смещение пояса — переводится в местное
    время), «ДД.ММ.ГГГГ [ЧЧ:ММ[:СС]]», «ГГГГ/ММ/ДД [ЧЧ:ММ]», Unix-время (сек или мс).
    end_of_day=True: если указана только дата, берётся конец суток (23:59:59) — для end_date.
    Ошибка разбора — не повод падать: срок просто считается неизвестным.
    """
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        ts = value / 1000 if value > 1e11 else value  # миллисекунды -> секунды
        try:
            return datetime.fromtimestamp(ts)
        except (OverflowError, OSError, ValueError):
            return None
    text = str(value).strip()
    if not text:
        return None
    dt = None
    try:
        dt = datetime.fromisoformat(text)   # дата, дата+время, «T», «Z», смещение
    except ValueError:
        for fmt in ("%d.%m.%Y %H:%M:%S", "%d.%m.%Y %H:%M", "%d.%m.%Y",
                    "%Y/%m/%d %H:%M:%S", "%Y/%m/%d %H:%M", "%Y/%m/%d"):
            try:
                dt = datetime.strptime(text, fmt)
                break
            except ValueError:
                continue
    if dt is None:
        return None
    date_only = not re.search(r"\d:\d", text)  # во входной строке нет времени
    if dt.tzinfo is not None:                   # переводим в местное время компьютера
        dt = dt.astimezone().replace(tzinfo=None)
    elif date_only and end_of_day:
        dt = dt.replace(hour=23, minute=59, second=59)
    return dt


def format_remaining(seconds: float) -> str:
    """Оставшееся время по-русски: «5 дн. 12 ч.» (от суток), «03 ч. 45 мин.»
    (меньше суток), «12 мин.» (меньше часа), «меньше минуты»."""
    total = int(seconds)
    if total < 60:
        return "меньше минуты"
    days, rest = divmod(total, 86400)
    hours, rest = divmod(rest, 3600)
    minutes = rest // 60
    if days:
        return f"{days} дн. {hours} ч."   # формат «X дн. Y ч.» (минуты от суток не нужны)
    if hours:
        return f"{hours:02d} ч. {minutes:02d} мин."
    return f"{minutes} мин."


def pick_banner_dates(sources):
    """Достаёт (начало, конец) из JSON. sources — список пар (словарь, префикс ключей);
    берётся первое найденное значение. Нераспознанная дата -> None; если конец не позже
    начала, начало игнорируется."""
    found = {}
    for field, keys, end_of_day in (("start", BANNER_START_KEYS, False),
                                    ("end", BANNER_END_KEYS, True)):
        found[field] = None
        for src, prefix in sources:
            raw = next((src[prefix + k] for k in keys if src.get(prefix + k) not in (None, "")), None)
            if raw is not None:
                found[field] = parse_banner_datetime(raw, end_of_day)
                break
    start, end = found["start"], found["end"]
    if start and end and end <= start:
        start = None
    return start, end


def _lower_keys(d: dict) -> dict:
    """Копия словаря с ключами в нижнем регистре и без пробелов по краям: «Rerun_End_Time »
    и «rerun_end_time» читаются одинаково."""
    return {str(k).strip().lower(): v for k, v in d.items()}


def parse_rerun_entry(data):
    """Реран из JSON: {"name", "start", "end"} или None, если рерана нет / имя некорректно.

    Схема та же, что у основного баннера:
      * имя — строка («rerun_banner»: «Лакримоза») или объект {"name": ..., "end_time": ...};
      * дата окончания: внутри объекта (end_time / end_date / end …) ИЛИ на верхнем уровне
        с префиксом rerun_ (rerun_end_time, rerun_end_date, rerun_event_end_time …);
      * дата начала — аналогично (rerun_start_time …).
    Ошибка здесь не критична: без рерана правая половина панели просто пуста."""
    entry = next((data[k] for k in BANNER_RERUN_KEYS
                  if data.get(k) not in (None, "", {}, [])), None)
    sources = [(data, pre) for pre in BANNER_RERUN_DATE_PREFIXES]
    if isinstance(entry, dict):
        entry = _lower_keys(entry)
        name = entry.get("name") or entry.get("character") or entry.get("banner") or ""
        sources.insert(0, (entry, ""))     # даты внутри объекта рерана — в приоритете
    elif isinstance(entry, str):
        name = entry
    else:
        return None
    name = str(name).strip()
    if not name or len(name) > BANNER_NAME_MAX_LEN or "\n" in name:
        return None
    start, end = pick_banner_dates(sources)
    return {"name": name, "start": start, "end": end}


def parse_arc_entry(data, keys, prefixes):
    entry = next((data[k] for k in keys if data.get(k) not in (None, "", {}, [])), None)
    sources = [(data, prefix) for prefix in prefixes]
    if isinstance(entry, dict):
        entry = _lower_keys(entry)
        name = (entry.get("name") or entry.get("arc") or entry.get("weapon")
                or entry.get("banner") or "")
        sources.insert(0, (entry, ""))
    elif isinstance(entry, str):
        name = entry
    else:
        return None
    name = str(name).strip()
    if not name or len(name) > BANNER_NAME_MAX_LEN or "\n" in name:
        return None
    start, end = pick_banner_dates(sources)
    return {"name": name, "start": start, "end": end}


def parse_banner_payload(data) -> dict:
    """Достаёт из JSON текущий ивентовый баннер и (необязательно) реран.

    Основной формат: {"current_event_banner": "Имя"}. Допустимы также запасные формы
    (см. docstring в начале файла): значение-объект {"name": "Имя", "start": ..., "end": ...}
    и старый ключ "event_character". Реран: «rerun_banner» + «rerun_end_time» (см. parse_rerun_entry).
    Возвращает {"name": str, "start": datetime | None, "end": datetime | None,
                "rerun": {"name", "start", "end"} | None}.
    ИСПРАВЛЕНО: реран не зависит от основного баннера. Раньше при отсутствии
    current_event_banner выбрасывалась ошибка и реран пропадал вместе с ним; теперь ошибка
    только если нет НИ основного баннера, НИ рерана. Без основного баннера name == "".
    Даты (start_date / end_date или start_time / end_time) необязательны: если их нет или
    они не распознаны — соответствующее значение None.
    """
    if not isinstance(data, dict):
        raise ValueError("ожидался JSON-объект")
    data = _lower_keys(data)               # ключи верхнего уровня — без учёта регистра
    entry = next((data[k] for k in BANNER_CURRENT_KEYS
                  if data.get(k) not in (None, "", {}, [])), None)
    if entry is None:                      # запасные ключи — на случай другого названия поля
        entry = data.get(EVENT_BANNER) or data.get("character") or data.get("name")
    info = {"name": "", "start": None, "end": None}
    sources = [data]                       # где искать даты: сначала внутри объекта баннера,
    if isinstance(entry, dict):            # затем на верхнем уровне JSON
        entry = _lower_keys(entry)
        info["name"] = entry.get("name") or entry.get("character") or ""
        sources.insert(0, entry)
    elif isinstance(entry, str):
        info["name"] = entry
    info["start"], info["end"] = pick_banner_dates(
        [(src, "") for src in sources] + [(data, pre) for pre in BANNER_CURRENT_DATE_PREFIXES])
    info["rerun"] = parse_rerun_entry(data)   # реран персонажа (или None)
    info["arc"] = parse_arc_entry(data, BANNER_ARC_KEYS, BANNER_ARC_DATE_PREFIXES)
    info["arc_rerun"] = parse_arc_entry(data, BANNER_ARC_RERUN_KEYS,
                                        BANNER_ARC_RERUN_DATE_PREFIXES)
    name = str(info["name"]).strip()
    if not name or len(name) > BANNER_NAME_MAX_LEN or "\n" in name:
        if info["rerun"] is None and info["arc"] is None and info["arc_rerun"] is None:
            raise ValueError("в ответе нет корректного названия баннера")
        name, info["start"], info["end"] = "", None, None   # есть только реран
    info["name"] = name
    return info


# ---- НОВОЕ: пакетное распознавание («Скриншот оптом») ----
BATCH_MAX_FILES = 10                              # не больше стольких скриншотов за раз


BATCH_EXTS = (".jpg", ".jpeg", ".png", ".bmp")    # допустимые форматы


_LIVE_BATCH_THREADS = set()                       # потоки, пережившие закрытие окна


def natural_key(path) -> list:
    """Ключ «естественной» сортировки имён файлов: shot2.png идёт раньше shot10.png."""
    return [int(t) if t.isdigit() else t.lower()
            for t in re.split(r"(\d+)", Path(path).name)]


# ---- НОВОЕ: «Скриншоты разом» — массовая обработка (100–200+ файлов) ----
MASS_GC_EVERY = 8          # как часто (в файлах) принудительно вызывать сборщик мусора


MASS_UI_SLICE_S = 0.025    # сколько секунд подряд работает «порция» разбора/построения списка в окне


MASS_LIST_ROWS = 10        # минимальная высота общего списка (строк без прокрутки)


def file_created_ns(path) -> int:
    """Время создания файла (нс): st_birthtime, на Windows — st_ctime; иначе наименьшее из
    ctime и mtime. Ошибка чтения — 0."""
    try:
        st = Path(path).stat()
    except OSError:
        return 0
    birth = getattr(st, "st_birthtime", None)
    if birth is not None:
        return int(birth * 1_000_000_000)
    if sys.platform == "win32":
        return st.st_ctime_ns
    return min(st.st_ctime_ns, st.st_mtime_ns)


def mass_sort_key(path) -> tuple:
    """Ключ порядка файлов: строго по дате создания (старые первыми); при равенстве — дата
    изменения, затем естественное имя файла и путь."""
    try:
        mtime = Path(path).stat().st_mtime_ns
    except OSError:
        mtime = 0
    return (file_created_ns(path), mtime, natural_key(path), str(path))


# Порядок скриншотов с ОДИНАКОВЫМ временем записей (десятикратный бросок, разорванный на две
# страницы): True — страницы снимались сверху вниз (ранний файл содержит более НОВЫЕ записи),
# False — снизу вверх (ранний файл содержит более СТАРЫЕ записи).
SHOT_PAGES_CAPTURED_TOP_DOWN = True


STAMP_CONFUSABLE = {frozenset(x) for x in ("35", "17", "08", "68", "56", "38", "06", "89")}


def repair_stamp_misreads(pull_lists: list) -> int:
    """Исправляет одиночные ошибки OCR в цифрах времени («31» прочитано как «51») по всем
    скриншотам пакета: если метка встречается один-два раза, а метка, отличающаяся ровно одной
    похожей цифрой (3/5, 1/7, 0/8, 6/8, 5/6 ...), встречается заметно чаще — берётся частая.
    Исправленные записи помечаются жёлтым. Возвращает число исправленных записей."""
    items = [p for pulls in pull_lists for p in pulls if p.get("has_time")]
    fixed = 0
    # день-буква («Б май» = 5 или 6 мая): берём вариант, который подтверждают записи с чётко
    # прочитанным днём по всему пакету (по полной метке времени)
    firm_count = Counter(p["timestamp"].toString(QT_DATE_FMT) for p in items
                         if not soft_day_stamps(p.get("raw_date") or ""))
    for p in items:
        alts = soft_day_stamps(p.get("raw_date") or "")
        if not alts or p.get("time_locked"):
            continue
        cur = p["timestamp"].toString(QT_DATE_FMT)
        best = max(alts, key=lambda a: firm_count.get(a, 0))
        if firm_count.get(best, 0) and best != cur:
            p["timestamp"] = QDateTime.fromString(best, QT_DATE_FMT)
            fixed += 1          # уверенная правка («Б» = 5): жёлтой пометки не нужно
    count = Counter(p["timestamp"].toString(QT_DATE_FMT) for p in items)
    for p in items:
        cur = p["timestamp"].toString(QT_DATE_FMT)
        own, best, best_n = count[cur], None, 0
        if own > 2 or p.get("time_locked"):
            continue
        for i, ch in enumerate(cur):
            if not ch.isdigit():
                continue
            for other in "0123456789":
                if other == ch or frozenset((ch, other)) not in STAMP_CONFUSABLE:
                    continue
                cand = cur[:i] + other + cur[i + 1:]
                n = count.get(cand, 0)
                if n >= 2 and n > own * 2 and n > best_n:
                    try:
                        datetime.strptime(cand, DATE_FMT)
                    except ValueError:
                        continue
                    best, best_n = cand, n
        if best:
            p["timestamp"] = QDateTime.fromString(best, QT_DATE_FMT)
            reasons = list(p.get("weak") or [])
            reasons.append(f"время исправлено по соседним записям: {cur[11:]} → {best[11:]}")
            p["weak"], p["needs_review"] = reasons, True
            fixed += 1
    return fixed


def shot_order_key(stamps: list, order: int, total: int) -> tuple:
    """Ключ порядка скриншота в пакете: сначала по найденному времени записей (старые первыми:
    минимум, затем максимум), при полном совпадении — по порядку создания файла (order) с учётом
    SHOT_PAGES_CAPTURED_TOP_DOWN; скриншоты без найденного времени — в конце по порядку файлов."""
    if not stamps:
        return (1, "", "", order)
    tie = (total - order) if SHOT_PAGES_CAPTURED_TOP_DOWN else order
    return (0, min(stamps), max(stamps), tie)


def _lnds_keep(values: list) -> set:
    """Индексы наибольшей неубывающей подпоследовательности (они считаются верными)."""
    import bisect
    tails, tails_idx, prev = [], [], [-1] * len(values)
    for i, v in enumerate(values):
        pos = bisect.bisect_right(tails, v)
        if pos == len(tails):
            tails.append(v)
            tails_idx.append(i)
        else:
            tails[pos], tails_idx[pos] = v, i
        prev[i] = tails_idx[pos - 1] if pos else -1
    keep, k = set(), (tails_idx[-1] if tails_idx else -1)
    while k != -1:
        keep.add(k)
        k = prev[k]
    return keep


def _add_review_reason(p: dict, reason: str) -> None:
    reasons = list(p.get("weak") or [])
    reasons.append(reason)
    p["weak"], p["needs_review"] = reasons, True


def mark_locked_times(entries: list) -> None:
    """Записи, время которых пользователь исправил вручную в редакторе, автоматическим
    исправлениям времени не подлежат."""
    for e in entries:
        edits = e.get("edits") or {}
        for p in e["pulls"]:
            p["time_locked"] = p.get("line") in edits


def resolve_page_conflicts(entries: list) -> list:
    """Два скриншота с одним номером страницы — одно из прочтений ошибочно (113 → 115). У менее
    уверенного (меньше голосов) берётся запасное прочтение с тем же «всего», номер которого ещё
    не занят. Возвращает предупреждения о сделанных заменах."""
    notes = []
    for _ in range(len(entries)):
        by_page = {}
        for e in entries:
            by_page.setdefault(e["page"], []).append(e)
        conflict = next((grp for grp in by_page.values() if len(grp) > 1), None)
        if not conflict:
            break

        def votes(e):
            return dict(e.get("page_alts") or []).get(e["page"], 0)
        conflict.sort(key=lambda e: -votes(e))
        taken = {e["page"][0] for e in entries}
        changed = False
        for e in conflict[1:]:
            alts = [pg for pg, _n in (e.get("page_alts") or [])
                    if pg[1] == e["page"][1] and pg[0] not in taken]
            if alts:
                notes.append(f"номер страницы файла {Path(e['path']).name} исправлен: "
                             f"{e['page'][0]} → {alts[0][0]}")
                e["page"] = alts[0]
                taken.add(alts[0][0])
                changed = True
        if not changed:
            break
    return notes


def repair_page_numbers(entries: list) -> list:
    """ИСПРАВЛЕНО (порядок и даты страниц): Tesseract путает похожие цифры и в номере страницы —
    «34/115» читается как «54/115». Такая страница попадала в начало пакета (как самая старая),
    а все её записи получали неверный порядок и счётчик. Здесь номера проверяются по времени:
    по возрастанию номера время записей должно убывать (страница с большим номером старше).
    Номера, нарушающие это, подменяются запасным прочтением или похожей цифрой, если после
    замены хронология и непрерывность страниц становятся лучше. Возвращает список замечаний."""
    if len(entries) < 3 or not all(e.get("page") for e in entries):
        return []
    total = entries[0]["page"][1]
    if any(e["page"][1] != total for e in entries):
        return []
    top = {id(e): max(e["stamps"]) if e.get("stamps") else None for e in entries}
    start = {id(e): e["page"][0] for e in entries}

    def score(pages: dict) -> float:
        order = sorted(entries, key=lambda e: -pages[id(e)])
        times = [top[id(e)] for e in order if top[id(e)]]
        inversions = len(times) - len(_lnds_keep(times)) if times else 0
        nums = [pages[id(e)] for e in entries]
        dup = len(nums) - len(set(nums))
        missing = (max(nums) - min(nums) + 1) - len(set(nums))
        changed = sum(1 for e in entries if pages[id(e)] != start[id(e)])
        return 10 * inversions + 3 * dup + 0.05 * missing + 2 * changed

    def candidates(e) -> set:
        n = start[id(e)]
        out = {pg for pg, _v in (e.get("page_alts") or []) if pg[1] == total}
        out = {pg[0] for pg in out}
        digits = str(n)
        for i, ch in enumerate(digits):
            for other in "0123456789":
                if other != ch and frozenset((ch, other)) in STAMP_CONFUSABLE:
                    v = int((digits[:i] + other + digits[i + 1:]) or 0)
                    out.add(v)
        return {v for v in out if 1 <= v <= total and v != n}

    pages = dict(start)
    best = score(pages)
    for _ in range(len(entries) * 2):
        move = None
        for e in entries:
            for v in candidates(e):
                trial = dict(pages)
                trial[id(e)] = v
                sc = score(trial)
                if sc < best - 1e-9 and (move is None or sc < move[0]):
                    move = (sc, e, v)
        if move is None:
            break
        best, e, v = move
        pages[id(e)] = v
    notes = []
    for e in entries:
        if pages[id(e)] != start[id(e)]:
            notes.append(f"номер страницы файла {Path(e['path']).name} исправлен по времени записей: "
                         f"{start[id(e)]} → {pages[id(e)]}")
            e["page"] = (pages[id(e)], total)
    return notes


def order_shots(entries: list, total_files: int):
    """Порядок скриншотов пакета. entries — [{"order", "path", "pulls", "page"}].
    Если номер страницы «N/M» найден на КАЖДОМ скриншоте и у всех одно M — порядок строго по
    странице (больший номер — старше), время только проверяется. Иначе — по найденному времени
    (shot_order_key). Возвращает (упорядоченные записи, предупреждения, page_mode)."""
    warnings = []
    for e in entries:
        e["stamps"] = [p["timestamp"].toString(QT_DATE_FMT) for p in e["pulls"] if p["has_time"]]
    totals = Counter(e["page"][1] for e in entries if e.get("page"))
    if len(totals) > 1:
        common = totals.most_common(1)[0][0]
        for e in entries:
            if e.get("page") and e["page"][1] != common:
                alts = [pg for pg, _n in (e.get("page_alts") or []) if pg[1] == common]
                if alts:
                    e["page"] = alts[0]
    pages = [e.get("page") for e in entries]
    if entries and all(pages):
        warnings += resolve_page_conflicts(entries)
        warnings += repair_page_numbers(entries)
        pages = [e.get("page") for e in entries]
    page_mode = bool(entries) and all(pages) and len({pg[1] for pg in pages}) == 1

    def time_key(e):
        return shot_order_key(e["stamps"], e["order"], total_files)

    if page_mode:
        ordered = sorted(entries, key=lambda e: (-e["page"][0], time_key(e)))
        total = entries[0]["page"][1]
        nums = [e["page"][0] for e in ordered]
        dup = sorted({n for n in nums if nums.count(n) > 1}, reverse=True)
        if dup:
            warnings.append("одна страница истории на нескольких скриншотах: "
                            + ", ".join(map(str, dup)) + " — возможны дубли")
        missing = sorted(set(range(min(nums), max(nums) + 1)) - set(nums), reverse=True)
        if missing:
            shown = ", ".join(map(str, missing[:12])) + ("…" if len(missing) > 12 else "")
            warnings.append(f"пропущены страницы между скриншотами: {shown} — гарант может быть неверным")
        for e in ordered:
            n = e["page"][0]
            found = len(e["pulls"])
            if n != total and found != OCR_PAGE_SIZE:
                warnings.append(f"страница {n}: найдено записей {found} из {OCR_PAGE_SIZE}")
    else:
        ordered = sorted(entries, key=time_key)
        if entries and any(pages):
            warnings.append("номер страницы «N/M» найден не на всех скриншотах (или у них разное "
                            "число страниц) — порядок задан по времени записей")
        elif entries:
            warnings.append("номер страницы «N/M» на скриншотах не найден — порядок задан по "
                            "времени записей")
    return ordered, warnings, page_mode


def enforce_chronology(ordered: list):
    """Проверка монотонности времени по всей цепочке «страницы от старых к новым, строки снизу
    вверх». Время должно только расти; записи, нарушающие рост (обычно — ошибка OCR в цифре),
    исправляются: сначала подбором одной похожей цифры, чтобы время встало между верными
    соседями, иначе подставляется время ближайшей верной записи ПЕРЕД ней (порядок на
    странице известен точно). Исправленные записи помечаются жёлтым.
    Возвращает (число исправлений, предупреждения)."""
    seq = [p for e in ordered for p in bottom_to_top_order(e["pulls"]) if p.get("has_time")]
    if len(seq) < 3:
        return 0, []
    vals = [p["timestamp"].toString(QT_DATE_FMT) for p in seq]
    keep = _lnds_keep(vals)
    bad = [i for i in range(len(seq)) if i not in keep]
    if not bad:
        return 0, []
    if len(bad) > max(3, int(len(seq) * 0.2)):
        for i in bad:
            _add_review_reason(seq[i], "время нарушает хронологию страниц")
        return 0, [f"хронология по номерам страниц нарушена у {len(bad)} из {len(seq)} записей — "
                   f"возможно, страницы сняты в разное время; время не менялось, проверьте жёлтые строки"]
    fixed = 0
    for i in bad:
        p = seq[i]
        if p.get("time_locked"):
            continue
        prev_ok = next((vals[j] for j in range(i - 1, -1, -1) if j in keep), None)
        next_ok = next((vals[j] for j in range(i + 1, len(seq)) if j in keep), None)
        lo, hi, cur = prev_ok or "0000", next_ok or "9999", vals[i]
        best = None
        for pos, ch in enumerate(cur):
            if not ch.isdigit():
                continue
            for other in "0123456789":
                if other == ch:
                    continue
                cand = cur[:pos] + other + cur[pos + 1:]
                if not (lo <= cand <= hi):
                    continue
                try:
                    delta = abs((datetime.strptime(cand, DATE_FMT)
                                 - datetime.strptime(cur, DATE_FMT)).total_seconds())
                except ValueError:
                    continue
                rank = (frozenset((ch, other)) not in STAMP_CONFUSABLE, delta)
                if best is None or rank < best[0]:
                    best = (rank, cand)
        if best:
            new, how = best[1], "исправлено по хронологии страниц"
        else:
            new, how = (prev_ok or next_ok), "нарушает хронологию страниц, подставлено время соседней записи"
        if not new or new == cur:
            _add_review_reason(p, "время нарушает хронологию страниц")
            continue
        p["timestamp"] = QDateTime.fromString(new, QT_DATE_FMT)
        _add_review_reason(p, f"время {how}: {cur[11:] if cur[:10] == new[:10] else cur} → "
                              f"{new[11:] if cur[:10] == new[:10] else new}")
        fixed += 1
    return fixed, ([f"время исправлено по хронологии страниц у записей: {fixed} (жёлтые)"]
                   if fixed else [])


def refresh_flagged(entries: list, data: dict) -> None:
    """Пересчёт числа помеченных строк файла после автоисправлений."""
    for e in entries:
        d = data.get(e["path"])
        if d is not None:
            d["flagged"] = sum(1 for p in e["pulls"] if p.get("needs_review"))


def format_duration(seconds) -> str:
    """Длительность для таймеров: «01:20» или «1:05:09» (с часами)."""
    total = max(0, int(round(seconds)))
    h, rest = divmod(total, 3600)
    m, sec = divmod(rest, 60)
    return f"{h}:{m:02d}:{sec:02d}" if h else f"{m:02d}:{sec:02d}"


# ---------------------------------------------------------------------------
# НОВОЕ: правки строк после сканирования (общие для «Скриншот оптом» и «Скриншоты разом»)
# ---------------------------------------------------------------------------
def new_file_data() -> dict:
    """Данные одного файла пакета: текст OCR, ранги, уверенность, статус и правки строк."""
    return {"text": "", "ranks": [], "glob": None, "confs": None, "page": None, "page_alts": [], "status": "Ожидает",
            "count": None, "chrono": None, "done": False,
            "edits": {}, "reviewed": set(),            # правки и просмотренные строки (по номеру строки)
            "pulls_all": [], "skipped_rest": [], "flagged": 0}


def review_total(data: dict) -> int:
    """Сколько строк всех файлов вкладки ждут проверки."""
    return sum(review_count(d) for d in data.values())


def review_count(d: dict) -> int:
    """Сколько строк файла ещё ждут проверки (помеченные + нераспознанные)."""
    return int(d.get("flagged", 0)) + len(d.get("skipped_rest", ()))


def pull_from_edit(base: dict, e: dict) -> dict:
    """Запись по правке из редактора: тип, название, количество, ранг, время. base — прежняя
    запись (или заготовка для нераспознанной строки). Место строки в раскладке (line) не
    меняется, поэтому порядок выпадений сохраняется."""
    key = e["loot"]
    info = LOOT_TYPES[key]
    mode = info["mode"]
    qty = e.get("qty") or None
    rank = e.get("rank") or base.get("rarity") or 3
    if mode == "cashback":
        rarity, src = loot_rarity(info), "тип предмета"
    elif mode == "reward":
        fixed = loot_rarity(info)
        rarity, src = rank, ("тип предмета" if rank == fixed else "цвет")
    else:
        rarity, src = rank, "правка"
    name = (e.get("name") or "").strip()
    if info.get("hide_name") or not name:
        name = ""
    elif key == "arc":
        name = format_duga_name(name)
    elif key == "character":
        name = clean_character_name(name)
    elif key == "outfit":
        name = format_outfit_name(name)              # «Костюм - Название»
    else:
        name = strip_item_prefix(key, strip_labels(name, ("rank",)))
    is_bonus = bool(base.get("is_bonus")) and mode != "cashback"
    type_text = (REWARD_KINDS[info["kind"]] if mode == "reward" and info.get("kind") in REWARD_KINDS
                 else info["label"])
    if is_bonus:
        type_text = f"{BONUS_TYPE_PREFIX} - {type_text}"
    when = QDateTime.fromString(e["ts"], QT_DATE_FMT)
    out = dict(base)
    out.update(
        loot=key, name=name, rarity=rarity, rarity_src=src, qty=qty, amount=qty,
        rarity_type=info["label"] if mode != "wish" else rank_letter(rarity),
        item_label=info["label"] if mode == "reward" else "",
        item_type=("Предмет" if mode == "reward" else "Кешбэк" if mode == "cashback"
                   else info["label"]),
        display_name=(default_reward_name(info["kind"], qty or info.get("detail", ""))
                      if mode == "reward" and not name else name),
        type_text=type_text, is_bonus=is_bonus, timestamp=when, has_time=when.isValid(),
        known=True, doubtful=False, weak=[], needs_review=False, edited=True)
    return out


def merge_row_edits(pulls: list, skipped_rows: list, d: dict):
    """Накладывает правки редактора на результат разбора файла. Возвращает (записи в порядке
    раскладки скриншота, нераспознанные строки без правок, сколько строк превращено в записи).
    Порядок — строго по номеру строки текста, поэтому правка не может переставить строки."""
    edits, reviewed = d.get("edits") or {}, d.get("reviewed") or set()
    out, rest, converted = [], [], 0
    for p in pulls:
        line = p.get("line")
        e = edits.get(line)
        if e is not None:
            if e.get("include", True):
                out.append(pull_from_edit(p, e))
            continue                                   # include=False — строка убрана пользователем
        if line in reviewed:
            p = dict(p, needs_review=False, weak=[])   # просмотрена — подсветка снимается
        out.append(p)
    for r in skipped_rows:
        e = edits.get(r["line"])
        if e is not None and e.get("include") and e.get("loot"):
            base = {"is_bonus": r.get("bonus", False), "raw_date": r.get("raw_date", ""),
                    "body_raw": r["body"], "conf": r.get("conf"), "line": r["line"]}
            out.append(pull_from_edit(base, e))
            converted += 1
        elif r["line"] not in reviewed:
            rest.append(r)
    out.sort(key=lambda q: q.get("line", 0))
    return out, rest, converted


def parse_file_with_edits(d: dict, known: dict, default_loot: str):
    """Разбор одного файла + правки редактора. Сохраняет в d итоговые записи (pulls_all),
    оставшиеся нераспознанные строки (skipped_rest) и число помеченных (flagged).
    Возвращает (записи, число пропущенных строк)."""
    pulls, skipped, rows = parse_screenshot_text_ex(d["text"], known, d["ranks"], d["glob"],
                                                    default_loot, d.get("confs"))
    pulls, rest, converted = merge_row_edits(pulls, rows, d)
    d["pulls_all"], d["skipped_rest"] = pulls, rest
    d["flagged"] = sum(1 for p in pulls if p.get("needs_review"))
    return pulls, max(0, skipped - converted)


def QDateTime_le(a, b) -> bool:
    """ИСПРАВЛЕНО: a <= b для QDateTime с точностью до секунды (равное время — допустимо)."""
    fa, fb = (_qdt_seconds(a).toString(QT_DATE_FMT), _qdt_seconds(b).toString(QT_DATE_FMT))
    return datetime.strptime(fa, DATE_FMT) <= datetime.strptime(fb, DATE_FMT)


def _qdt_seconds(value):
    """ИСПРАВЛЕНО: QDateTime без миллисекунд (формат DATE_FMT), чтобы время записей одной крутки
    совпадало побайтно и границы поля времени не отсекали равные секунды."""
    try:
        out = QDateTime.fromString(value.toString(QT_DATE_FMT), QT_DATE_FMT)
        return out if out.isValid() else value
    except AttributeError:
        return value


def collect_editor_entries(paths: list, data: dict) -> list:
    """Строки для «Редактора нераспознанных строк»: помеченные записи и нераспознанные строки
    в порядке файлов и раскладки. Для каждой считаются границы времени: не новее ближайшей
    записи выше (она выпала позже) и не старше ближайшей записи ниже (выпала раньше)."""
    entries = []
    for path in paths:
        d = data[path]
        pulls = d.get("pulls_all", [])
        timed = sorted(((q["line"], q["timestamp"]) for q in pulls
                        if q.get("has_time") and "line" in q), key=lambda t: t[0])
        todo = [("flag", q) for q in pulls if q.get("needs_review")]
        todo += [("skipped", r) for r in d.get("skipped_rest", ())]
        todo.sort(key=lambda t: t[1]["line"])
        for kind, item in todo:
            line = item["line"]
            above = [t for ln, t in timed if ln < line]     # выше на скриншоте — выпали позже
            below = [t for ln, t in timed if ln > line]     # ниже — выпали раньше
            # ИСПРАВЛЕНО: границы — время с точностью до секунды (без миллисекунд)
            above = [_qdt_seconds(t) for t in above]
            below = [_qdt_seconds(t) for t in below]
            entries.append({
                "path": path, "file": Path(path).name, "line": line, "kind": kind,
                "item": item, "hi": above[-1] if above else None,
                "lo": below[0] if below else None,
                "timeline": timed,
                "number": 1 + sum(1 for q in pulls if q.get("line", -1) < line)})
    return entries


ShotRow_WARN_BG = QColor(255, 214, 79, 80)      # мягкий жёлтый фон «проверить»


# ---------------------------------------------------------------------------
# НОВОЕ: ЕДИНОЕ построение списка «Распознанные варианты» (вкладки «Скриншот» и «Скриншот оптом»)
# ---------------------------------------------------------------------------
SHOT_ROW_HEIGHT = 64            # высота одной строки списка, px (иконка 40 + поля + поле даты)


SHOT_LIST_VISIBLE_ROWS = 6      # сколько строк должно быть видно без прокрутки (не меньше 5)


def shot_list_min_height() -> int:
    """Минимальная высота списка: SHOT_LIST_VISIBLE_ROWS полных строк + отступы и рамка."""
    return SHOT_LIST_VISIBLE_ROWS * (SHOT_ROW_HEIGHT + 8) + 16


def shot_title(p: dict) -> str:
    """Читаемое название найденной записи: у персонажа и дуги — очищенное название, у
    предметов без названия — стандартное («Потерянный фрагмент (30 шт)»)."""
    info = LOOT_TYPES.get(p["loot"])
    if info is None:
        return p["name"] or "—"
    if p["name"]:
        return p["name"]
    if info["mode"] == "reward":
        qty = info.get("qty")
        detail = pick_item_qty(info, p.get("qty")) if qty else info.get("detail", "")
        return default_reward_name(info["kind"], detail)
    return info["label"]


# ----------------------------------------------------------------------------
# НОВОЕ: окно «Профиль» — аватарка, имя и сводная статистика аккаунта
# ----------------------------------------------------------------------------
PROFILE_AVATAR_KEY = "profile_avatar"      # ключ в settings (на профиль): путь к файлу аватарки


PROFILE_AVATAR_PX = 512                    # сторона сохраняемой квадратной аватарки


PROFILE_AVATAR_FILTER = "Изображения (*.png *.jpg *.jpeg *.webp)"


PROFILE_NEON, PROFILE_PINK, PROFILE_GOLD, PROFILE_MINT = "#00e5ff", "#ff2bd6", "#ffd740", "#7be0a8"


def avatar_dir() -> Path:
    """Папка аватарок рядом с базой данных (создаётся при первом сохранении)."""
    path = resolve_db_path().parent / "avatars"
    path.mkdir(parents=True, exist_ok=True)
    return path


def clear_profile_avatar(db: Database) -> None:
    path = db.get_setting(PROFILE_AVATAR_KEY, "", scoped=True)
    db.set_setting(PROFILE_AVATAR_KEY, "", scoped=True)
    if path:
        try:
            Path(path).unlink(missing_ok=True)
        except OSError:
            pass


def profile_summary(stats: dict, history: list) -> list:
    """Статистика отдельно по пулам (ивентовые, стандартные, дуги) по готовым stats и history."""
    out = []
    for key in BANNERS:
        s = stats.get(key) or _blank_stats()
        rows = [e for e in history if e.get("src") == "wish" and e.get("banner") == key
                and e.get("rarity") == 5 and e.get("kind") in ("main", "cashback")]
        best = min((e for e in rows if _safe_int(e.get("p5")) > 0), key=lambda e: _safe_int(e["p5"]),
                   default=None)
        if key == ARC_BANNER:
            ev = sum(1 for e in rows if arc_kind_by_name(e.get("name"), e.get("arc_kind") or "") == "event")
            pity = [("Стандартная S", s["counter_std"], PITY_ARC_STD),
                    ("Ивентовая S", s["counter_ev"], PITY_ARC_EVENT)]
        else:
            ev, pity = 0, [("Гарант S", s["counter"], PITY_CHAR_HARD)]
        out.append({"key": key, "title": POOL_TITLES[key], "total": s["total"], "s": s["r5"],
                    "avg": fmt_avg(s["pities"]), "best": best, "pity": pity,
                    "ev": ev, "st": len(rows) - ev})
    return out


# ----------------------------------------------------------------------------
# НОВОЕ: система достижений — менеджер (SQLite), всплывающее уведомление, карточки
# ----------------------------------------------------------------------------
APP_SECONDS_KEY = "app_seconds"                # настройка профиля: секунды, проведённые в приложении


MINIGAME_PLAYS_KEY = "minigame_plays"         # настройка профиля: сколько раз запускались мини-игры


MINIGAME_IDS = ("invaders", "arkanoid", "platformer", "asteroids")   # настройка minigame_tried_<id> = "1"


FORTUNE_SPINS_KEY = "fortune_spins"           # настройка профиля: сколько раз прокручено колесо фортуны


ACH_SEEDED_KEY = "achievements_seeded"     # настройка профиля: достижения уже проверялись


ACH_GOLD = "#ffd740"


ACH_TOAST_HOLD_MS = 3600                   # сколько уведомление остаётся на экране


ACHIEVEMENTS = (
    {"id": "first_step", "title": "Первый шаг", "icon": "➤", "metric": "pulls", "target": 1,
     "description": "Импортируйте или добавьте первую крутку"},
    {"id": "hundred_pulls", "title": "Сотня", "icon": "✦", "metric": "pulls", "target": 100,
     "description": "Совершите 100 круток"},
    {"id": "five_hundred_pulls", "title": "Полтысячи", "icon": "◆", "metric": "pulls", "target": 500,
     "description": "Совершите 500 круток"},
    {"id": "thousand_pulls", "title": "Тысячник", "icon": "❂", "metric": "pulls", "target": 1000,
     "description": "Совершите 1000 круток"},
    {"id": "pulls_1500", "title": "Полторы тысячи", "icon": "✸", "metric": "pulls", "target": 1500,
     "description": "Совершите 1500 круток"},
    {"id": "pulls_2000", "title": "Двухтысячник", "icon": "✹", "metric": "pulls", "target": 2000,
     "description": "Совершите 2000 круток"},
    {"id": "s_collector", "title": "Коллекционер S", "icon": "★", "metric": "s_total", "target": 5,
     "description": "Получите 5 предметов S-ранга"},
    {"id": "s_rain", "title": "Звёздный дождь", "icon": "✪", "metric": "s_total", "target": 15,
     "description": "Получите 15 предметов S-ранга"},
    {"id": "lucky", "title": "Фортуна на моей стороне", "icon": "☘", "metric": "lucky", "target": 1,
     "description": "Получите S-ранг, потратив меньше 10 круток гаранта"},
    {"id": "true_pity", "title": "Настоящий гарант", "icon": "♛", "metric": "pity80", "target": 1,
     "description": "Получите S-ранг на гаранте 80 и выше"},
    {"id": "arc_hunter", "title": "Охотник за дугами", "icon": "❖", "metric": "arcs", "target": 10,
     "description": "Соберите 10 уникальных дуг"},
    {"id": "full_arsenal", "title": "Полный арсенал", "icon": "✚", "metric": "unique_s", "target": 10,
     "description": "Откройте 10 уникальных персонажей и дуг в «Стафф»"},
    {"id": "event_fan", "title": "Любимчик ивентов", "icon": "◈", "metric": "event_s", "target": 5,
     "description": "Получите 5 S-рангов с ивентового баннера персонажей"},
    {"id": "classic", "title": "Классика", "icon": "♦", "metric": "std_s", "target": 5,
     "description": "Получите 5 S-рангов со стандартного баннера персонажей"},
    {"id": "crazy", "title": "Чокнутый", "icon": "✺", "metric": "fortune_spins", "target": 100,
     "description": "Прокрутите колесо фортуны 100 раз",
     "reward_title": "Рецепт шаурмы", "reward_text": "RECIPE_SHAWARMA"},
    {"id": "time_1h", "title": "Заглянул на огонёк", "icon": "◔", "metric": "app_seconds", "target": 3600,
     "unit": "time", "description": "Проведите в приложении 1 час"},
    {"id": "time_10h", "title": "Завсегдатай", "icon": "◑", "metric": "app_seconds", "target": 36000,
     "unit": "time", "description": "Проведите в приложении 10 часов"},
    {"id": "time_50h", "title": "Живу здесь", "icon": "◕", "metric": "app_seconds", "target": 180000,
     "unit": "time", "description": "Проведите в приложении 50 часов"},
    {"id": "time_100h", "title": "Хранитель трекера", "icon": "●", "metric": "app_seconds", "target": 360000,
     "unit": "time", "description": "Проведите в приложении 100 часов"},
    {"id": "first_game", "title": "Давай поиграем", "icon": "▶", "metric": "game_plays", "target": 1,
     "description": "Запустите любую мини-игру"},
    {"id": "gamer_25", "title": "Заядлый геймер", "icon": "♜", "metric": "game_plays", "target": 25,
     "description": "Запустите мини-игры 25 раз"},
    {"id": "arcade_100", "title": "Аркадный маньяк", "icon": "♚", "metric": "game_plays", "target": 100,
     "description": "Запустите мини-игры 100 раз"},
    {"id": "all_games", "title": "Мастер на все руки", "icon": "✜", "metric": "games_tried", "target": 4,
     "description": "Попробуйте все 4 мини-игры"},
    {"id": "profile_face", "title": "Лицо профиля", "icon": "☻", "metric": "avatar", "target": 1,
     "description": "Установите аватарку профиля"},
)


def achievement_metrics(db: Database, stats: dict, history: list) -> dict:
    """Числа, по которым считается прогресс достижений активного профиля."""
    wishes = [e for e in history if e.get("src") == "wish"]
    s_rows = [e for e in wishes if e.get("rarity") == 5 and e.get("kind") in ("main", "cashback")]

    def named(e):
        return bool(e.get("name")) and e["name"] not in ("Персонаж", "Дуга")

    pities = [_safe_int(e.get("p5")) for e in s_rows if _safe_int(e.get("p5")) > 0]
    arcs = {e["name"].lower() for e in wishes if e.get("banner") == ARC_BANNER and named(e)
            and e.get("rarity") in (4, 5) and e.get("kind") in ("main", "cashback")}
    avatar_path = db.get_setting(PROFILE_AVATAR_KEY, "", scoped=True)
    return {
        "pulls": sum(s["total"] for s in stats.values()),
        "s_total": sum(s["r5"] for s in stats.values()),
        "lucky": int(any(p < 10 for p in pities)),
        "pity80": int(any(p >= 80 for p in pities)),
        "arcs": len(arcs),
        "unique_s": len({e["name"].lower() for e in s_rows if named(e)}),
        "event_s": sum(1 for e in s_rows if e.get("banner") == EVENT_BANNER),
        "std_s": sum(1 for e in s_rows if e.get("banner") == STANDARD_BANNER),
        "avatar": int(bool(avatar_path) and Path(avatar_path).is_file()),
        "fortune_spins": _safe_int(db.get_setting(FORTUNE_SPINS_KEY, "0", scoped=True)),
        "app_seconds": _safe_int(db.get_setting(APP_SECONDS_KEY, "0", scoped=True)),
        "game_plays": _safe_int(db.get_setting(MINIGAME_PLAYS_KEY, "0", scoped=True)),
        "games_tried": sum(1 for g in MINIGAME_IDS
                           if db.get_setting(f"minigame_tried_{g}", "0", scoped=True) == "1"),
    }


class AchievementManager:
    """Определения достижений + прогресс профиля в таблице achievements (SQLite)."""

    def __init__(self, db: Database):
        self.db = db
        try:
            with db.conn:
                db.conn.execute("""CREATE TABLE IF NOT EXISTS achievements (
                                       profile_id INTEGER NOT NULL,
                                       achievement_id TEXT NOT NULL,
                                       title TEXT NOT NULL DEFAULT '',
                                       description TEXT NOT NULL DEFAULT '',
                                       icon TEXT NOT NULL DEFAULT '',
                                       is_unlocked INTEGER NOT NULL DEFAULT 0,
                                       unlocked_at TEXT NOT NULL DEFAULT '',
                                       progress_current INTEGER NOT NULL DEFAULT 0,
                                       progress_target INTEGER NOT NULL DEFAULT 1,
                                       PRIMARY KEY (profile_id, achievement_id)
                                   )""")
        except sqlite3.Error:
            traceback.print_exc()

    def _stored(self, pid: int) -> dict:
        try:
            rows = self.db.conn.execute(
                "SELECT achievement_id, is_unlocked, unlocked_at, progress_current, progress_target "
                "FROM achievements WHERE profile_id = ?", (pid,)).fetchall()
        except sqlite3.Error:
            return {}
        return {r["achievement_id"]: r for r in rows}

    def evaluate(self, stats: dict, history: list) -> list:
        """Пересчитывает прогресс, сохраняет его и возвращает только что полученные достижения.
        Если у профиля уже были данные при первой проверке, старые достижения открываются тихо."""
        pid = self.db.profile_id
        if not pid:
            return []
        metrics = achievement_metrics(self.db, stats, history)
        stored = self._stored(pid)
        seeded = self.db.get_setting(ACH_SEEDED_KEY, "0", scoped=True) == "1"
        silent = not seeded and (metrics["pulls"] > 0 or metrics["avatar"] > 0)
        now = datetime.now().strftime("%Y-%m-%d %H:%M")
        rows, fresh = [], []
        for d in ACHIEVEMENTS:
            old = stored.get(d["id"])
            was = bool(old and old["is_unlocked"])
            current = min(_safe_int(metrics.get(d["metric"], 0)), d["target"])
            done = was or current >= d["target"]
            at = old["unlocked_at"] if was else (now if done else "")
            rows.append((pid, d["id"], d["title"], d["description"], d["icon"], int(done), at,
                         d["target"] if done else current, d["target"]))
            if done and not was and not silent and not (old is None and seeded):
                fresh.append(d)
        try:
            with self.db.conn:
                self.db.conn.executemany(
                    "INSERT INTO achievements (profile_id, achievement_id, title, description, icon, "
                    "is_unlocked, unlocked_at, progress_current, progress_target) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?) "
                    "ON CONFLICT(profile_id, achievement_id) DO UPDATE SET title = excluded.title, "
                    "description = excluded.description, icon = excluded.icon, "
                    "is_unlocked = excluded.is_unlocked, unlocked_at = excluded.unlocked_at, "
                    "progress_current = excluded.progress_current, "
                    "progress_target = excluded.progress_target", rows)
        except sqlite3.Error:
            traceback.print_exc()
            return []
        if not seeded:
            self.db.set_setting(ACH_SEEDED_KEY, "1", scoped=True)
        return fresh

    def all(self) -> list:
        """Все достижения активного профиля в порядке определения."""
        stored = self._stored(self.db.profile_id)
        out = []
        for d in ACHIEVEMENTS:
            r = stored.get(d["id"])
            out.append({"id": d["id"], "title": d["title"], "description": d["description"],
                        "icon": d["icon"], "is_unlocked": bool(r and r["is_unlocked"]),
                        "unlocked_at": r["unlocked_at"] if r else "",
                        "progress_current": _safe_int(r["progress_current"]) if r else 0,
                        "progress_target": d["target"], "unit": d.get("unit", ""),
                        "reward_title": d.get("reward_title", ""),
                        "reward_text": RECIPE_SHAWARMA if d.get("reward_text") == "RECIPE_SHAWARMA" else ""})
        return out


_ACH_SFX_KEEP = []


def _achievement_sound_file() -> Path:
    """Короткий победный перезвон (WAV синтезируется один раз во временной папке)."""
    folder = Path(tempfile.gettempdir()) / "nte_gacha_ach_v1"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / "unlock.wav"
    if not path.exists() or path.stat().st_size < 64:
        rate = 22050
        notes = ((659.3, 0.00), (830.6, 0.10), (987.8, 0.20), (1318.5, 0.32))
        samples = []
        for i in range(int(rate * 1.1)):
            t, v = i / rate, 0.0
            for freq, start in notes:
                if t >= start:
                    dt = t - start
                    v += (math.sin(2 * math.pi * freq * dt) + 0.3 * math.sin(4 * math.pi * freq * dt)) \
                         * math.exp(-4.0 * dt) * min(1.0, dt * 200)
            samples.append(v)
        top = max((abs(v) for v in samples), default=1.0) or 1.0
        _fortune_write_wav(path, [v * 0.85 / top for v in samples], rate)
    return path


def fmt_ach_value(value: int, unit: str = "") -> str:
    """Значение прогресса для карточки: время — «3 ч 05 мин», остальное — число."""
    if unit != "time":
        return str(value)
    hours, minutes = divmod(max(0, int(value)) // 60, 60)
    return f"{hours} ч {minutes:02d} мин" if hours else f"{minutes} мин"


RECIPE_SHAWARMA = """Ингредиенты (на 2 штуки)

• Тонкий армянский лаваш — 2 шт.
• Куриное филе или бедро — 300 г
• Капуста (белокочанная или пекинская) — 100 г
• Огурец — 1 шт.
• Помидор — 1 шт.
• Соус: 3 ст. л. сметаны + 2 ст. л. майонеза + 1–2 зубчика чеснока (через пресс) + зелень, соль и перец по вкусу.

Приготовление

1. Подготовьте соус: смешайте сметану, майонез, измельченный чеснок, мелко нарезанную зелень и щепотку соли.
2. Пожарьте мясо: курицу нарежьте небольшими кусочками, посолите, добавьте специи (паприку, сушеный чеснок, перец) и обжарьте на сковороде до золотистой корочки (7–10 минут).
3. Нарежьте овощи: капусту мелко нашинкуйте (и немного помните руками), огурец и помидор нарежьте тонкой соломкой или ломтиками.
4. Соберите шаурму:
   • Разложите лаваш, смажьте центр соусом.
   • Выложите капусту, затем курицу, огурцы и помидоры.
   • Добавьте еще немного соуса сверху.
5. Заверните: подогните нижний и боковые края лаваша и скрутите в плотный рулет.
6. Обжарьте: подрумяньте шаурму на сухой сковороде (лучше гриль) по 1–2 минуты с каждой стороны до хрустящей корочки."""


# ----------------------------------------------------------------------------
# НОВОЕ: вкладка «Симуляция» — рост характеристик, возвышение, защита и сопротивление врага
# ----------------------------------------------------------------------------
SIM_ELEMENTS = ("Космос", "Лакшана", "Анима", "Хаос", "Инкантация", "Психея")


SIM_JSON_NAME = "simulation_data.json"      # необязательный файл: свои базовые статы


SIM_PORTRAIT_DIRS = ("portraits", "full", "art")


SIM_PORTRAIT_SUFFIXES = ("", "_full", "_portrait", "_art", "_splash", "-full", "-portrait", "-art")


SIM_FLAT_STEP = 50.0                        # шаг для плоской АТК в таблице весов


SIM_SETTING_CHAR, SIM_SETTING_ARC = "sim_character", "sim_weapon"


SIM_NO_WEAPON = "Без дуги"


# --- модель прогрессии (nte_character_progression.md) ---
SIM_MAX_LEVEL = 80


SIM_ASC_LEVELS = (40, 50, 60, 70)           # пороги возвышения


SIM_BETAS = (0.12, 0.14, 0.16, 0.18)        # скачок характеристик на i-м возвышении


SIM_HIDDEN_BONUS = 12.0                     # скрытый бонус S-ранга, % за этап


SIM_HIDDEN_STAGES = (2, 4)                  # этапы возвышения, открывающие скрытый бонус


SIM_BASE_CRIT, SIM_BASE_CRIT_DMG = 5.0, 50.0


SIM_BASE_STAMINA, SIM_BASE_REGEN = 240, 100


# фазы возвышения (nte_complete_math_guide.md): (фаза, характеристика, бонус %), накопительно
SIM_PHASE_AFFIXES = ((2, "element_dmg", 8.0), (4, "crit_dmg", 12.0), (6, "dmg", 10.0))


SIM_PHASE_NAMES = {"element_dmg": "стихийный урон", "crit_dmg": "крит. урон", "dmg": "общий урон"}


SIM_HIDDEN_KINDS = (("Стихийный урон", "element_dmg"), ("Шанс крита", "crit"))


# роль: (название, K_hp, K_atk, K_def, приоритетный скрытый стат)
SIM_ROLES = {
    "dps": ("Основной урон", 1.0, 1.4, 0.8, "Крит. урон / Стихийный урон"),
    "sub": ("Саб-урон / энейблер", 1.1, 1.2, 0.9, "Скорость восполнения энергии"),
    "support": ("Поддержка / бафер", 1.2, 0.9, 1.1, "Общий процентный урон %"),
    "tank": ("Танк / щитовик", 1.5, 0.7, 1.4, "Эффективность щита / Защита %"),
}


SIM_ROLE_BY_NAME = {"Наналли": "dps", "Лакримоза": "dps", "Шинку": "sub", "Минт": "support",
                    "Адлер": "support", "Фадия": "tank", "Хатор": "tank"}


# Значения на 1-м уровне по рангу (если нет данных в simulation_data.json).
SIM_CHAR_DEFAULTS = {
    5: {"element": "Космос", "hidden": "element_dmg", "hp": 800.0, "atk": 120.0, "def": 70.0,
        "alpha": 0.05, "gamma": 0.97, "dmg": 0.0},
    4: {"element": "Космос", "hidden": "element_dmg", "hp": 700.0, "atk": 100.0, "def": 60.0,
        "alpha": 0.05, "gamma": 0.97, "dmg": 0.0},
}


SIM_WEAPON_DEFAULTS = {
    5: {"atk": 100.0, "alpha": 0.05, "gamma": 0.97, "atk_pct": 20.0, "crit": 0.0, "crit_dmg": 0.0,
        "dmg": 0.0, "element_dmg": 0.0},
    4: {"atk": 80.0, "alpha": 0.05, "gamma": 0.97, "atk_pct": 12.0, "crit": 0.0, "crit_dmg": 0.0,
        "dmg": 0.0, "element_dmg": 0.0},
    3: {"atk": 60.0, "alpha": 0.05, "gamma": 0.97, "atk_pct": 8.0, "crit": 0.0, "crit_dmg": 0.0,
        "dmg": 0.0, "element_dmg": 0.0},
}


# (ключ, подпись, минимум, максимум, знаков, шаг, значение по умолчанию, суффикс, группа)
SIM_FIELDS = (
    ("level", "Уровень персонажа (L)", 1, 80, 0, 1, 80, "", "char"),
    ("ascension", "Ранг возвышения (A)", 0, 4, 0, 1, 4, "", "char"),
    ("weapon_level", "Уровень дуги (L_орк)", 1, 80, 0, 1, 80, "", "char"),
    ("phase", "Фаза возвышения (аффиксы 2/4/6)", 0, 6, 0, 1, 0, "", "char"),
    ("skill", "% навыка (базовый)", 0, 20000, 1, 5, 100, " %", "char"),
    ("skill_level", "Уровень навыка (L_skill)", 1, 20, 0, 1, 1, "", "char"),
    ("skill_k", "Рост навыка K_skill", 0, 50, 1, 0.5, 6.5, " % за ур.", "char"),
    ("atk_pct", "АТК % (модули)", 0, 2000, 1, 1, 0, " %", "char"),
    ("atk_flat", "АТК плоская (модули)", 0, 99999, 0, 10, 0, "", "char"),
    ("dmg", "Общий урон % (модули)", 0, 2000, 1, 1, 0, " %", "char"),
    ("element_dmg", "Урон стихии % (модули)", 0, 2000, 1, 1, 0, " %", "char"),
    ("crit", "Шанс крита % (модули)", 0, 100, 1, 1, 0, " %", "char"),
    ("crit_dmg", "Крит. урон % (модули)", 0, 2000, 1, 1, 0, " %", "char"),
    ("enemy_level", "Уровень врага", 1, 200, 0, 1, 80, "", "enemy"),
    ("resist", "Базовый резист врага %", -100, 200, 1, 1, 10, " %", "enemy"),
    ("shred", "Срез резиста %", 0, 200, 1, 1, 0, " %", "enemy"),
    ("def_shred", "Срез защиты врага %", 0, 100, 1, 1, 0, " %", "enemy"),
    ("def_ignore", "Игнор защиты %", 0, 100, 1, 1, 0, " %", "enemy"),
    ("under_level", "Уровень отстающего персонажа", 1, 80, 0, 1, 60, "", "scenario"),
    ("boss_level", "Уровень эндгейм-босса", 1, 200, 0, 1, 90, "", "scenario"),
)


# ползунки рядом с полями: ключ -> (минимум, максимум, шаг)
SIM_SLIDERS = {"level": (1, 80, 1), "ascension": (0, 4, 1), "weapon_level": (1, 80, 1),
               "phase": (0, 6, 1), "skill_level": (1, 20, 1),
               "skill": (0, 2000, 5), "enemy_level": (1, 200, 1)}


SIM_STYLE = """
QDoubleSpinBox { background-color: rgba(8, 10, 24, 150); border: 1px solid rgba(255, 255, 255, 45);
                 border-radius: 8px; padding: 4px 8px; min-width: 96px; }
QDoubleSpinBox:focus { border-color: #ffd740; }
QFrame#simPortrait { background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                     stop:0 rgba(255, 255, 255, 26), stop:1 rgba(255, 255, 255, 8));
                     border: 1px solid rgba(255, 255, 255, 50); border-radius: 16px; }
QLabel#simName { font-size: 22px; font-weight: bold; color: #ffd740; }
QLabel#simSub { color: #b4b9c9; font-size: 13px; }
QLabel#simHint { color: #b4b9c9; font-size: 12px; }
QLabel#simIdeal { font-size: 14px; font-weight: bold; }
QSlider::groove:horizontal { height: 6px; border-radius: 3px; background: rgba(255, 255, 255, 40); }
QSlider::sub-page:horizontal { border-radius: 3px; background: rgba(255, 215, 64, 200); }
QSlider::handle:horizontal { width: 16px; margin: -6px 0; border-radius: 8px; background: #ffd740; }
"""


def _sim_clamp(value, lo, hi):
    return max(lo, min(hi, value))


def sim_required_ascension(level: int) -> int:
    """Минимальный ранг возвышения, нужный для достижения уровня L."""
    return sum(1 for t in SIM_ASC_LEVELS if level > t)


def sim_level_cap(asc: int) -> int:
    """Максимальный уровень при ранге возвышения A (40 / 50 / 60 / 70 / 80)."""
    return SIM_ASC_LEVELS[asc] if asc < len(SIM_ASC_LEVELS) else SIM_MAX_LEVEL


def sim_stat_at_level(stat1: float, alpha: float, gamma: float, level: float, asc: int,
                      betas=SIM_BETAS) -> float:
    """Stat_база(L) = Stat_ур.1 × (1 + α × (L − 1)^γ) + ΔStat_возв,
    ΔStat_возв = Σ(Stat_ур.1 × β_i) для i = 1..A."""
    level = _sim_clamp(level, 1, SIM_MAX_LEVEL)
    asc = int(_sim_clamp(asc, 0, len(SIM_ASC_LEVELS)))
    growth = stat1 * (1 + alpha * (level - 1) ** gamma)
    return growth + sum(stat1 * b for b in betas[:asc])


def sim_hidden_bonus(asc: int, rank: int) -> float:
    """Скрытый бонус возвышения: только S-ранг, +12 % на 2-м и 4-м этапах (накопительно)."""
    if rank < 5:
        return 0.0
    return SIM_HIDDEN_BONUS * sum(1 for s in SIM_HIDDEN_STAGES if asc >= s)


def sim_character_stats(prof: dict, role: str, level: int, asc: int) -> dict:
    """HP / АТК / ЗАЩ персонажа на уровне L: Stat_итого = Stat_база(L) × K_роль."""
    _name, k_hp, k_atk, k_def, _hidden = SIM_ROLES.get(role, SIM_ROLES["dps"])
    betas = prof.get("betas")
    if not (isinstance(betas, (list, tuple)) and len(betas) >= len(SIM_BETAS)):
        betas = SIM_BETAS
    out = {}
    for key, k in (("hp", k_hp), ("atk", k_atk), ("def", k_def)):
        out[key] = sim_stat_at_level(prof[key], prof["alpha"], prof["gamma"], level, asc, betas) * k
    return out


def sim_weapon_atk(wp: dict, level: int) -> float:
    """АТК дуги на уровне L_орк (без возвышений)."""
    return sim_stat_at_level(wp["atk"], wp["alpha"], wp["gamma"], level, 0)


def sim_skill_ratio(base_ratio: float, k_skill: float, skill_level: float) -> float:
    """Skill_Ratio(L_skill) = Skill_Ratio_base × (1 + K_skill × (L_skill − 1)), K в процентах."""
    return base_ratio * (1 + k_skill / 100.0 * (max(1.0, skill_level) - 1))


def sim_phase_bonuses(phase: int) -> dict:
    """Аффиксы фаз возвышения 2 / 4 / 6: +8 % стихии, +12 % крит. урона, +10 % общего урона."""
    out = {"element_dmg": 0.0, "crit_dmg": 0.0, "dmg": 0.0}
    for need, key, value in SIM_PHASE_AFFIXES:
        if phase >= need:
            out[key] += value
    return out


def sim_defense_multiplier(char_level, enemy_level, def_shred=0.0, def_ignore=0.0) -> float:
    """(L + 100) / (L + 100 + (Lвр + 100) × (1 − срез/игнор))."""
    reduction = _sim_clamp((def_shred + def_ignore) / 100.0, 0.0, 1.0)
    numerator = char_level + 100.0
    return numerator / (numerator + (enemy_level + 100.0) * (1.0 - reduction))


def sim_resist_multiplier(resist, shred) -> float:
    """Сопротивление врага с порогами: ≥ 75 % — 1/(1 + 4x), < 0 — 1 − x/2, иначе 1 − x."""
    x = (resist - shred) / 100.0
    if x >= 0.75:
        return 1.0 / (1.0 + x * 4.0)
    if x < 0:
        return 1.0 - x / 2.0
    return 1.0 - x


def sim_calculate(p: dict) -> dict:
    """Мультипликативная модель урона NTE (формулы из документов)."""
    atk = p["atk_base"] * (1 + p["atk_pct"] / 100) + p["atk_flat"]
    base = atk * p["skill"] / 100
    with_bonus = base * (1 + (p["dmg"] + p["element_dmg"]) / 100)
    crit_rate = _sim_clamp(p["crit"], 0.0, 100.0)
    crit_mult = 1 + (crit_rate / 100) * (p["crit_dmg"] / 100)
    average = with_bonus * crit_mult
    resist_factor = sim_resist_multiplier(p["resist"], p["shred"])
    defense_factor = sim_defense_multiplier(p["level"], p["enemy_level"],
                                            p.get("def_shred", 0.0), p.get("def_ignore", 0.0))
    mitigation = resist_factor * defense_factor
    return {
        "atk": atk, "base": base, "with_bonus": with_bonus, "crit_mult": crit_mult,
        "average": average, "resist_factor": resist_factor, "defense_factor": defense_factor,
        "final": average * mitigation,
        "crit_hit": with_bonus * (1 + p["crit_dmg"] / 100) * mitigation,
        "crit_value": 2 * p["crit"] + p["crit_dmg"],
        "ideal_crit": min(100.0, p["crit_dmg"] / 2),
    }


def sim_marginal(p: dict, step: float) -> dict:
    """Прирост по формулам из документа: АТК % и стихия (в процентах)."""
    atk_gain = step / (100 + p["atk_pct"]) * 100
    elem_gain = step / (100 + p["dmg"] + p["element_dmg"]) * 100
    return {"atk": atk_gain, "element": elem_gain}


def sim_stat_weights(p: dict, step: float) -> list:
    """Реальный прирост итогового урона от добавки к каждой характеристике.
    Возвращает [(подпись, шаг, прирост %, вес относительно АТК %)]."""
    base_final = sim_calculate(p)["final"]
    stats = (("atk_pct", "АТК %", step), ("atk_flat", "АТК плоская", SIM_FLAT_STEP),
             ("element_dmg", "Урон стихии %", step), ("dmg", "Общий урон %", step),
             ("crit", "Шанс крита %", step), ("crit_dmg", "Крит. урон %", step),
             ("shred", "Срез резиста %", step), ("def_shred", "Срез защиты %", step))
    gains = []
    for key, label, delta in stats:
        q = dict(p)
        q[key] = q.get(key, 0.0) + delta
        gain = (sim_calculate(q)["final"] / base_final - 1) * 100 if base_final > 0 else 0.0
        gains.append((label, delta, gain))
    ref = gains[0][2]
    return [(label, delta, gain, (gain / ref if ref > 0 else 0.0)) for label, delta, gain in gains]


def sim_load_overrides() -> dict:
    """Читает simulation_data.json (рядом с main.py, в assets/ или рядом с базой).
    Любая ошибка файла игнорируется."""
    roots = [app_dir()] + ([Path(_DATA_DIR)] if _DATA_DIR is not None else [])
    for root in roots:
        for path in (root / SIM_JSON_NAME, root / "assets" / SIM_JSON_NAME):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if isinstance(data, dict):
                return data
    return {}


def find_portrait_path(name: str):
    """Ищет арт персонажа в полный рост: portraits/, full/, art/ (и файлы с суффиксами
    _full, _portrait, _art), затем обычную иконку. Возвращает Path или None."""
    roots = [app_dir()] + ([Path(_DATA_DIR)] if _DATA_DIR is not None else [])
    portrait_dirs = [root / base / sub for root in roots for base in ICON_DIR_NAMES
                     for sub in SIM_PORTRAIT_DIRS]
    variants = _name_variants(name)
    for dirs, suffixes in ((portrait_dirs, SIM_PORTRAIT_SUFFIXES),
                           (asset_dirs(), SIM_PORTRAIT_SUFFIXES[1:])):
        for d in dirs:
            if not d.is_dir():
                continue
            for v in variants:
                for s in suffixes:
                    for ext in ICON_EXTS:
                        f = d / (v + s + ext)
                        if f.is_file():
                            return f
    return find_icon_path(name)


# =====================================================================================
# НОВОЕ: встроенная мини-игра «Космические захватчики» (кнопка «Поиграй 🎮» на вкладке
# «Скриншоты разом»). Логика игры (InvadersEngine) не зависит от Qt и работает по
# времени кадра (dt), поэтому скорость не зависит от частоты таймера. Виджет рисует кадр
# в paintEvent и обновляется таймером ~60 кадров/с в основном потоке: игра очень лёгкая
# и не мешает фоновым потокам OCR.
# =====================================================================================
MINIGAME_INVADERS_KEY = "minigame_invaders_highscore"


# =====================================================================================
# НОВОЕ: звуковые эффекты мини-игр. Все звуки синтезируются при первом запуске (WAV во
# временной папке) — внешние файлы не нужны. Воспроизведение — QSoundEffect; при любом
# сбое мультимедиа игры работают в тишине. Движки игр вызывают self._snd("имя") — это
# обычный колбэк (engine.sfx), поэтому логика остаётся независимой от Qt.
# =====================================================================================
MINIGAME_SOUND_OFF_KEY = "minigame_sound_muted"        # 0 / отсутствует — звук включён, 1 — выключен


GAME_SFX_RATE = 22050


GAME_SFX_LOOPS = frozenset({"thrust"})                 # зацикленные звуки (гул двигателя)


def _sfx_sweep(f0, f1, dur, shape="square", vol=0.6, decay=1.5, duty=0.5):
    """Тон с плавным изменением частоты f0 -> f1 и затуханием."""
    n = max(1, int(GAME_SFX_RATE * dur))
    out, phase = [], 0.0
    att = GAME_SFX_RATE * 0.003
    rel = GAME_SFX_RATE * 0.006
    for i in range(n):
        k = i / max(1, n - 1)
        phase += (f0 + (f1 - f0) * k) / GAME_SFX_RATE
        ph = phase % 1.0
        if shape == "square":
            v = 1.0 if ph < duty else -1.0
        elif shape == "tri":
            v = 4.0 * abs(ph - 0.5) - 1.0
        elif shape == "saw":
            v = 2.0 * ph - 1.0
        else:
            v = math.sin(math.tau * ph)
        env = (1.0 - k) ** decay if decay else 1.0
        out.append(v * vol * env * min(1.0, i / att) * min(1.0, (n - i) / rel))
    return out


def _sfx_noise(dur, vol=0.6, decay=2.0, smooth0=0.0, smooth1=None, seed=1):
    """Шум (взрывы, удары); smooth — «глухость» (0 — резкий, ближе к 1 — низкий гул)."""
    rnd = random.Random(seed)
    n = max(1, int(GAME_SFX_RATE * dur))
    smooth1 = smooth0 if smooth1 is None else smooth1
    out, last = [], 0.0
    rel = GAME_SFX_RATE * 0.006
    for i in range(n):
        k = i / max(1, n - 1)
        s = smooth0 + (smooth1 - smooth0) * k
        last = last * s + rnd.uniform(-1.0, 1.0) * (1.0 - s)
        gain = 1.0 / max(0.15, 1.0 - s) ** 0.5 if s else 1.0
        out.append(last * gain * vol * (1.0 - k) ** decay * min(1.0, (n - i) / rel))
    return out


def _sfx_seq(*parts):
    out = []
    for part in parts:
        out.extend(part)
    return out


def _sfx_mix(*parts):
    n = max(len(p) for p in parts)
    return [sum(p[i] for p in parts if i < len(p)) for i in range(n)]


def _sfx_notes(freqs, each, shape="square", vol=0.35, last=None, decay=0.8):
    parts = []
    for i, f in enumerate(freqs):
        d = last if (last and i == len(freqs) - 1) else each
        parts.append(_sfx_sweep(f, f, d, shape, vol, decay if i == len(freqs) - 1 else 0.3))
    return _sfx_seq(*parts)


def _sfx_rumble():
    """Бесшовный гул двигателя (целое число периодов -> без щелчка при зацикливании)."""
    n = int(GAME_SFX_RATE * 0.4)
    out = []
    for i in range(n):
        t = i / GAME_SFX_RATE
        saw = 2.0 * ((30.0 * t) % 1.0) - 1.0
        out.append(0.45 * math.sin(math.tau * 60 * t) + 0.3 * math.sin(math.tau * 90 * t + 1.0)
                   + 0.12 * math.sin(math.tau * 120 * t) + 0.13 * saw)
    return out


def _game_sfx_samples() -> dict:
    return {
        # Марио / общие
        "jump": _sfx_sweep(260, 760, 0.17, "square", 0.45, 1.0),
        "block": _sfx_mix(_sfx_sweep(230, 110, 0.09, "square", 0.5, 1.0), _sfx_noise(0.05, 0.25, 2.0, 0.5, seed=3)),
        "item": _sfx_notes((392, 523, 659, 784, 988), 0.045, "tri", 0.5, last=0.12),
        "coin": _sfx_seq(_sfx_sweep(988, 988, 0.06, "square", 0.32, 0.0),
                         _sfx_sweep(1319, 1319, 0.26, "square", 0.32, 2.0)),
        "powerup": _sfx_notes((262, 330, 392, 523, 659, 784, 1047, 1319), 0.05, "square", 0.32, last=0.2),
        "fireball": _sfx_mix(_sfx_sweep(950, 280, 0.15, "square", 0.38, 1.5, 0.25),
                             _sfx_noise(0.1, 0.18, 2.0, 0.2, seed=5)),
        "stomp": _sfx_seq(_sfx_sweep(420, 140, 0.09, "square", 0.5, 0.8), _sfx_sweep(180, 90, 0.07, "tri", 0.45, 1.5)),
        "death": _sfx_seq(_sfx_notes((523, 392, 330), 0.12, "tri", 0.5, last=0.14),
                          _sfx_sweep(320, 60, 0.55, "square", 0.38, 1.2)),
        "gameover": _sfx_seq(_sfx_notes((392, 370, 349, 330, 294), 0.16, "square", 0.34),
                             _sfx_sweep(262, 196, 0.6, "tri", 0.5, 1.4)),
        "win": _sfx_notes((523, 659, 784, 1047, 784, 1047), 0.09, "square", 0.34, last=0.4),
        # Астероиды / захватчики
        "shoot": _sfx_sweep(1500, 320, 0.13, "saw", 0.36, 1.4),
        "explode": _sfx_mix(_sfx_noise(0.55, 0.85, 2.2, 0.72, 0.93, seed=7),
                            _sfx_sweep(130, 40, 0.5, "square", 0.3, 1.5)),
        "explode_small": _sfx_noise(0.22, 0.65, 2.0, 0.35, 0.7, seed=9),
        "hit": _sfx_mix(_sfx_noise(0.35, 0.6, 1.8, 0.55, 0.85, seed=11), _sfx_sweep(320, 60, 0.32, "saw", 0.4, 1.2)),
        "ufo": _sfx_mix(_sfx_sweep(220, 1250, 0.32, "saw", 0.34, 0.8), _sfx_noise(0.25, 0.3, 1.5, 0.3, seed=13)),
        "thrust": _sfx_rumble(),
        # Арканоид
        "paddle": _sfx_sweep(440, 440, 0.07, "square", 0.42, 1.5),
        "wall": _sfx_sweep(220, 220, 0.045, "square", 0.32, 1.0),
        "brick": _sfx_sweep(660, 900, 0.08, "square", 0.42, 1.5),
    }


_GAME_SFX_FILES = {}


def _game_sfx_files() -> dict:
    """Пишет (один раз) WAV-файлы звуков во временную папку и возвращает {имя: путь}."""
    if _GAME_SFX_FILES:
        return _GAME_SFX_FILES
    folder = Path(tempfile.gettempdir()) / "nte_gacha_game_sfx_v1"
    folder.mkdir(parents=True, exist_ok=True)
    for name, samples in _game_sfx_samples().items():
        path = folder / f"{name}.wav"
        if not path.exists() or path.stat().st_size < 64:
            top = max((abs(v) for v in samples), default=1.0) or 1.0
            _fortune_write_wav(path, [v * min(1.0, 0.9 / top) for v in samples], GAME_SFX_RATE)
        _GAME_SFX_FILES[name] = path
    return _GAME_SFX_FILES


class GameSfxMixin:
    """Подмешивается в движки игр: engine.sfx — колбэк звука (None — тишина)."""
    sfx = None

    def _snd(self, name: str):
        cb = self.sfx
        if cb is not None:
            try:
                cb(name)
            except Exception:  # noqa: BLE001
                pass


# Пиксельные спрайты (# — закрашенный пиксель). У пришельцев по два кадра анимации.
SPRITE_SQUID = (
    ("...##...", "..####..", ".######.", "##.##.##", "########", ".#.##.#.", "#......#", ".#....#."),
    ("...##...", "..####..", ".######.", "##.##.##", "########", "..#..#..", ".#.##.#.", "#.#..#.#"),
)


SPRITE_CRAB = (
    ("..#.....#..", "...#...#...", "..#######..", ".##.###.##.",
     "###########", "#.#######.#", "#.#.....#.#", "...##.##..."),
    ("..#.....#..", "#..#...#..#", "#.#######.#", "###.###.###",
     "###########", ".#########.", "..#.....#..", ".#.......#."),
)


SPRITE_OCTOPUS = (
    ("....####....", ".##########.", "############", "###..##..###",
     "############", "...##..##...", "..##.##.##..", "##........##"),
    ("....####....", ".##########.", "############", "###..##..###",
     "############", "..###..###..", ".##..##..##.", "..##....##.."),
)


SPRITE_PLAYER = (
    "......#......", ".....###.....", ".....###.....", ".###########.",
    "#############", "#############", "#############", "#############",
)


SPRITE_UFO = (
    ".....######.....", "...##########...", "..############..", ".##.##.##.##.##.",
    "################", "..###..##..###..", "...#........#...",
)


SHIELD_PATTERN = (
    "..#######..", ".#########.", "###########", "###########",
    "###########", "###.....###", "###.....###", "###.....###",
)


class InvadersEngine(GameSfxMixin):
    """Чистая логика «Космических захватчиков» (без Qt). Координаты — в логических пикселях
    поля W×H; виджет сам масштабирует поле под размер окна."""

    W, H = 480, 560
    COLS, ROWS = 8, 5
    DX, DY = 44, 34                  # шаг сетки пришельцев
    ALIEN_W, ALIEN_H = 36, 24
    PLAYER_W, PLAYER_H, PLAYER_Y = 39, 24, 516
    TOP = 48                         # высота строки со счётом
    SHIELD_Y, SHIELD_CELL = 428, 5
    POINTS = (30, 20, 20, 10, 10)    # очки за ряд сверху вниз

    def __init__(self, high_score: int = 0):
        self.high = max(0, int(high_score))
        self.state = "ready"         # ready / playing / paused / over
        self.new_game()

    # ---------- подготовка ----------
    def new_game(self):
        self.score = 0
        self.lives = 3
        self.level = 1
        self.record_beaten = False
        self.player_x = self.W / 2
        self.bullets, self.ebullets, self.blasts = [], [], []
        self.cooldown = 0.0
        self.invuln = 0.0
        self.banner = 0.0
        self.ufo = None
        self.ufo_t = random.uniform(10, 18)
        self.fire_t = 1.0
        self.spawn_wave()
        self.make_shields()

    def spawn_wave(self):
        self.aliens = [{"c": c, "r": r, "alive": True}
                       for r in range(self.ROWS) for c in range(self.COLS)]
        self.total = len(self.aliens)
        self.ox = (self.W - ((self.COLS - 1) * self.DX + self.ALIEN_W)) / 2
        self.oy = self.TOP + 26 + min(self.level - 1, 5) * 14
        self.dir = 1
        self.anim = 0.0
        self.bullets.clear()
        self.ebullets.clear()

    def make_shields(self):
        cell = self.SHIELD_CELL
        width = len(SHIELD_PATTERN[0]) * cell
        self.shields = []
        for i in range(4):
            x = self.W / 4 * (i + 0.5) - width / 2
            cells = {(cx, cy) for cy, row in enumerate(SHIELD_PATTERN)
                     for cx, ch in enumerate(row) if ch == "#"}
            self.shields.append({"x": x, "y": self.SHIELD_Y, "cells": cells})

    def start(self):
        if self.state in ("ready", "over"):
            if self.state == "over":
                self.new_game()
            self.state = "playing"

    def pause(self):
        if self.state == "playing":
            self.state = "paused"

    def resume(self):
        if self.state == "paused":
            self.state = "playing"

    # ---------- вспомогательное ----------
    def alien_pos(self, a):
        return self.ox + a["c"] * self.DX, self.oy + a["r"] * self.DY

    def alive_aliens(self):
        return [a for a in self.aliens if a["alive"]]

    @staticmethod
    def _hit(ax, ay, aw, ah, bx, by, bw, bh):
        return ax < bx + bw and bx < ax + aw and ay < by + bh and by < ay + ah

    def _add_score(self, pts):
        self.score += pts
        if self.score > self.high:
            self.high = self.score
            self.record_beaten = True

    def _shield_hit(self, bx, by, bw, bh, erode=True) -> bool:
        """Попадание в щит: разрушает клетку (и соседнюю) под пулей."""
        cell = self.SHIELD_CELL
        for sh in self.shields:
            w, h = len(SHIELD_PATTERN[0]) * cell, len(SHIELD_PATTERN) * cell
            if not self._hit(sh["x"], sh["y"], w, h, bx, by, bw, bh):
                continue
            for cx, cy in list(sh["cells"]):
                if self._hit(sh["x"] + cx * cell, sh["y"] + cy * cell, cell, cell, bx, by, bw, bh):
                    sh["cells"].discard((cx, cy))
                    if erode:
                        for ddx, ddy in ((0, 1), (0, -1), (1, 0), (-1, 0)):
                            if random.random() < 0.35:
                                sh["cells"].discard((cx + ddx, cy + ddy))
                    return True
        return False

    def _player_hit(self):
        self.lives -= 1
        self.blasts.append({"x": self.player_x, "y": self.PLAYER_Y + 10, "t": 0.0, "c": "p"})
        self.ebullets.clear()
        self.invuln = 1.8
        if self.lives <= 0:
            self.state = "over"
            self._snd("gameover")
        else:
            self._snd("hit")

    # ---------- один шаг игры ----------
    def update(self, dt: float, left: bool, right: bool, fire: bool):
        if self.state != "playing":
            return
        dt = min(max(dt, 0.0), 0.05)
        for b in self.blasts:
            b["t"] += dt
        self.blasts = [b for b in self.blasts if b["t"] < 0.4]
        self.invuln = max(0.0, self.invuln - dt)
        if self.banner > 0:                      # пауза между волнами: двигается только корабль
            self.banner -= dt
            self._move_player(dt, left, right)
            return
        self._move_player(dt, left, right)
        self.cooldown = max(0.0, self.cooldown - dt)
        if fire and self.cooldown <= 0 and len(self.bullets) < 2:
            self.bullets.append({"x": self.player_x, "y": self.PLAYER_Y - 4})
            self.cooldown = 0.32
            self._snd("shoot")
        self._step_player_bullets(dt)
        self._step_aliens(dt)
        self._step_enemy_fire(dt)
        self._step_enemy_bullets(dt)
        self._step_ufo(dt)
        if self.state != "playing":
            return
        if not self.alive_aliens():              # волна уничтожена
            self.level += 1
            self._add_score(100)
            self._snd("win")
            self.spawn_wave()
            self.banner = 1.4
            self.invuln = 0.0

    def _move_player(self, dt, left, right):
        speed = 270.0
        if left and not right:
            self.player_x -= speed * dt
        elif right and not left:
            self.player_x += speed * dt
        half = self.PLAYER_W / 2
        self.player_x = min(self.W - 10 - half, max(10 + half, self.player_x))

    def _step_player_bullets(self, dt):
        keep = []
        for b in self.bullets:
            b["y"] -= 520.0 * dt
            bx, by, bw, bh = b["x"] - 1.5, b["y"], 3, 12
            gone = False
            for a in self.aliens:
                if not a["alive"]:
                    continue
                ax, ay = self.alien_pos(a)
                if self._hit(ax, ay, self.ALIEN_W, self.ALIEN_H, bx, by, bw, bh):
                    a["alive"] = False
                    self._add_score(self.POINTS[a["r"]])
                    self._snd("explode_small")
                    self.blasts.append({"x": ax + self.ALIEN_W / 2, "y": ay + self.ALIEN_H / 2,
                                        "t": 0.0, "c": "a"})
                    gone = True
                    break
            if not gone and self.ufo and self._hit(self.ufo["x"], 52, 48, 21, bx, by, bw, bh):
                self._add_score(self.ufo["pts"])
                self._snd("ufo")
                self.blasts.append({"x": self.ufo["x"] + 24, "y": 62, "t": 0.0, "c": "u"})
                self.ufo = None
                gone = True
            if not gone and self._shield_hit(bx, by, bw, bh):
                gone = True
            if not gone and by + bh > self.TOP:
                keep.append(b)
        self.bullets = keep

    def _step_aliens(self, dt):
        alive = self.alive_aliens()
        if not alive:
            return
        n = len(alive)
        speed = 28 + self.level * 5 + (1 - n / self.total) * 150 + (80 if n == 1 else 0)
        move = self.dir * speed * dt
        left = self.ox + min(a["c"] for a in alive) * self.DX
        right = self.ox + max(a["c"] for a in alive) * self.DX + self.ALIEN_W
        if right + move > self.W - 12 or left + move < 12:
            self.dir = -self.dir
            self.oy += 14
        else:
            self.ox += move
        self.anim += abs(move)
        low = max(self.oy + a["r"] * self.DY + self.ALIEN_H for a in alive)
        if low > self.SHIELD_Y:                  # пришельцы «стирают» щиты, до которых дошли
            for a in alive:
                ax, ay = self.alien_pos(a)
                if ay + self.ALIEN_H > self.SHIELD_Y:
                    self._shield_hit(ax, ay, self.ALIEN_W, self.ALIEN_H, erode=False)
        if low >= self.PLAYER_Y - 2:             # вторжение — игра окончена
            self.lives = 0
            self.state = "over"
            self._snd("gameover")

    def _step_enemy_fire(self, dt):
        self.fire_t -= dt
        if self.fire_t > 0:
            return
        limit = min(6, 2 + self.level // 2)
        self.fire_t = random.uniform(0.4, 1.0) * max(0.3, 1.2 - 0.09 * self.level)
        if len(self.ebullets) >= limit:
            return
        columns = {}
        for a in self.alive_aliens():
            if a["c"] not in columns or a["r"] > columns[a["c"]]["r"]:
                columns[a["c"]] = a
        if columns:
            a = random.choice(list(columns.values()))
            ax, ay = self.alien_pos(a)
            self.ebullets.append({"x": ax + self.ALIEN_W / 2, "y": ay + self.ALIEN_H})

    def _step_enemy_bullets(self, dt):
        keep = []
        speed = 190.0 + self.level * 12
        for b in self.ebullets:
            b["y"] += speed * dt
            bx, by, bw, bh = b["x"] - 1.5, b["y"], 3, 12
            if (self.invuln <= 0 and self._hit(self.player_x - self.PLAYER_W / 2, self.PLAYER_Y,
                                               self.PLAYER_W, self.PLAYER_H, bx, by, bw, bh)):
                self._player_hit()
                return
            if self._shield_hit(bx, by, bw, bh) or by > self.H:
                continue
            keep.append(b)
        self.ebullets = keep

    def _step_ufo(self, dt):
        if self.ufo is None:
            self.ufo_t -= dt
            if self.ufo_t <= 0 and len(self.alive_aliens()) > 3:
                d = random.choice((-1, 1))
                self.ufo = {"x": -48.0 if d > 0 else float(self.W), "d": d,
                            "pts": random.choice((50, 100, 150, 300))}
                self.ufo_t = random.uniform(15, 25)
            return
        self.ufo["x"] += self.ufo["d"] * 110.0 * dt
        if self.ufo["x"] < -60 or self.ufo["x"] > self.W + 12:
            self.ufo = None


# =====================================================================================
# НОВОЕ: встроенная мини-игра «Арканоид» (кнопка «Поиграй 🎮» на вкладке «Скриншоты разом»).
# Логика (ArkanoidEngine) не зависит от Qt и считает движение по времени кадра (dt) с
# подшагами, поэтому мяч не «пролетает» сквозь блоки, а скорость не зависит от частоты
# таймера. Виджет рисует кадр в paintEvent; игровой цикл — QTimer ~60 кадров/с в основном
# потоке: игра очень лёгкая и не мешает фоновым потокам OCR.
# =====================================================================================
MINIGAME_ARKANOID_KEY = "minigame_arkanoid_highscore"


MINIGAME_PLATFORMER_KEY = "minigame_platformer_highscore"


# цвета рядов блоков сверху вниз: верхний ряд — «бронированный» (2 попадания)
ARKANOID_ROW_COLORS = ("#c0c8d8", "#ff4d4d", "#ff9a3c", "#ffd84a", "#4cff6a", "#5ce1ff")


class ArkanoidEngine(GameSfxMixin):
    """Чистая логика «Арканоида» (без Qt). Координаты — логические пиксели поля W×H;
    виджет сам масштабирует поле под размер окна."""

    W, H = 480, 600
    TOP, WALL = 48, 8                      # высота строки со счётом и толщина боковых стен
    COLS, ROWS = 10, 6
    PITCH_X, PITCH_Y = 44, 22              # шаг сетки блоков
    BRICK_W, BRICK_H = 42, 20
    BRICK_Y0 = 92
    PADDLE_W, PADDLE_H, PADDLE_Y = 84, 12, 556
    BALL_R = 6
    ROW_POINTS = (70, 60, 50, 40, 30, 20)  # очки за блок: верхние ряды дороже
    LIVES = 3

    def __init__(self, high_score: int = 0):
        self.high = max(0, int(high_score))
        self.state = "ready"               # ready / playing / paused / over / won
        self.new_game()

    # ---------- подготовка ----------
    def new_game(self):
        self.score = 0
        self.lives = self.LIVES
        self.broken = 0
        self.record_beaten = False
        self.paddle_x = self.W / 2
        self.particles = []
        self.build_bricks()
        self.reset_ball()

    def build_bricks(self):
        x0 = (self.W - self.COLS * self.PITCH_X) / 2 + (self.PITCH_X - self.BRICK_W) / 2
        self.bricks = [
            {"c": c, "r": r, "hp": 2 if r == 0 else 1, "flash": 0.0,
             "x": x0 + c * self.PITCH_X, "y": self.BRICK_Y0 + r * self.PITCH_Y}
            for r in range(self.ROWS) for c in range(self.COLS)
        ]

    def reset_ball(self):
        """Мяч «приклеен» к платформе до запуска (пробел / ↑ / щелчок мыши)."""
        self.stuck = True
        self.vx = self.vy = 0.0
        self.bx = self.paddle_x
        self.by = self.PADDLE_Y - self.BALL_R - 1

    @property
    def speed(self) -> float:
        return 330.0 + min(170.0, self.broken * 2.5)    # мяч разгоняется по ходу игры

    # ---------- управление ----------
    def start(self):
        if self.state in ("ready", "over", "won"):
            if self.state != "ready":
                self.new_game()
            self.state = "playing"

    def pause(self):
        if self.state == "playing":
            self.state = "paused"

    def resume(self):
        if self.state == "paused":
            self.state = "playing"

    def launch(self):
        """Запуск мяча с платформы под небольшим случайным углом."""
        if self.state == "playing" and self.stuck:
            self.stuck = False
            self._set_velocity(math.sin(math.radians(random.uniform(-22, 22))),
                               -math.cos(math.radians(random.uniform(0, 22))))

    def set_paddle_x(self, x: float):
        """Платформа под курсором мыши (центр платформы в логических координатах)."""
        if self.state in ("ready", "playing"):
            self._place_paddle(x)

    def _place_paddle(self, x: float):
        half = self.PADDLE_W / 2
        self.paddle_x = min(self.W - self.WALL - half, max(self.WALL + half, x))
        if self.stuck:
            self.bx = self.paddle_x

    # ---------- вспомогательное ----------
    def _set_velocity(self, dx: float, dy: float):
        """Задаёт направление и приводит скорость к текущей; не даёт мячу идти почти
        горизонтально (иначе он может бесконечно кататься между стенами)."""
        length = math.hypot(dx, dy) or 1.0
        dx, dy = dx / length, dy / length
        if abs(dy) < 0.28:
            dy = math.copysign(0.28, dy or -1)
            dx = math.copysign(math.sqrt(1 - dy * dy), dx or 1)
        self.vx, self.vy = dx * self.speed, dy * self.speed

    def _add_score(self, pts: int):
        self.score += pts
        if self.score > self.high:
            self.high = self.score
            self.record_beaten = True

    def _burst(self, brick: dict):
        for _ in range(7):
            ang = random.uniform(0, math.tau)
            sp = random.uniform(40, 160)
            self.particles.append({"x": brick["x"] + self.BRICK_W / 2, "y": brick["y"] + self.BRICK_H / 2,
                                   "vx": math.cos(ang) * sp, "vy": math.sin(ang) * sp - 30,
                                   "t": 0.0, "r": brick["r"]})

    # ---------- один шаг игры ----------
    def update(self, dt: float, left: bool, right: bool):
        if self.state != "playing":
            return
        dt = min(max(dt, 0.0), 0.05)
        for p in self.particles:
            p["t"] += dt
            p["x"] += p["vx"] * dt
            p["y"] += p["vy"] * dt
            p["vy"] += 400 * dt
        self.particles = [p for p in self.particles if p["t"] < 0.5]
        for b in self.bricks:
            b["flash"] = max(0.0, b["flash"] - dt)
        if left and not right:
            self._place_paddle(self.paddle_x - 520.0 * dt)
        elif right and not left:
            self._place_paddle(self.paddle_x + 520.0 * dt)
        if self.stuck:
            return
        steps = max(1, math.ceil(self.speed * dt / 3.0))    # подшаги: не больше ~3 px за шаг
        for _ in range(steps):
            self._advance(dt / steps)
            if self.state != "playing" or self.stuck:
                break

    def _advance(self, h: float):
        r = self.BALL_R
        self.bx += self.vx * h
        self.by += self.vy * h
        # стены и потолок
        if self.bx - r < self.WALL:
            self.bx, self.vx = self.WALL + r, abs(self.vx)
            self._snd("wall")
        elif self.bx + r > self.W - self.WALL:
            self.bx, self.vx = self.W - self.WALL - r, -abs(self.vx)
            self._snd("wall")
        if self.by - r < self.TOP:
            self.by, self.vy = self.TOP + r, abs(self.vy)
            self._snd("wall")
        # платформа: угол отскока зависит от места попадания
        top = self.PADDLE_Y
        half = self.PADDLE_W / 2
        if (self.vy > 0 and top <= self.by + r <= top + 12
                and self.paddle_x - half - r * 0.6 <= self.bx <= self.paddle_x + half + r * 0.6):
            rel = max(-1.0, min(1.0, (self.bx - self.paddle_x) / half))
            ang = math.radians(rel * 62)
            self.by = top - r
            self._set_velocity(math.sin(ang), -math.cos(ang))
            self._snd("paddle")
            return
        # блоки
        for b in self.bricks:
            cx = min(max(self.bx, b["x"]), b["x"] + self.BRICK_W)
            cy = min(max(self.by, b["y"]), b["y"] + self.BRICK_H)
            dx, dy = self.bx - cx, self.by - cy
            if dx * dx + dy * dy > r * r:
                continue
            if dx == 0 and dy == 0:                       # центр мяча внутри блока
                self.vy = -self.vy
            elif abs(dx) > abs(dy):                       # удар сбоку
                self.vx = abs(self.vx) * (1 if dx > 0 else -1)
                self.bx = cx + (r + 0.01) * (1 if dx > 0 else -1)
            else:                                         # удар сверху / снизу
                self.vy = abs(self.vy) * (1 if dy > 0 else -1)
                self.by = cy + (r + 0.01) * (1 if dy > 0 else -1)
            b["hp"] -= 1
            b["flash"] = 0.12
            self._snd("brick" if b["hp"] <= 0 else "wall")
            if b["hp"] <= 0:
                self.bricks.remove(b)
                self.broken += 1
                self._add_score(self.ROW_POINTS[b["r"]])
                self._burst(b)
            self._set_velocity(self.vx, self.vy)
            break
        if not self.bricks:                               # стенка разрушена — победа
            self._add_score(50 * self.lives)              # бонус за оставшиеся жизни
            self.state = "won"
            self._snd("win")
            self.stuck = True
            self.vx = self.vy = 0.0
            return
        # мяч упал под платформу
        if self.by - r > self.H:
            self.lives -= 1
            if self.lives <= 0:
                self.lives = 0
                self.state = "over"
                self._snd("gameover")
            else:
                self._snd("death")
            self.reset_ball()


# =====================================================================================
# НОВОЕ: мини-игра «Платформер» (в духе классических 2D-платформеров): три уровня с
# нарастающей сложностью, бег и прыжки с настоящей физикой, блоки «?» с усилениями,
# Супер гриб, Огненный цветок, Звезда неуязвимости, монеты, враги, шипы, ямы, контрольные
# точки и финишный флаг. Логика (PlatformerEngine) не зависит от Qt: физика считается
# маленькими подшагами по времени кадра, поэтому игра идёт одинаково при любой частоте
# таймера. Виджет рисует кадр в paintEvent; цикл — QTimer ~60 кадров/с в основном потоке
# (игра очень лёгкая и не мешает фоновым потокам OCR). Все рисунки — простые фигуры.
# =====================================================================================
PLATFORMER_SOLID = frozenset("#BQU=T")      # твёрдые клетки: земля, кирпич, блок «?», пустой блок, платформа, труба


# описание уровней: номер, название, оформление, ширина, столбец флага, скорость врагов
PLATFORMER_LEVELS = (
    {"name": "1-1", "title": "Зелёные луга", "theme": "day", "cols": 120, "flag": 114, "enemy_speed": 50.0},
    {"name": "1-2", "title": "Тёмная пещера", "theme": "cave", "cols": 130, "flag": 124, "enemy_speed": 62.0},
    {"name": "1-3", "title": "Ночные небеса", "theme": "night", "cols": 140, "flag": 134, "enemy_speed": 76.0},
)


class PlatformerEngine(GameSfxMixin):
    """Чистая логика платформера (без Qt). Мир — сетка клеток TILE×TILE, камера движется
    по горизонтали; все координаты в логических пикселях."""

    TILE = 32
    VIEW_W, VIEW_H = 512, 384
    ROWS = 12
    GRAVITY, JUMP_V, MAX_FALL = 1800.0, 650.0, 640.0
    MAX_SPEED = 200.0
    PW, PH, BIG_PH = 22, 30, 46              # размер героя: обычный и «большой» (после гриба)
    LIVES = 3
    GROUND_ROW = 10
    STAR_TIME = 10.0
    FB = 12                                  # размер огненного шара

    def __init__(self, high_score: int = 0):
        self.high = max(0, int(high_score))
        self.state = "ready"                 # ready / playing / paused / over / won / levelclear
        self.new_game()

    # ---------- новая игра / уровни ----------
    def new_game(self):
        self.score = 0
        self.coins = 0
        self.lives = self.LIVES
        self.level_idx = 0
        self.record_beaten = False
        self.t = 0.0
        self.power = 0                       # 0 — обычный, 1 — Супер гриб, 2 — Огненный цветок
        self.star_t = 0.0
        self.level_bonus = 0
        self.dying = 0.0
        self.load_level()

    @property
    def level_count(self) -> int:
        return len(PLATFORMER_LEVELS)

    @property
    def meta(self) -> dict:
        return PLATFORMER_LEVELS[self.level_idx]

    @property
    def theme(self) -> str:
        return self.meta["theme"]

    def load_level(self):
        self.cols = self.meta["cols"]
        self.grid, self.coin_list, self.enemies, self.qcontent = self._build_level(self.level_idx)
        self.items, self.fireballs = [], []
        self.checkpoint = (2 * self.TILE, self.GROUND_ROW * self.TILE - self.PH)
        self.checkpoint_hit = False
        self.bumps, self.pops, self.particles = {}, [], []
        self.dying = 0.0
        self.fire_cd = 0.0
        self.banner = 2.4                    # заставка «Уровень 1-1» в начале уровня
        self.cam_x = 0.0
        self.ph = self.PH
        self._respawn(invuln=0.0)
        self._try_enlarge()

    def next_level(self):
        """Переход на следующий уровень после финишного флага (усиления сохраняются)."""
        if self.state == "levelclear" and self.level_idx < self.level_count - 1:
            self.level_idx += 1
            self.load_level()
            self.state = "playing"

    def _build_level(self, idx):
        T, R = self.TILE, self.ROWS
        meta = PLATFORMER_LEVELS[idx]
        C = meta["cols"]
        g = [[" "] * C for _ in range(R)]
        qc = {}

        def put(c, r, ch):
            if 0 <= c < C and 0 <= r < R:
                g[r][c] = ch

        def row(c0, c1, r, ch):
            for c in range(c0, c1):
                put(c, r, ch)

        def ground(segs):                                   # земля; промежутки между кусками — ямы
            for a, b in segs:
                row(a, b, 10, "#")
                row(a, b, 11, "#")

        def pipe(c, h):
            for cc in (c, c + 1):
                for r in range(10 - h, 10):
                    put(cc, r, "T")

        def stairs(c0, tops):
            for i, top in enumerate(tops):
                for r in range(top, 10):
                    put(c0 + i, r, "#")

        def block(c, r, ch="Q", content=None):
            put(c, r, ch)
            if content:
                qc[(c, r)] = content

        if idx == 0:                                        # 1-1: мягкий старт
            ground([(0, 28), (30, 52), (55, 78), (81, 100), (102, 120)])
            block(11, 7, "B"); block(12, 7, "Q", "power"); block(13, 7, "B")
            block(14, 7, "Q", "coin"); block(15, 7, "B")
            row(18, 22, 7, "="); row(18, 22, 6, "o")
            row(5, 8, 9, "o"); row(27, 31, 8, "o")
            pipe(38, 2); pipe(42, 2)
            put(57, 9, "C")
            row(60, 62, 9, "^"); row(63, 66, 7, "=")
            row(68, 73, 5, "="); row(68, 73, 4, "o"); row(53, 55, 8, "o")
            row(88, 90, 9, "^"); row(82, 86, 7, "=")
            block(90, 7, "Q", "power"); row(92, 95, 9, "o")
            stairs(105, (9, 8, 7, 6))
            enemy_cols = (20, 36, 45, 66, 72, 91, 94)
        elif idx == 1:                                      # 1-2: пещера, больше ям, шипов и труб
            ground([(0, 22), (24, 42), (45, 62), (64, 84), (87, 104), (106, 130)])
            row(0, 130, 0, "#"); row(0, 130, 1, "#")        # каменный потолок
            for c in (14, 15, 33, 34, 57, 58, 75, 76, 97, 98):
                put(c, 2, "#")
            block(27, 7, "B"); block(28, 7, "Q", "power"); block(29, 7, "B"); block(30, 7, "Q", "coin")
            block(57, 7, "B"); block(58, 7, "Q", "power"); block(59, 7, "B")
            block(77, 7, "B"); block(78, 7, "Q", "star"); block(79, 7, "B")
            pipe(34, 2); pipe(54, 2); pipe(70, 3)
            row(50, 52, 9, "^"); row(74, 76, 9, "^"); row(99, 101, 9, "^")
            row(28, 32, 6, "o"); row(10, 14, 9, "o"); row(42, 45, 8, "o"); row(84, 87, 8, "o")
            row(66, 70, 6, "o"); row(99, 103, 6, "o")
            row(88, 91, 7, "="); row(92, 97, 5, "="); row(92, 97, 4, "o")
            put(66, 9, "C")
            stairs(119, (9, 8, 7, 6))
            enemy_cols = (12, 16, 29, 32, 56, 68, 78, 90, 96, 110, 114, 116)
        else:                                               # 1-3: небо, узкие острова, много врагов и шипов
            ground([(0, 16), (19, 29), (32, 38), (41, 52), (55, 60), (63, 78), (81, 90),
                    (93, 108), (111, 140)])
            block(5, 7, "B"); block(6, 7, "Q", "power"); block(7, 7, "B")
            block(42, 7, "B"); block(43, 7, "Q", "star"); block(44, 7, "B")
            block(68, 7, "B"); block(69, 7, "Q", "power"); block(70, 7, "B")
            block(97, 7, "Q", "coin"); block(98, 7, "Q", "power")
            pipe(20, 2); pipe(124, 2)
            row(12, 14, 9, "^"); row(48, 50, 9, "^"); row(73, 75, 9, "^"); put(86, 9, "^")
            row(118, 120, 9, "^")
            for a0, b0 in ((16, 19), (29, 32), (38, 41), (52, 55), (60, 63), (78, 81), (90, 93), (108, 111)):
                row(a0, b0, 8, "o")                         # монеты дугой над ямами
            row(2, 5, 9, "o"); row(88, 90, 9, "o"); row(127, 130, 9, "o")
            put(64, 9, "C")
            stairs(126, (9, 8, 7, 6))
            enemy_cols = (8, 25, 68, 96, 116, 122, 131)
        flag = meta["flag"]
        for r in range(4, 10):
            put(flag, r, "F")
        coin_list = []
        for r in range(R):
            for c in range(C):
                if g[r][c] == "o":
                    g[r][c] = " "
                    coin_list.append({"x": c * T + 8, "y": r * T + 8, "taken": False})
        sp = meta["enemy_speed"]
        enemies = [{"x": c * T + 3.0, "y": 10 * T - 24.0, "w": 26, "h": 24, "vx": -sp, "vy": 0.0,
                    "alive": True, "squash": 0.0} for c in enemy_cols]
        return g, coin_list, enemies, qc

    def tile(self, c, r) -> str:
        if c < 0 or c >= self.cols:
            return "#"                       # края уровня — невидимые стены
        if r < 0 or r >= self.ROWS:
            return " "
        return self.grid[r][c]

    # ---------- управление ----------
    def start(self):
        if self.state in ("ready", "over", "won"):
            if self.state != "ready":
                self.new_game()
            self.state = "playing"

    def pause(self):
        if self.state == "playing":
            self.state = "paused"

    def resume(self):
        if self.state == "paused":
            self.state = "playing"

    def press_jump(self):
        self.jump_buf = 0.12                 # «запас» нажатия: прыжок сработает чуть раньше приземления

    def fire(self):
        """Огненный шар (клавиши F / Ctrl): только с Огненным цветком, не больше двух на экране."""
        if (self.state == "playing" and self.power == 2 and self.dying <= 0 and self.fire_cd <= 0
                and len(self.fireballs) < 2):
            self.fire_cd = 0.28
            self._snd("fireball")
            self.fireballs.append({"x": self.x + (self.PW if self.facing > 0 else -self.FB),
                                   "y": self.y + self.ph * 0.6, "vx": 330.0 * self.facing,
                                   "vy": 0.0, "t": 0.0, "dead": False})

    def _respawn(self, invuln=2.0):
        self.x = float(self.checkpoint[0])
        self.y = float(self.checkpoint[1] + self.PH - self.ph)
        self.vx = self.vy = 0.0
        self.on_ground = False
        self.coyote = 0.0
        self.jump_buf = 0.0
        self.facing = 1
        self.invuln = invuln
        self.walk_t = 0.0
        self.cam_x = self._cam_target()

    def _cam_target(self) -> float:
        return min(max(0.0, self.x + self.PW / 2 - self.VIEW_W * 0.42), self.cols * self.TILE - self.VIEW_W)

    def _add_score(self, pts: int):
        self.score += pts
        if self.score > self.high:
            self.high = self.score
            self.record_beaten = True

    # ---------- размер героя ----------
    def _try_enlarge(self):
        """Большой герой (Супер гриб / Огненный цветок): вырастает вверх, если над головой есть место."""
        if self.power >= 1 and self.ph == self.PH:
            diff = self.BIG_PH - self.PH
            if not any(ch in PLATFORMER_SOLID for _c, _r, ch in
                       self._tiles_in(self.x, self.y - diff, self.PW, self.BIG_PH)):
                self.y -= diff
                self.ph = self.BIG_PH

    def _shrink(self):
        """Удар по большому герою: усиление пропадает, но жизнь не теряется."""
        self._snd("hit")
        self.power = 0
        if self.ph > self.PH:
            self.y += self.ph - self.PH
            self.ph = self.PH
        self.invuln = 2.0

    # ---------- шаг ----------
    def update(self, dt: float, left: bool, right: bool, jump_held: bool):
        if self.state != "playing":
            return
        dt = min(max(dt, 0.0), 0.05)
        self.t += dt
        self.banner = max(0.0, self.banner - dt)
        n = max(1, math.ceil(dt / 0.008))    # подшаги ≤ 8 мс: герой не пролетает сквозь клетки
        for _ in range(n):
            self._physics(dt / n, left, right, jump_held)
            if self.state != "playing":
                break
        self._step_fx(dt)
        self.cam_x += (self._cam_target() - self.cam_x) * min(1.0, dt * 8)

    def _step_fx(self, dt):
        for k in list(self.bumps):
            self.bumps[k] += dt
            if self.bumps[k] > 0.18:
                del self.bumps[k]
        for p in self.pops:
            p["t"] += dt
        self.pops = [p for p in self.pops if p["t"] < 0.5]
        for p in self.particles:
            p["t"] += dt
            p["x"] += p["vx"] * dt
            p["y"] += p["vy"] * dt
            p["vy"] += 700 * dt
        self.particles = [p for p in self.particles if p["t"] < 0.6]

    def _physics(self, h, left, right, jump_held):
        if self.dying > 0:                   # анимация потери жизни: герой подлетает и падает
            self.dying -= h
            self.vy += self.GRAVITY * h
            self.y += self.vy * h
            if self.dying <= 0:
                if self.lives <= 0:
                    self.state = "over"
                    self._snd("gameover")
                else:
                    self._respawn()
            return
        self.invuln = max(0.0, self.invuln - h)
        self.star_t = max(0.0, self.star_t - h)
        self.fire_cd = max(0.0, self.fire_cd - h)
        self.jump_buf = max(0.0, self.jump_buf - h)
        self.coyote = self.coyote - h if not self.on_ground else 0.09     # «время койота»: прыжок сразу после края
        # горизонталь: разгон, трение (со звездой герой чуть быстрее)
        top_speed = self.MAX_SPEED * (1.2 if self.star_t > 0 else 1.0)
        target = (int(right) - int(left)) * top_speed
        if target:
            self.facing = 1 if target > 0 else -1
        accel = (1500.0 if self.on_ground else 900.0) if target else (1800.0 if self.on_ground else 250.0)
        if self.vx < target:
            self.vx = min(target, self.vx + accel * h)
        elif self.vx > target:
            self.vx = max(target, self.vx - accel * h)
        # прыжок: высота зависит от того, как долго удерживают клавишу
        if self.jump_buf > 0 and (self.on_ground or self.coyote > 0):
            self.vy = -self.JUMP_V
            self.jump_buf = 0.0
            self.coyote = 0.0
            self.on_ground = False
            self._snd("jump")
        grav = self.GRAVITY * (2.4 if self.vy < 0 and not jump_held else 1.0)
        self.vy = min(self.MAX_FALL, self.vy + grav * h)
        self._move_x(self.vx * h)
        self._move_y(self.vy * h)
        self._try_enlarge()
        if self.on_ground and abs(self.vx) > 10:
            self.walk_t += h * abs(self.vx) / 22.0
        if self.y > self.ROWS * self.TILE + 40:                           # упал в яму
            self._lose_life()
            return
        self._step_enemies(h)
        self._step_items(h)
        self._step_fireballs(h)
        self._interact()

    # ---------- столкновения со сеткой ----------
    def _tiles_in(self, x, y, w, h):
        T = self.TILE
        for r in range(int(y // T), int((y + h - 0.001) // T) + 1):
            for c in range(int(x // T), int((x + w - 0.001) // T) + 1):
                yield c, r, self.tile(c, r)

    def _move_x(self, dx):
        T = self.TILE
        self.x += dx
        for c, r, ch in self._tiles_in(self.x, self.y, self.PW, self.ph):
            if ch in PLATFORMER_SOLID:
                self.x = c * T - self.PW if dx > 0 else (c + 1) * T
                self.vx = 0.0
                break

    def _move_y(self, dy):
        T = self.TILE
        self.y += dy
        self.on_ground = False
        for c, r, ch in self._tiles_in(self.x, self.y, self.PW, self.ph):
            if ch not in PLATFORMER_SOLID:
                continue
            if dy > 0:
                self.y = r * T - self.ph
                self.vy = 0.0
                self.on_ground = True
            elif dy < 0:
                self.y = (r + 1) * T
                self.vy = 0.0
                self._hit_block(c, r)
            break

    def _hit_block(self, c, r):
        """Удар головой снизу: «?» даёт монету или усиление, кирпич ломается (большим героем)."""
        ch = self.tile(c, r)
        T = self.TILE
        if ch == "Q":
            self.grid[r][c] = "U"
            self.bumps[(c, r)] = 0.0
            content = self.qcontent.get((c, r), "coin")
            if content == "coin":
                self.coins += 1
                self._add_score(10)
                self._snd("coin")
                self.pops.append({"x": c * T + T / 2, "y": r * T, "t": 0.0})
            else:
                self._snd("block")
                kind = ("mushroom" if self.power == 0 else "flower") if content == "power" else content
                self._spawn_item(kind, c, r)
        elif ch == "B":
            if self.power >= 1:
                self.grid[r][c] = " "
                self._add_score(10)
                self._snd("explode_small")
                for _ in range(6):
                    self.particles.append({"x": c * T + T / 2, "y": r * T + T / 2,
                                           "vx": random.uniform(-120, 120), "vy": random.uniform(-260, -80), "t": 0.0})
            else:
                self.bumps[(c, r)] = 0.0
                self._snd("block")
        else:
            self.bumps[(c, r)] = 0.0
            self._snd("block")

    def _spawn_item(self, kind, c, r):
        T = self.TILE
        self._snd("item")
        self.items.append({"kind": kind, "x": c * T + 3.0, "y": r * T + 3.0, "y0": r * T + 3.0,
                           "y1": r * T - 26.0, "w": 26, "h": 26, "vx": 0.0, "vy": 0.0, "emerge": 0.5})

    # ---------- враги, предметы, огненные шары ----------
    def _kill_enemy(self, e, pts):
        e["alive"], e["squash"] = False, 0.35
        self._add_score(pts)
        self._snd("stomp")

    def _step_enemies(self, h):
        T = self.TILE
        for e in self.enemies:
            if not e["alive"]:
                e["squash"] -= h
                continue
            if abs(e["x"] - self.x) > self.VIEW_W:      # далёкие враги «спят»
                continue
            e["vy"] = min(self.MAX_FALL, e["vy"] + self.GRAVITY * h)
            e["x"] += e["vx"] * h
            for c, r, ch in self._tiles_in(e["x"], e["y"], e["w"], e["h"]):
                if ch in PLATFORMER_SOLID:
                    e["x"] = c * T - e["w"] if e["vx"] > 0 else (c + 1) * T
                    e["vx"] = -e["vx"]
                    break
            e["y"] += e["vy"] * h
            grounded = False
            for c, r, ch in self._tiles_in(e["x"], e["y"], e["w"], e["h"]):
                if ch in PLATFORMER_SOLID and e["vy"] > 0:
                    e["y"] = r * T - e["h"]
                    e["vy"] = 0.0
                    grounded = True
                    break
            if grounded:                                  # не падать с края платформы
                lead = e["x"] + (e["w"] + 2 if e["vx"] > 0 else -2)
                if self.tile(int(lead // T), int((e["y"] + e["h"] + 2) // T)) not in PLATFORMER_SOLID:
                    e["vx"] = -e["vx"]
            if e["y"] > self.ROWS * T + 60:
                e["alive"], e["squash"] = False, 0.0

    def _step_items(self, h):
        T = self.TILE
        keep = []
        for it in self.items:
            if it["emerge"] > 0:                          # предмет «выезжает» из блока
                it["emerge"] -= h
                k = 1 - max(0.0, it["emerge"]) / 0.5
                it["y"] = it["y0"] + (it["y1"] - it["y0"]) * k
                if it["emerge"] <= 0:
                    it["vx"] = {"mushroom": 70.0, "star": 95.0}.get(it["kind"], 0.0)
                    it["vy"] = -380.0 if it["kind"] == "star" else 0.0
                keep.append(it)
                continue
            it["vy"] = min(self.MAX_FALL, it["vy"] + self.GRAVITY * h)
            it["x"] += it["vx"] * h
            for c, r, ch in self._tiles_in(it["x"], it["y"], it["w"], it["h"]):
                if ch in PLATFORMER_SOLID:
                    it["x"] = c * T - it["w"] if it["vx"] > 0 else (c + 1) * T
                    it["vx"] = -it["vx"]
                    break
            it["y"] += it["vy"] * h
            for c, r, ch in self._tiles_in(it["x"], it["y"], it["w"], it["h"]):
                if ch in PLATFORMER_SOLID:
                    if it["vy"] > 0:
                        it["y"] = r * T - it["h"]
                        it["vy"] = -380.0 if it["kind"] == "star" else 0.0   # звезда подпрыгивает
                    else:
                        it["y"] = (r + 1) * T
                        it["vy"] = 0.0
                    break
            if it["y"] < self.ROWS * T + 60:
                keep.append(it)
        self.items = keep

    def _step_fireballs(self, h):
        T = self.TILE
        for f in self.fireballs:
            f["t"] += h
            f["vy"] += 1500.0 * h
            f["x"] += f["vx"] * h
            if any(ch in PLATFORMER_SOLID for _c, _r, ch in self._tiles_in(f["x"], f["y"], self.FB, self.FB)):
                f["dead"] = True                          # ударился о стену
                continue
            f["y"] += f["vy"] * h
            for c, r, ch in self._tiles_in(f["x"], f["y"], self.FB, self.FB):
                if ch in PLATFORMER_SOLID:
                    if f["vy"] > 0:
                        f["y"] = r * T - self.FB
                        f["vy"] = -250.0                  # шар отскакивает от земли
                    else:
                        f["dead"] = True
                    break
            for e in self.enemies:
                if e["alive"] and self._overlap(f["x"], f["y"], self.FB, self.FB, e["x"], e["y"], e["w"], e["h"]):
                    self._kill_enemy(e, 100)
                    f["dead"] = True
                    break
            if f["t"] > 2.5 or f["y"] > self.ROWS * T + 40 or abs(f["x"] - self.x) > self.VIEW_W:
                f["dead"] = True
        self.fireballs = [f for f in self.fireballs if not f["dead"]]

    @staticmethod
    def _overlap(ax, ay, aw, ah, bx, by, bw, bh):
        return ax < bx + bw and bx < ax + aw and ay < by + bh and by < ay + ah

    def _collect(self, it):
        kind = it["kind"]
        self._snd("powerup")
        if kind == "mushroom":
            if self.power == 0:
                self.power = 1
                self._try_enlarge()
            self._add_score(1000)
        elif kind == "flower":
            self.power = 2
            self._try_enlarge()
            self._add_score(1000)
        elif kind == "star":
            self.star_t = self.STAR_TIME
            self._add_score(1000)

    def _interact(self):
        T = self.TILE
        px, py, pw, ph = self.x, self.y, self.PW, self.ph
        for it in list(self.items):                         # усиления
            if it["emerge"] <= 0 and self._overlap(px, py, pw, ph, it["x"], it["y"], it["w"], it["h"]):
                self.items.remove(it)
                self._collect(it)
        for cn in self.coin_list:                           # монеты
            if not cn["taken"] and self._overlap(px, py, pw, ph, cn["x"], cn["y"], 16, 16):
                cn["taken"] = True
                self.coins += 1
                self._add_score(10)
                self._snd("coin")
        for e in self.enemies:                              # враги
            if e["alive"] and self._overlap(px, py, pw, ph, e["x"], e["y"], e["w"], e["h"]):
                if self.star_t > 0:                         # со звездой достаточно коснуться
                    self._kill_enemy(e, 200)
                elif self.vy > 0 and (py + ph) - e["y"] < 18:
                    self._kill_enemy(e, 100)                # прыжок сверху
                    self.vy = -(430.0 if self._jump_pressed_recently() else 300.0)
                else:
                    self._hurt()
                    return
        for c, r, ch in self._tiles_in(px, py, pw, ph):
            if ch == "^" and self.star_t <= 0 and self._overlap(px, py, pw, ph, c * T + 4, r * T + 14, 24, 18):
                self._hurt()                                # шипы
                return
            if ch == "C" and not self.checkpoint_hit:       # контрольная точка
                self.checkpoint_hit = True
                self.checkpoint = (c * T + 5, self.GROUND_ROW * T - self.PH)
                self._add_score(50)
            if ch == "F":                                   # финиш уровня
                self.level_bonus = 500 + 200 * self.lives + 100 * self.level_idx
                self._add_score(self.level_bonus)
                self.state = "levelclear" if self.level_idx < self.level_count - 1 else "won"
                self._snd("win")
                self.vx = 0.0
                return

    def _jump_pressed_recently(self) -> bool:
        return self.jump_buf > 0 or self._held_jump

    _held_jump = False

    def _hurt(self):
        """Удар: со звездой — ничего; большой герой теряет усиление; обычный — жизнь."""
        if self.invuln > 0 or self.dying > 0 or self.star_t > 0:
            return
        if self.power > 0:
            self._shrink()
        else:
            self._lose_life()

    def _lose_life(self):
        if self.dying > 0:
            return
        self.lives = max(0, self.lives - 1)
        self.power = 0
        self.star_t = 0.0
        if self.ph > self.PH:
            self.y += self.ph - self.PH
            self.ph = self.PH
        self.fireballs.clear()
        self.dying = 0.9
        self._snd("death")
        self.vy = -560.0
        self.vx = 0.0


# =====================================================================================
# НОВОЕ: мини-игра «Астероиды» (классическая аркада с векторной графикой). Логика
# (AsteroidsEngine) не зависит от Qt и считает физику по времени кадра (dt): корабль с
# инерцией, зацикленный экран, лазер, дробление астероидов, волны, жизни. Виджет рисует
# кадр в paintEvent; цикл — QTimer ~60 кадров/с в основном потоке (игра очень лёгкая и не
# мешает фоновым потокам OCR).
# =====================================================================================
MINIGAME_ASTEROIDS_KEY = "minigame_asteroids_highscore"


class AsteroidsEngine(GameSfxMixin):
    """Чистая логика «Астероидов» (без Qt). Поле W×H замкнуто: всё, что вылетает за край,
    появляется с противоположной стороны. Угол корабля 0 — «вверх», растёт по часовой."""

    W, H = 520, 560
    SHIP_R = 10
    ROT_SPEED = 4.4                          # рад/с
    THRUST, MAX_SPEED, DRAG = 280.0, 340.0, 0.25
    BULLET_SPEED, BULLET_LIFE, MAX_BULLETS, FIRE_CD = 520.0, 1.0, 5, 0.2
    SIZES = {3: (40.0, 20), 2: (22.0, 50), 1: (11.0, 100)}   # размер: (радиус, очки)
    LIVES, MAX_LIVES, BONUS_EVERY = 3, 5, 5000

    def __init__(self, high_score: int = 0):
        self.high = max(0, int(high_score))
        self.state = "ready"                 # ready / playing / paused / over
        self.new_game()

    # ---------- подготовка ----------
    def new_game(self):
        self.score = 0
        self.lives = self.LIVES
        self.level = 1
        self.record_beaten = False
        self.next_bonus = self.BONUS_EVERY
        self.t = 0.0
        self.bullets, self.asteroids, self.particles = [], [], []
        self.cooldown = 0.0
        self.banner = 2.0
        self.wave_t = 0.0                    # пауза перед следующей волной (0 — волна идёт)
        self.thrusting = False
        self.respawn_ship(invuln=0.0)
        self.spawn_wave()

    def respawn_ship(self, invuln=2.5):
        """Корабль в центре поля, неподвижный, носом вверх; короткая неуязвимость."""
        self.sx, self.sy = self.W / 2, self.H / 2
        self.sa = 0.0
        self.svx = self.svy = 0.0
        self.ship_alive = True
        self.dead_t = 0.0
        self.invuln = invuln

    def spawn_wave(self):
        count = min(3 + self.level, 10)
        for _ in range(count):
            while True:                      # рождаем астероиды подальше от корабля
                x, y = random.uniform(0, self.W), random.uniform(0, self.H)
                if math.hypot(x - self.sx, y - self.sy) > 170:
                    break
            self.asteroids.append(self._make_asteroid(3, x, y))

    def _make_asteroid(self, size, x, y):
        radius = self.SIZES[size][0]
        base = {3: (40, 70), 2: (70, 110), 1: (100, 150)}[size]
        speed = random.uniform(*base) * (1 + 0.07 * (self.level - 1))
        ang = random.uniform(0, math.tau)
        return {"x": x, "y": y, "vx": math.cos(ang) * speed, "vy": math.sin(ang) * speed,
                "size": size, "r": radius, "ang": random.uniform(0, math.tau),
                "spin": random.uniform(-1.2, 1.2),
                "shape": [random.uniform(0.72, 1.12) for _ in range(11)]}

    # ---------- управление ----------
    def start(self):
        if self.state in ("ready", "over"):
            if self.state == "over":
                self.new_game()
            self.state = "playing"

    def pause(self):
        if self.state == "playing":
            self.state = "paused"

    def resume(self):
        if self.state == "paused":
            self.state = "playing"

    # ---------- вспомогательное ----------
    def _add_score(self, pts: int):
        self.score += pts
        if self.score > self.high:
            self.high = self.score
            self.record_beaten = True
        while self.score >= self.next_bonus:             # дополнительная жизнь каждые 5000 очков
            self.next_bonus += self.BONUS_EVERY
            self.lives = min(self.MAX_LIVES, self.lives + 1)

    def _wrap(self, x, y):
        return x % self.W, y % self.H

    def _burst(self, x, y, count, speed, life=0.8, lines=False):
        for _ in range(count):
            ang = random.uniform(0, math.tau)
            sp = random.uniform(0.3, 1.0) * speed
            self.particles.append({"x": x, "y": y, "vx": math.cos(ang) * sp, "vy": math.sin(ang) * sp,
                                   "t": 0.0, "life": life * random.uniform(0.6, 1.0),
                                   "line": lines, "a": random.uniform(0, math.tau)})

    def _ship_destroyed(self):
        self.lives = max(0, self.lives - 1)
        self._snd("hit")
        self.ship_alive = False
        self.dead_t = 1.2
        self.thrusting = False
        self._burst(self.sx, self.sy, 22, 170, 1.0, lines=True)

    def _safe_to_respawn(self) -> bool:
        cx, cy = self.W / 2, self.H / 2
        return all(math.hypot(a["x"] - cx, a["y"] - cy) > a["r"] + 90 for a in self.asteroids)

    # ---------- один шаг игры ----------
    def update(self, dt: float, left: bool, right: bool, thrust: bool, fire: bool):
        if self.state != "playing":
            return
        dt = min(max(dt, 0.0), 0.05)
        self.t += dt
        self.banner = max(0.0, self.banner - dt)
        for p in self.particles:
            p["t"] += dt
            p["x"] += p["vx"] * dt
            p["y"] += p["vy"] * dt
        self.particles = [p for p in self.particles if p["t"] < p["life"]]
        self._step_ship(dt, left, right, thrust, fire)
        if self.state != "playing":
            return
        self._step_bullets(dt)
        for a in self.asteroids:
            a["x"], a["y"] = self._wrap(a["x"] + a["vx"] * dt, a["y"] + a["vy"] * dt)
            a["ang"] += a["spin"] * dt
        self._collide_bullets()
        self._collide_ship()
        self._step_waves(dt)

    def _step_ship(self, dt, left, right, thrust, fire):
        if not self.ship_alive:
            self.dead_t -= dt
            if self.dead_t <= 0:
                if self.lives <= 0:
                    self.state = "over"
                    self._snd("gameover")
                elif self._safe_to_respawn() or self.dead_t < -3.0:
                    self.respawn_ship()
            return
        self.invuln = max(0.0, self.invuln - dt)
        self.sa += (int(right) - int(left)) * self.ROT_SPEED * dt
        self.thrusting = thrust
        if thrust:                                        # тяга: ускорение вдоль носа корабля
            self._snd("thrust")
            self.svx += math.sin(self.sa) * self.THRUST * dt
            self.svy -= math.cos(self.sa) * self.THRUST * dt
            if random.random() < 0.7:                     # искры двигателя
                self.particles.append({"x": self.sx - math.sin(self.sa) * 11, "y": self.sy + math.cos(self.sa) * 11,
                                       "vx": self.svx - math.sin(self.sa) * 90 + random.uniform(-25, 25),
                                       "vy": self.svy + math.cos(self.sa) * 90 + random.uniform(-25, 25),
                                       "t": 0.0, "life": 0.25, "line": False, "a": 0.0})
        drag = max(0.0, 1.0 - self.DRAG * dt)             # лёгкое затухание: инерция остаётся заметной
        self.svx *= drag
        self.svy *= drag
        speed = math.hypot(self.svx, self.svy)
        if speed > self.MAX_SPEED:
            self.svx *= self.MAX_SPEED / speed
            self.svy *= self.MAX_SPEED / speed
        self.sx, self.sy = self._wrap(self.sx + self.svx * dt, self.sy + self.svy * dt)
        self.cooldown = max(0.0, self.cooldown - dt)
        if fire and self.cooldown <= 0 and len(self.bullets) < self.MAX_BULLETS:
            dx, dy = math.sin(self.sa), -math.cos(self.sa)
            self.bullets.append({"x": self.sx + dx * 12, "y": self.sy + dy * 12,
                                 "vx": dx * self.BULLET_SPEED + self.svx * 0.5,
                                 "vy": dy * self.BULLET_SPEED + self.svy * 0.5, "t": 0.0})
            self.cooldown = self.FIRE_CD
            self._snd("shoot")

    def _step_bullets(self, dt):
        keep = []
        for b in self.bullets:
            b["t"] += dt
            b["x"], b["y"] = self._wrap(b["x"] + b["vx"] * dt, b["y"] + b["vy"] * dt)
            if b["t"] < self.BULLET_LIFE:
                keep.append(b)
        self.bullets = keep

    def _collide_bullets(self):
        for b in list(self.bullets):
            for a in self.asteroids:
                if math.hypot(b["x"] - a["x"], b["y"] - a["y"]) < a["r"] * 0.92 + 2:
                    self.bullets.remove(b)
                    self._split(a)
                    break

    def _split(self, a):
        """Попадание: большой астероид -> два средних, средний -> два малых, малый исчезает."""
        self.asteroids.remove(a)
        self._add_score(self.SIZES[a["size"]][1])
        self._snd("explode" if a["size"] >= 3 else "explode_small")
        self._burst(a["x"], a["y"], 6 + 3 * a["size"], 90 + 30 * a["size"], 0.7)
        if a["size"] > 1:
            for _ in range(2):
                child = self._make_asteroid(a["size"] - 1, a["x"], a["y"])
                self.asteroids.append(child)

    def _collide_ship(self):
        if not self.ship_alive or self.invuln > 0:
            return
        for a in self.asteroids:
            if math.hypot(self.sx - a["x"], self.sy - a["y"]) < a["r"] * 0.9 + self.SHIP_R * 0.8:
                self._ship_destroyed()
                return

    def _step_waves(self, dt):
        if self.asteroids:
            return
        if self.wave_t <= 0:
            self.wave_t = 1.6                             # волна уничтожена — короткая пауза
            return
        self.wave_t -= dt
        if self.wave_t <= 0:
            self.level += 1
            self.banner = 2.0
            self._snd("win")
            self.spawn_wave()


# =====================================================================================
# НОВОЕ: «Колесо Фортуны» (кнопка «Испытай судьбу» на вкладке «Стафф»).
#   * FORTUNE_* / _fortune_sound_files — звуки синтезируются при первом открытии и
#     сохраняются во временную папку (WAV): внешние файлы не нужны;
#   * FortuneSounds — фоновая тема, «тики» на каждом штифте, шум вращения (его громкость
#     следует за скоростью колеса) и победный перезвон; QSoundEffect, при любом сбое —
#     тишина без падения приложения;
#   * FortuneWheel — рисованное колесо и физика с инерцией: случайная начальная скорость,
#     три профиля торможения (быстрая остановка / долгий накат / «интрига» с ползущим
#     замедлением) и штифты на границах секторов, о которые колесо теряет энергию, из-за
#     чего оно может «перевалить» через сектор или откатиться назад;
#   * FortuneDialog — окно с вступительным текстом, редактируемым списком вариантов,
#     колесом, кнопкой «Удачи!» и карточкой победы;
#   * PulsingGlow — плавное «дыхание» свечения кнопки (прозрачность тени 0.4 -> 1.0).
# =====================================================================================
FORTUNE_INTRO_TEXT = ("Сомневаешься? Боишься сделать шаг, который изменит всё? Не пытайся предугадать судьбу - "
                      "доверься ей. Передай бразды правления в надёжные руки Госпожи Фортуны. "
                      "Пусть её колесо решит за тебя. Крути и узнай, что уготовано.")


FORTUNE_INTRO_TEXT_SAKURA = ("Лепесток сакуры не выбирает, куда упасть, — его несёт ветер судьбы. "
                             "Так и ты: не спорь с небом, прими дары, что протягивает тебе Госпожа Фортуна.")


FORTUNE_INTRO_TEXT_NTE = ("Хватит строить из себя героя. В Этеро удача решает всё: от утреннего кофе до того, "
                          "доживёшь ли ты до следующего заказа. Боишься, что твой выбор всё сломает? Расслабься. "
                          "Отдайся в надёжные объятия Госпожи Фортуны - она хотя бы честно играет по своим правилам.")


FORTUNE_INTRO_TEXT_PAWS = ("«Кто сказал, что маленькие лапки не решают большие судьбы? Ещё как решают - просто делают это мило. "
                           "Белый котёнок уже тянет лапку к колесу: дом, вкусняшка или новое приключение? "
                           "Пусть Госпожа Фортуна улыбнётся - а ты просто наслаждайся подарком.»")


FORTUNE_STYLE_KEY = "fortune_style"               # ключ в таблице settings: выбранный стиль ("classic" / "nte" / "sakura" / "paws")


FORTUNE_NTE_KEY = "fortune_nte_style"            # ключ в таблице settings: включён ли «Стиль NTE» ("1" / "0")


FORTUNE_DEFAULT_OPTIONS = ("Да, действуй!", "Нет, не стоит", "Подожди до завтра", "Рискни!",
                           "Спроси совета у друга", "Сделай первый шаг", "Отложи на неделю",
                           "Доверься интуиции")


FORTUNE_MIN_OPTIONS, FORTUNE_MAX_OPTIONS = 1, 24   # крутить можно и с одним вариантом; список при каждом открытии пуст


FORTUNE_COLORS = ("#e94f64", "#f0a43c", "#f2d24b", "#5cc47a", "#3fb7c9", "#4a7be8", "#8a5ce0", "#d65bb8",
                  "#ff7a59", "#7bd0a0")


# ---------- темы оформления: классическая и «Стиль NTE» (киберпанк ночного города) ----------
_FORTUNE_BTN_GRAD = "qlineargradient(x1:0,y1:0,x2:0,y2:1, stop:0 {a}, stop:1 {b})"


FORTUNE_THEMES = {
    "classic": {
        "bg": ("#120c24", "#241540"),
        "card": ("#34204f", "#1b1233"), "card_border": "#d9b45a",
        "title": "#ffd98a", "intro": "#f6e7bd",
        "panel_bg": "rgba(255,255,255,18)", "panel_border": "rgba(217,180,90,120)",
        "head": "#ffd98a", "hint": "#b8a8d8",
        "list_bg": "rgba(10,6,25,170)", "list_fg": "#f3ecff", "field_border": "#5a4690", "select": "#6a4bb0",
        "btn_bg": "#3b2a66", "btn_fg": "#f3ecff", "btn_border": "#6a4bb0", "btn_hover": "#4b3680",
        "btn_dis": ("#8a80a8", "#2a2048", "#3e3463"),
        "spin": (_FORTUNE_BTN_GRAD.format(a="#ffe08a", b="#d9a52e"), "#3b2400", "#fff2b8",
                 _FORTUNE_BTN_GRAD.format(a="#fff0b0", b="#e8b542")),
        "spin_dis": ("#6b5a3a", "#2a1d08", "#8a7a52"),
        "check": "#d8c8f8", "spin_glow": None, "select_fg": "#ffffff", "edit_fg": "#ffffff",
        "title_text": "✦  КОЛЕСО ФОРТУНЫ  ✦", "win_top": "ВЫПАЛО", "win_sub": "Госпожа решила твою судьбу",
        "intro_text": FORTUNE_INTRO_TEXT,
        "win": {"bg": ("#3c2466", "#1a1030"), "border": "#ffe27a", "top": "#ffd98a", "text": "#ffffff",
                "sub": "#ffe27a", "btn_bg": "#d9a52e", "btn_fg": "#3b2400", "btn_border": "#fff2b8",
                "btn_hover": "#f0be48"},
        "wheel": {"colors": FORTUNE_COLORS, "edge": (30, 20, 50, 200), "aura": (255, 210, 110),
                  "rim": "#d9b45a", "rim2": None, "neon": False, "peg": ("#fff6cf", "#b8892a"),
                  "hub": ("#fff2b8", "#b8892a", "#6b4a14"), "star": "#6b4a14",
                  "ptr": ("#ffcf4a", "#4a2a00", "#fff2b8"), "win": (255, 240, 160), "win_edge": (255, 226, 122),
                  "text_dark": "#1b1230", "text_light": "#ffffff",
                  "rim_glow": None, "rim_w": 0.045, "hub_pen": 1.0, "ptr_glow": None, "ptr_sharp": False,
                  "blossom": False, "petals": False},
    },
    "nte": {                                              # глубокий ночной фиолет, неоновый циан и розовый
        "bg": ("#0d0c1d", "#1a1233"),
        "card": ("rgba(25, 20, 45, 217)", "rgba(35, 24, 64, 217)"), "card_border": "#00f0ff",
        "title": "#00f0ff", "intro": "#e6ecff",
        "panel_bg": "rgba(25, 20, 45, 217)", "panel_border": "#ff2a8d",
        "head": "#ff4fa3", "hint": "#8fa4d8",
        "list_bg": "rgba(13, 12, 29, 200)", "list_fg": "#e6f7ff", "field_border": "#00b8cc", "select": "#ff2a8d",
        "btn_bg": "#1c1740", "btn_fg": "#d9f7ff", "btn_border": "#00f0ff", "btn_hover": "#2a2262",
        "btn_dis": ("#6f7aa8", "#161230", "#2a3a6a"),
        "spin": ("qlineargradient(x1:0,y1:0,x2:1,y2:0, stop:0 #00f0ff, stop:1 #ff2a8d)", "#0d0c1d", "#ffffff",
                 "qlineargradient(x1:0,y1:0,x2:1,y2:0, stop:0 #6ff7ff, stop:1 #ff6fb2)"),
        "spin_dis": ("#2b2a4a", "#6f7aa8", "#3a3a6a"),
        "check": "#9fe9ff", "spin_glow": "#00f0ff", "select_fg": "#ffffff", "edit_fg": "#ffffff",
        "title_text": "✦ NTE FORTUNE WHEEL ✦", "win_top": "✦ ВЫПАЛО ✦", "win_sub": "✦ ГОСПОЖА РЕШИЛА ТВОЮ СУДЬБУ ✦",
        "intro_text": FORTUNE_INTRO_TEXT_NTE,
        "win": {"bg": ("rgba(25, 20, 45, 235)", "rgba(40, 20, 70, 235)"), "border": "#00f0ff", "top": "#ff4fa3",
                "text": "#ffffff", "sub": "#00f0ff", "btn_bg": "#ff2a8d", "btn_fg": "#ffffff",
                "btn_border": "#00f0ff", "btn_hover": "#ff5fa8"},
        "wheel": {"colors": ("#00e5ff", "#ff2a8d", "#9b5cff", "#ffc83d", "#2b3a6b"), "edge": (13, 12, 29, 230),
                  "aura": (0, 240, 255), "rim": "#00f0ff", "rim2": "#ff2a8d", "neon": True,
                  "peg": ("#eaffff", "#00a8c8"), "hub": ("#2a2062", "#0d0c1d", "#00f0ff"), "star": "#ff2a8d",
                  "ptr": ("#ff2a8d", "#00f0ff", "#ffffff"), "win": (0, 240, 255), "win_edge": (255, 42, 141),
                  "text_dark": "#0d0c1d", "text_light": "#ffffff",
                  "rim_glow": "#00f0ff", "rim_w": 0.032, "hub_pen": 1.6, "ptr_glow": "#00f0ff", "ptr_sharp": True,
                  "blossom": False, "petals": False},
    },
    "sakura": {                                           # японская эстетика: нежно-розовый, слоновая кость, багрянец и золото
        "bg": ("#fff0f5", "#fadadd"),
        "card": ("rgba(255, 255, 255, 215)", "rgba(255, 226, 234, 215)"), "card_border": "#e6ca65",
        "title": "#dc143c", "intro": "#6b2a3c",
        "panel_bg": "rgba(255, 255, 255, 175)", "panel_border": "#ffb7c5",
        "head": "#dc143c", "hint": "#9a6a78",
        "list_bg": "rgba(255, 255, 255, 225)", "list_fg": "#4a2630", "field_border": "#ffb7c5", "select": "#ffb7c5",
        "btn_bg": "#ffdbe4", "btn_fg": "#7a1230", "btn_border": "#ffb7c5", "btn_hover": "#ffc4d2",
        "btn_dis": ("#b79aa3", "#fbe9ee", "#f1cdd6"),
        "spin": ("qlineargradient(x1:0,y1:0,x2:0,y2:1, stop:0 #ff8aa5, stop:1 #dc143c)", "#ffffff", "#e6ca65",
                 "qlineargradient(x1:0,y1:0,x2:0,y2:1, stop:0 #ffa3b8, stop:1 #e8405e)"),
        "spin_dis": ("#efc9d2", "#a47c86", "#e6ca65"),
        "check": "#7a1230", "spin_glow": "#ff8fa8", "select_fg": "#4a1020", "edit_fg": "#4a2630",
        "title_text": "✿  КОЛЕСО ФОРТУНЫ  ✿", "win_top": "✦ СУДЬБА ОПУСТИЛАСЬ КАК ЛЕПЕСТОК САКУРЫ ✦",
        "win_sub": "Госпожа решила твою судьбу",
        "intro_text": FORTUNE_INTRO_TEXT_SAKURA,
        "win": {"bg": ("#fff9fb", "#ffdce5"), "border": "#e6ca65", "top": "#dc143c", "text": "#4a1020",
                "sub": "#a8324d", "btn_bg": "#dc143c", "btn_fg": "#ffffff", "btn_border": "#e6ca65",
                "btn_hover": "#e8405e"},
        "wheel": {"colors": ("#ffb7c5", "#d63a5c", "#fff6ea", "#ffc9a8", "#e6ca65", "#b8735c"),
                  "edge": (255, 255, 255, 235), "aura": (255, 183, 197), "rim": "#e6ca65", "rim2": "#dc143c",
                  "neon": False, "peg": ("#fff6ea", "#e6ca65"), "hub": ("#fff6ea", "#ffb7c5", "#e6ca65"),
                  "star": "#dc143c", "ptr": ("#dc143c", "#e6ca65", "#fff6ea"), "win": (255, 255, 255),
                  "win_edge": (220, 20, 60), "text_dark": "#4a1020", "text_light": "#ffffff",
                  "rim_glow": "#ff8fa8", "rim_w": 0.04, "hub_pen": 1.3, "ptr_glow": "#ff8fa8", "ptr_sharp": True,
                  "blossom": True, "petals": True},
    },
    "paws": {                                             # «Белые лапки»: уютный дом, кремовое молоко, персик и тёплый шоколад
        "bg": ("#fdfbf7", "#f4ecd8"),
        "card": ("rgba(255, 252, 245, 220)", "rgba(244, 236, 216, 220)"), "card_border": "#d9c3a9",
        "title": "#8b5e3c", "intro": "#6b4a32",
        "panel_bg": "rgba(255, 251, 243, 185)", "panel_border": "#e6b89c",
        "head": "#9a6a44", "hint": "#a38a74",
        "list_bg": "rgba(255, 252, 246, 230)", "list_fg": "#4a3220", "field_border": "#d9c3a9", "select": "#e6b89c",
        "btn_bg": "#f4ecd8", "btn_fg": "#6b4528", "btn_border": "#d9c3a9", "btn_hover": "#f0dfc2",
        "btn_dis": ("#b5a28c", "#f6eee0", "#e8dcc6"),
        "spin": (_FORTUNE_BTN_GRAD.format(a="#f8d3b0", b="#e0a068"), "#4a2a12", "#fff3d6",
                 _FORTUNE_BTN_GRAD.format(a="#fbdfc3", b="#e8b07a")),
        "spin_dis": ("#ece0cb", "#a89580", "#d9c3a9"),
        "check": "#7a5334", "spin_glow": "#f0b98a", "select_fg": "#4a2a12", "edit_fg": "#4a3220",
        "title_text": "🐾  КОЛЕСО ФОРТУНЫ  🐾", "win_top": "✦ МИЛАЯ ЛАПКА РЕШИЛА ТВОЮ СУДЬБУ ✦",
        "win_sub": "Госпожа решила твою судьбу",
        "intro_text": FORTUNE_INTRO_TEXT_PAWS,
        "win": {"bg": ("#fffdf8", "#f6e6cf"), "border": "#d9a86a", "top": "#b9794a", "text": "#4a2e1a",
                "sub": "#9a6a44", "btn_bg": "#e6b89c", "btn_fg": "#4a2a12", "btn_border": "#fff3d6",
                "btn_hover": "#efc9ae"},
        "wheel": {"colors": ("#f7d9c4", "#e8b04f", "#fff6e6", "#8b5e3c", "#e6b89c", "#d9c3a9", "#f4ecd8", "#b9794a"),
                  "edge": (253, 251, 247, 240), "aura": (240, 200, 160), "rim": "#c9a27a", "rim2": "#e6b89c",
                  "neon": False, "peg": ("#fff6e6", "#d9c3a9"), "hub": ("#fff6e6", "#f4d9c2", "#c9a27a"),
                  "star": "#8b5e3c", "ptr": ("#e0a95a", "#6b4423", "#fff3d6"), "win": (255, 240, 200),
                  "win_edge": (184, 115, 70), "text_dark": "#4a2e1a", "text_light": "#fffaf0",
                  "rim_glow": "#f0c9a0", "rim_w": 0.042, "hub_pen": 1.3, "ptr_glow": "#f0c9a0", "ptr_sharp": False,
                  "blossom": False, "petals": False, "paws": True, "dim": (120, 84, 52, 105)},
    },
}


# ---------- свои звуки ----------
# Положите WAV-файлы в папку  assets/audio/fortune/  рядом с main.py (или рядом с базой данных):
#   ambient.wav — фоновая тема (звучит по кругу, пока открыто окно колеса)
#   spin.wav    — шум вращения (по кругу; громкость следует за скоростью колеса)
#   tick.wav    — короткий щелчок штифта (проигрывается на каждом секторе)
#   win.wav     — победный звук после остановки
# Любой файл можно не класть — тогда вместо него играет встроенный синтезированный звук.
# Формат: несжатый PCM WAV (QSoundEffect не читает mp3 / ogg). Файлы подхватываются при открытии окна.
FORTUNE_SOUND_DIR = "assets/audio/fortune"


FORTUNE_SOUND_FILES = {"ambient": "ambient.wav", "whirr": "spin.wav", "tick": "tick.wav", "win": "win.wav"}


def fortune_sound_dir() -> Path:
    return app_dir() / FORTUNE_SOUND_DIR


def _fortune_custom_file(key: str, theme: str = "classic"):
    """Путь к своему звуку из assets/audio/fortune (без учёта регистра имени) или None.
    Классическая тема берёт ambient.wav / spin.wav / tick.wav / win.wav, «Стиль NTE» —
    nte_ambient.wav / nte_spin.wav / nte_tick.wav / nte_win.wav, «Сакура» —
    sakura_ambient.wav / sakura_spin.wav / sakura_tick.wav / sakura_win.wav, «Белые лапки» —
    paws_ambient.wav / paws_spin.wav / paws_tick.wav / paws_win.wav."""
    wanted = {"nte": "nte_", "sakura": "sakura_", "paws": "paws_"}.get(theme, "") + FORTUNE_SOUND_FILES[key]
    roots = [app_dir()] + ([Path(_DATA_DIR)] if _DATA_DIR is not None else [])
    for root in roots:
        folder = root / FORTUNE_SOUND_DIR
        try:
            if folder.is_dir():
                for p in folder.iterdir():
                    if p.is_file() and p.name.lower() == wanted:
                        return p
        except OSError:
            continue
    return None


# ---------- синтез звуков ----------
_FORTUNE_SOUNDS = {}                              # {тема: {имя: путь}}


_FORTUNE_DIR = []                                 # временная папка со звуками (создаётся один раз)


def _fortune_write_wav(path, samples, rate):
    """Записывает список чисел -1..1 в 16-битный моно WAV."""
    data = array.array("h", [max(-32767, min(32767, int(v * 32767))) for v in samples])
    if sys.byteorder == "big":
        data.byteswap()
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(data.tobytes())


def _fortune_normalize(samples, peak):
    top = max((abs(v) for v in samples), default=1.0) or 1.0
    return [v * peak / top for v in samples]


def _synth_classic(folder: Path) -> dict:
    """Классический набор: механические щелчки, мягкий «лаунж»-пэд с колокольчиками, шум вращения
    и победный перезвон."""
    rnd = random.Random(42)
    # «тики»: три высоты — чем быстрее колесо, тем выше и суше щелчок
    rate = 22050
    for name, freq in (("tick_low", 900.0), ("tick_mid", 1400.0), ("tick_high", 2100.0)):
        n = int(rate * 0.05)
        s = [(math.sin(math.tau * freq * i / rate) * math.exp(-i / rate * 120)
              + (rnd.random() - 0.5) * 0.5 * math.exp(-i / rate * 400)) for i in range(n)]
        _fortune_write_wav(folder / f"{name}.wav", _fortune_normalize(s, 0.7), rate)
    # шум вращения: сглаженный шум, склеенный по кругу (плавный переход конца в начало)
    n = int(rate * 1.2)
    lp, noise = 0.0, []
    for _ in range(n):
        lp += 0.12 * ((rnd.random() - 0.5) - lp)
        noise.append(lp)
    fade = int(rate * 0.08)
    for i in range(fade):
        k = i / fade
        noise[i] = noise[i] * k + noise[n - fade + i] * (1 - k)
    noise = noise[:n - fade]
    _fortune_write_wav(folder / "whirr.wav", _fortune_normalize(noise, 0.6), rate)
    # фоновая тема: тихий «пэд» + редкие колокольчики; все частоты кратны 1/8 Гц, поэтому
    # петля длиной 8 секунд замыкается без щелчка
    rate_a, length = 11025, 8.0
    total = int(rate_a * length)
    snap = lambda f: round(f * 8) / 8.0
    pad = [(snap(220.0), 0.30), (snap(329.63), 0.22), (snap(440.0), 0.18), (snap(523.25), 0.12),
           (snap(220.0) + 0.25, 0.18), (snap(329.63) - 0.25, 0.12)]
    bells = [(0.0, 880.0), (1.0, 659.25), (2.0, 784.0), (3.0, 659.25), (4.0, 1046.5), (5.0, 880.0),
             (6.0, 784.0), (7.0, 659.25)]
    amb = []
    for i in range(total):
        t = i / rate_a
        v = 0.0
        for f, a in pad:
            v += a * math.sin(math.tau * f * t)
        v *= 0.55 + 0.45 * math.sin(math.tau * t / 8.0) ** 2
        amb.append(v)
    for start, f in bells:                            # колокольчики с хвостом, переходящим через границу петли
        f = snap(f)
        for i in range(int(rate_a * 2.4)):
            idx = (int(start * rate_a) + i) % total
            t = i / rate_a
            amb[idx] += 0.16 * math.sin(math.tau * f * t) * math.exp(-t * 2.2)
    _fortune_write_wav(folder / "ambient.wav", _fortune_normalize(amb, 0.55), rate_a)
    # победный перезвон: арпеджио до-мажора + мерцающий аккорд и лёгкое эхо
    rate = 22050
    n = int(rate * 2.6)
    win = [0.0] * n
    for k, f in enumerate((523.25, 659.25, 783.99, 1046.5)):
        t0 = int(rate * 0.11 * k)
        for i in range(n - t0):
            t = i / rate
            e = math.exp(-t * 2.4)
            win[t0 + i] += e * (math.sin(math.tau * f * t) + 0.3 * math.sin(math.tau * 2 * f * t)
                                + 0.12 * math.sin(math.tau * 3 * f * t))
    t0 = int(rate * 0.5)
    for f in (783.99, 1046.5, 1318.5):
        for i in range(n - t0):
            t = i / rate
            win[t0 + i] += 0.5 * math.exp(-t * 1.5) * math.sin(math.tau * f * t) * (0.8 + 0.2 * math.sin(math.tau * 6 * t))
    delay = int(rate * 0.18)
    for i in range(n - 1, delay - 1, -1):
        win[i] += 0.32 * win[i - delay]
    _fortune_write_wav(folder / "win.wav", _fortune_normalize(win, 0.85), rate)
    return {name: folder / f"{name}.wav" for name in ("tick_low", "tick_mid", "tick_high", "whirr", "ambient", "win")}


def _synth_nte(folder: Path) -> dict:
    """Набор «Стиль NTE»: синтвейв-фон (бас, пэд, арпеджио, бочка, хэт), электронные блипы вместо
    щелчков, киберпанковый гул вращения и энергичный победный «стаб». Все петли замыкаются бесшовно."""
    rnd = random.Random(7)
    saw = lambda f, t: 2.0 * ((f * t) % 1.0) - 1.0
    # электронные тики: прямоугольная волна с быстрым падением высоты
    rate = 22050
    for name, freq in (("tick_low", 1100.0), ("tick_mid", 1700.0), ("tick_high", 2600.0)):
        n, ph, s = int(rate * 0.045), 0.0, []
        for i in range(n):
            t = i / rate
            ph += freq * (1 + 0.6 * math.exp(-t * 70)) / rate
            s.append((1.0 if ph % 1.0 < 0.5 else -1.0) * math.exp(-t * 85) * 0.8
                     + (rnd.random() - 0.5) * 0.25 * math.exp(-t * 300))
        _fortune_write_wav(folder / f"{name}.wav", _fortune_normalize(s, 0.7), rate)
    # гул вращения: пила + шумоподобная сумма синусоид; все частоты кратны 1/1.2 Гц — петля без щелчка
    n = int(rate * 1.2)
    f0 = 100 / 1.2
    comps = [(rnd.randint(120, 3000) / 1.2, rnd.uniform(0, math.tau)) for _ in range(24)]
    whirr = []
    for i in range(n):
        t = i / rate
        tonal = 0.55 * saw(f0, t) + 0.25 * saw(2 * f0, t)
        grit = sum(math.sin(math.tau * f * t + ph) for f, ph in comps) / 8.0
        whirr.append((tonal + 0.35 * grit) * (0.75 + 0.25 * math.sin(math.tau * 10 * t / 1.2)))
    _fortune_write_wav(folder / "whirr.wav", _fortune_normalize(whirr, 0.55), rate)
    # фон: синтвейв 120 BPM, 4 такта (Am – F – C – G) = 8 секунд; ноты начинаются и заканчиваются в тишине
    rate_a = 11025
    total = int(rate_a * 8.0)
    amb = [0.0] * total
    chords = ((55.0, (220.0, 261.63, 329.63)), (43.65, (174.61, 220.0, 261.63)),
              (65.41, (261.63, 329.63, 392.0)), (49.0, (196.0, 246.94, 293.66)))
    for bar, (root, chord) in enumerate(chords):
        base = int(bar * 2.0 * rate_a)
        for i in range(int(2.0 * rate_a)):               # пэд: две расстроенные пилы на ноту
            t = i / rate_a
            env = math.sin(math.pi * t / 2.0) ** 0.6
            amb[base + i] += env * sum(0.06 * (saw(f * 1.004, t) + saw(f * 0.996, t)) for f in chord)
        for step in range(8):                             # бас восьмыми
            for i in range(int(0.25 * rate_a)):
                t = i / rate_a
                env = math.exp(-t * 6) * min(1.0, (0.25 - t) / 0.01)
                amb[base + int(step * 0.25 * rate_a) + i] += 0.30 * env * (0.5 * saw(root, t) + 0.5 * math.sin(math.tau * root * t))
        for step in range(16):                            # арпеджио шестнадцатыми
            f = chord[(0, 1, 2, 1)[step % 4]] * 2
            for i in range(int(0.125 * rate_a)):
                t = i / rate_a
                env = math.exp(-t * 14) * min(1.0, (0.125 - t) / 0.008)
                amb[base + int(step * 0.125 * rate_a) + i] += 0.15 * env * (saw(f, t) + (1.0 if (f * t) % 1.0 < 0.5 else -1.0))
    for beat in range(16):                                # бочка на каждую долю и «хэт» между ними
        base = int(beat * 0.5 * rate_a)
        ph = 0.0
        for i in range(int(0.22 * rate_a)):
            t = i / rate_a
            ph += (45 + 90 * math.exp(-t * 18)) / rate_a
            amb[base + i] += 0.85 * math.sin(math.tau * ph) * math.exp(-t * 14) * min(1.0, (0.22 - t) / 0.01)
        hat = base + int(0.25 * rate_a)
        for i in range(int(0.04 * rate_a)):
            amb[hat + i] += 0.16 * (rnd.random() - 0.5) * math.exp(-i / rate_a * 90)
    _fortune_write_wav(folder / "ambient.wav", _fortune_normalize(amb, 0.55), rate_a)
    # победа: «райзер» + быстрое арпеджио + аккорд-стаб с басом и эхо
    n = int(rate * 2.6)
    win = [0.0] * n
    ph = 0.0
    for i in range(int(rate * 0.5)):                      # нарастающий свист
        t = i / rate
        ph += (300 + 3000 * t) / rate
        win[i] += 0.28 * math.sin(math.tau * ph) * (t / 0.5)
    for k, f in enumerate((440.0, 523.25, 659.25, 880.0, 1046.5, 1318.5)):
        t0 = int(rate * 0.07 * k)
        for i in range(min(n - t0, int(rate * 0.55))):
            t = i / rate
            win[t0 + i] += 0.30 * math.exp(-t * 5) * (0.6 * saw(f, t) + 0.4 * (1.0 if (f * t) % 1.0 < 0.5 else -1.0))
    t0 = int(rate * 0.5)
    ph = 0.0
    for i in range(n - t0):
        t = i / rate
        e = math.exp(-t * 2.2)
        stab = sum(saw(f * d, t) for f in (440.0, 523.25, 659.25, 987.77) for d in (0.997, 1.003))
        ph += (50 + 110 * math.exp(-t * 18)) / rate
        win[t0 + i] += 0.07 * e * stab + 0.55 * math.sin(math.tau * 110 * t) * e + 0.8 * math.sin(math.tau * ph) * math.exp(-t * 12)
    delay = int(rate * 0.15)
    for i in range(n - 1, delay - 1, -1):
        win[i] += 0.3 * win[i - delay]
    _fortune_write_wav(folder / "win.wav", _fortune_normalize(win, 0.9), rate)
    return {name: folder / f"{name}.wav" for name in ("tick_low", "tick_mid", "tick_high", "whirr", "ambient", "win")}


def _fortune_ks_pluck(freq: float, rate: int, seconds: float, rnd, decay: float = 0.996) -> list:
    """Щипок струны (алгоритм Карплюса — Стронга): звучит как кото / сямисэн."""
    size = max(2, int(rate / freq))
    buf = [rnd.uniform(-1.0, 1.0) for _ in range(size)]
    for _ in range(2):                                    # сглаживание начального «шума» — звук мягче, как у кото
        buf = [(buf[i] + buf[(i + 1) % size]) * 0.5 * 1.4 for i in range(size)]
    out, idx = [], 0
    for _ in range(int(rate * seconds)):
        out.append(buf[idx])
        nxt = buf[(idx + 1) % size]
        buf[idx] = decay * 0.5 * (buf[idx] + nxt)
        idx = (idx + 1) % size
    return out


def _synth_sakura(folder: Path) -> dict:
    """Набор «Сакура»: фон из кото и сякухати на ладу «ин» (A B♭ D E F), деревянные / бамбуковые щелчки,
    шелест бамбука при вращении и победный храмовый колокол с дзен-чашей. Петля фона замыкается бесшовно."""
    rnd = random.Random(21)
    # деревянные «тики»: короткий резонанс колодки + щелчок
    rate = 22050
    for name, freq in (("tick_low", 620.0), ("tick_mid", 880.0), ("tick_high", 1250.0)):
        n = int(rate * 0.07)
        s = []
        for i in range(n):
            t = i / rate
            s.append(math.sin(math.tau * freq * t) * math.exp(-t * 55)
                     + 0.45 * math.sin(math.tau * freq * 2.4 * t) * math.exp(-t * 90)
                     + (rnd.random() - 0.5) * 0.7 * math.exp(-t * 400))
        _fortune_write_wav(folder / f"{name}.wav", _fortune_normalize(s, 0.7), rate)
    # шелест бамбука: «шумоподобная» сумма синусоид (кратны 1/1.2 Гц — петля без щелчка) + тихий колокольчик
    n = int(rate * 1.2)
    comps = [(rnd.randint(350, 2400) / 1.2, rnd.uniform(0, math.tau)) for _ in range(20)]
    whirr = []
    for i in range(n):
        t = i / rate
        grit = sum(math.sin(math.tau * f * t + ph) for f, ph in comps) / 10.0
        whirr.append(grit * (0.65 + 0.35 * math.sin(math.tau * 5 * t / 1.2))
                     + 0.25 * math.sin(math.tau * (1800 / 1.2) * t) * (0.5 + 0.5 * math.sin(math.tau * 2 * t / 1.2)))
    _fortune_write_wav(folder / "whirr.wav", _fortune_normalize(whirr, 0.5), rate)
    # фон: 8 секунд, лад «ин» на ля; кото (щипки), басовый бурдон, две фразы сякухати и далёкий фурин
    rate_a = 11025
    total = int(rate_a * 8.0)
    amb = [0.0] * total
    A3, BB3, D4, E4, F4, A4, BB4, D5 = 220.0, 233.08, 293.66, 329.63, 349.23, 440.0, 466.16, 587.33
    melody = (A4, E4, F4, E4, D4, E4, A3, D4, E4, F4, A4, F4, E4, D4, BB3, A3)       # 16 нот по 0.5 с
    for k, f in enumerate(melody):
        pluck = _fortune_ks_pluck(f, rate_a, 1.6, rnd, 0.9965)
        start = int(k * 0.5 * rate_a)
        for i, v in enumerate(pluck):
            amb[(start + i) % total] += 0.35 * v * (1.0 - i / len(pluck)) ** 0.5
    for i in range(total):                                # бурдон на ля: плавное «дыхание»
        t = i / rate_a
        amb[i] += 0.10 * math.sin(math.tau * 110.0 * t) * (0.6 + 0.4 * math.sin(math.tau * t / 8.0 + 1.0) ** 2)
    for start_s, length_s, f in ((0.5, 3.0, A4), (4.5, 3.0, D5)):      # сякухати: тон, дыхание, вибрато
        start = int(start_s * rate_a)
        for i in range(int(length_s * rate_a)):
            t = i / rate_a
            env = math.sin(math.pi * t / length_s) ** 1.5
            vib = 1.0 + 0.006 * math.sin(math.tau * 5.0 * t)
            tone = math.sin(math.tau * f * vib * t) + 0.25 * math.sin(math.tau * 2 * f * t)
            breath = (rnd.random() - 0.5) * 0.35
            amb[(start + i) % total] += 0.16 * env * (tone + breath)
    for start_s in (1.75, 5.75):                          # ветряной колокольчик
        start = int(start_s * rate_a)
        for i in range(int(1.4 * rate_a)):
            t = i / rate_a
            amb[(start + i) % total] += 0.06 * math.sin(math.tau * 2093.0 * t) * math.exp(-t * 4)
    _fortune_write_wav(folder / "ambient.wav", _fortune_normalize(amb, 0.55), rate_a)
    # победа: быстрое глиссандо кото вверх по ладу, храмовый колокол и дзен-чаша
    n = int(rate * 3.4)
    win = [0.0] * n
    for k, f in enumerate((A3, D4, E4, F4, A4, BB4, D5)):
        pluck = _fortune_ks_pluck(f, rate, 1.2, rnd, 0.9965)
        start = int(rate * 0.06 * k)
        for i, v in enumerate(pluck):
            if start + i < n:
                win[start + i] += 0.30 * v * (1.0 - i / len(pluck)) ** 0.5
    t0 = int(rate * 0.45)
    for ratio, amp, dec in ((1.0, 1.0, 1.1), (2.0, 0.6, 1.5), (2.76, 0.5, 1.8), (5.4, 0.3, 2.6), (8.93, 0.15, 3.5)):
        f = 196.0 * ratio                                 # колокол: негармонические обертоны
        for i in range(n - t0):
            t = i / rate
            win[t0 + i] += 0.40 * amp * math.sin(math.tau * f * t) * math.exp(-t * dec)
    t1 = int(rate * 0.9)
    for f, amp in ((880.0, 0.5), (883.0, 0.5)):           # дзен-чаша: два близких тона дают плавные биения
        for i in range(n - t1):
            t = i / rate
            win[t1 + i] += 0.25 * amp * math.sin(math.tau * f * t) * math.exp(-t * 1.0) * min(1.0, t * 20)
    _fortune_write_wav(folder / "win.wav", _fortune_normalize(win, 0.9), rate)
    return {name: folder / f"{name}.wav" for name in ("tick_low", "tick_mid", "tick_high", "whirr", "ambient", "win")}


def _synth_paws(folder: Path) -> dict:
    """Набор «Белые лапки»: уютный lofi-фон на музыкальной шкатулке с тёплым пэдом, мягкие глухие «шлепки
    лапки» вместо щелчков, тихое мурлыканье при вращении и тёплый победный перезвон с лёгким «мяу».
    Петля фона замыкается бесшовно (каждый такт начинается и заканчивается в тишине)."""
    rnd = random.Random(33)
    rate = 22050
    # мягкие «шлепки лапки»: низкий круглый тон + приглушённый шум, плавная атака (без резкого клика)
    for name, freq in (("tick_low", 190.0), ("tick_mid", 260.0), ("tick_high", 360.0)):
        n = int(rate * 0.07)
        lp, s_ = 0.0, []
        for i in range(n):
            t = i / rate
            lp += 0.18 * ((rnd.random() - 0.5) - lp)
            att = min(1.0, t / 0.004)
            s_.append(att * (math.sin(math.tau * freq * t) * math.exp(-t * 62)
                             + 0.35 * math.sin(math.tau * freq * 2.0 * t) * math.exp(-t * 110)
                             + 1.6 * lp * math.exp(-t * 90)))
        _fortune_write_wav(folder / f"{name}.wav", _fortune_normalize(s_, 0.55), rate)
    # вращение: тихое мурлыканье — сглаженный шум с амплитудной модуляцией 25 Гц (петля с плавным стыком)
    n = int(rate * 1.2)
    lp, purr = 0.0, []
    for i in range(n):
        t = i / rate
        lp += 0.05 * ((rnd.random() - 0.5) - lp)
        purr.append(lp * (0.55 + 0.45 * math.sin(math.tau * 25.0 * t)))
    fade = int(rate * 0.08)
    for i in range(fade):
        k = i / fade
        purr[i] = purr[i] * k + purr[n - fade + i] * (1 - k)
    purr = purr[:n - fade]
    _fortune_write_wav(folder / "whirr.wav", _fortune_normalize(purr, 0.45), rate)
    # фон: 8 секунд, До – ля минор – Фа – Соль; музыкальная шкатулка, тёплый пэд, мягкий бас, тихий «винил»
    rate_a = 11025
    total = int(rate_a * 8.0)
    amb = [0.0] * total
    chords = ((130.81, (261.63, 329.63, 392.0)), (110.0, (220.0, 261.63, 329.63)),
              (87.31, (174.61, 220.0, 261.63)), (98.0, (196.0, 246.94, 293.66)))
    for bar, (root, chord) in enumerate(chords):
        base = int(bar * 2.0 * rate_a)
        for i in range(int(2.0 * rate_a)):
            t = i / rate_a
            env = math.sin(math.pi * t / 2.0) ** 2         # в начале и в конце такта — тишина: стык без щелчка
            v = 0.10 * math.sin(math.tau * root * t)
            for f in chord:
                v += 0.07 * (math.sin(math.tau * f * t) + 0.3 * math.sin(math.tau * 2 * f * t))
            amb[base + i] += env * v
    melody = (659.25, 783.99, 1046.5, 880.0, 783.99, 659.25, 587.33, 659.25,
              783.99, 880.0, 1046.5, 880.0, 783.99, 659.25, 587.33, 523.25)      # 16 нот по 0.5 с
    for k, f in enumerate(melody):
        start = int(k * 0.5 * rate_a)
        for i in range(int(rate_a * 1.5)):
            t = i / rate_a
            v = (math.sin(math.tau * f * t) * math.exp(-t * 3.2)
                 + 0.35 * math.sin(math.tau * 2 * f * t) * math.exp(-t * 6.0)
                 + 0.12 * math.sin(math.tau * 3 * f * t) * math.exp(-t * 9.0))
            amb[(start + i) % total] += 0.17 * min(1.0, t / 0.003) * v
    for _ in range(36):                                    # тихое потрескивание пластинки
        pos = rnd.randrange(total - 40)
        amp = rnd.uniform(0.01, 0.035)
        for j in range(30):
            amb[pos + j] += amp * (rnd.random() - 0.5) * math.exp(-j / 6.0)
    _fortune_write_wav(folder / "ambient.wav", _fortune_normalize(amb, 0.5), rate_a)
    # победа: тёплое арпеджио шкатулки, мягкий аккорд, мурлыканье и короткое «мяу»
    n = int(rate * 3.2)
    win = [0.0] * n
    for k, f in enumerate((523.25, 659.25, 783.99, 1046.5)):
        t0 = int(rate * 0.13 * k)
        for i in range(min(n - t0, int(rate * 2.2))):
            t = i / rate
            e = math.exp(-t * 2.6) * min(1.0, t / 0.004)
            win[t0 + i] += 0.5 * e * (math.sin(math.tau * f * t) + 0.3 * math.sin(math.tau * 2 * f * t)
                                      + 0.1 * math.sin(math.tau * 3 * f * t))
    t0 = int(rate * 0.5)
    for f in (261.63, 329.63, 392.0):
        for i in range(n - t0):
            t = i / rate
            win[t0 + i] += 0.12 * math.sin(math.tau * f * t) * math.exp(-t * 1.2) * min(1.0, t * 8)
    p0 = int(rate * 0.7)
    lp = 0.0
    for i in range(p0, n):                                 # мурлыканье
        t = (i - p0) / rate
        lp += 0.04 * ((rnd.random() - 0.5) - lp)
        win[i] += 2.2 * lp * min(1.0, t / 0.3) * math.exp(-t * 1.1) * (0.5 + 0.5 * math.sin(math.tau * 24.0 * t))
    m0, dur, ph = int(rate * 0.75), 0.45, 0.0
    for i in range(int(rate * dur)):                       # «мяу»: тон поднимается и опускается
        t = i / rate
        x = t / dur
        f = 480.0 + 320.0 * math.sin(math.pi * x) - 60.0 * x
        ph += f * (1.0 + 0.012 * math.sin(math.tau * 6.0 * t)) / rate
        tone = math.sin(math.tau * ph) + 0.5 * math.sin(math.tau * 2 * ph) + 0.3 * math.sin(math.tau * 3 * ph)
        win[m0 + i] += 0.16 * (math.sin(math.pi * x) ** 0.7) * tone
    delay = int(rate * 0.2)
    for i in range(n - 1, delay - 1, -1):
        win[i] += 0.25 * win[i - delay]
    _fortune_write_wav(folder / "win.wav", _fortune_normalize(win, 0.8), rate)
    return {name: folder / f"{name}.wav" for name in ("tick_low", "tick_mid", "tick_high", "whirr", "ambient", "win")}


def _fortune_sound_files(theme: str = "classic") -> dict:
    """Создаёт (один раз для каждой темы) звуки колеса и возвращает {имя: путь}.
    Бросает исключение при сбое записи."""
    theme = theme if theme in ("nte", "sakura", "paws") else "classic"
    if theme in _FORTUNE_SOUNDS:
        return _FORTUNE_SOUNDS[theme]
    if not _FORTUNE_DIR:
        _FORTUNE_DIR.append(Path(tempfile.mkdtemp(prefix="nte_fortune_")))
    folder = _FORTUNE_DIR[0] / theme
    folder.mkdir(parents=True, exist_ok=True)
    synth = {"nte": _synth_nte, "sakura": _synth_sakura, "paws": _synth_paws}.get(theme, _synth_classic)
    _FORTUNE_SOUNDS[theme] = synth(folder)
    return _FORTUNE_SOUNDS[theme]


# (x, y, размер в долях меньшей стороны, угол) — разбросанные отпечатки лапок для фона
FORTUNE_PAW_SPOTS = ((0.07, 0.10, 0.045, -20), (0.93, 0.07, 0.04, 25), (0.16, 0.40, 0.035, 15),
                     (0.88, 0.36, 0.045, -15), (0.05, 0.66, 0.04, 20), (0.94, 0.62, 0.035, -25),
                     (0.13, 0.92, 0.045, -10), (0.50, 0.97, 0.035, 12), (0.87, 0.93, 0.045, 18),
                     (0.30, 0.04, 0.03, 10), (0.70, 0.03, 0.03, -12), (0.30, 0.66, 0.03, -18))


# ---------- окно ----------
# ---------- адаптивное оформление окна колеса ----------
def _fortune_px(value: float, k: float) -> int:
    return max(1, int(round(value * k)))


def _fortune_stylesheet(k: float, theme: str = "classic") -> str:
    """Таблица стилей окна колеса для выбранной темы. Все размеры шрифтов, отступов и скруглений
    умножаются на коэффициент масштаба k (зависит от размера окна), поэтому текст и кнопки одинаково
    хорошо смотрятся и на маленьком окне, и на развёрнутом, и на 4K-мониторе."""
    f = lambda v: _fortune_px(v, k)
    T = FORTUNE_THEMES.get(theme, FORTUNE_THEMES["classic"])
    spin, spin_fg, spin_border, spin_hover = T["spin"]
    dis_fg, dis_bg, dis_border = T["btn_dis"]
    sd_bg, sd_fg, sd_border = T["spin_dis"]
    return f"""
        QDialog {{ background: qlineargradient(x1:0,y1:0,x2:1,y2:1, stop:0 {T['bg'][0]}, stop:1 {T['bg'][1]}); }}
        QScrollArea {{ background: transparent; border: none; }}
        QScrollArea > QWidget > QWidget {{ background: transparent; }}
        QFrame#fortuneCard {{ background: qlineargradient(x1:0,y1:0,x2:1,y2:1, stop:0 {T['card'][0]}, stop:1 {T['card'][1]});
            border: 1px solid {T['card_border']}; border-radius: {f(16)}px; }}
        QLabel#fortuneTitle {{ color: {T['title']}; font-family: Georgia, 'Palatino Linotype', serif;
            font-size: {f(22)}px; font-weight: bold; letter-spacing: {f(3)}px; background: transparent; }}
        QLabel#fortuneIntro {{ color: {T['intro']}; font-family: Georgia, 'Palatino Linotype', serif;
            font-size: {f(15)}px; font-style: italic; background: transparent; }}
        QFrame#fortunePanel {{ background: {T['panel_bg']}; border: 1px solid {T['panel_border']};
            border-radius: {f(12)}px; }}
        QLabel#fortuneHead {{ color: {T['head']}; font-size: {f(15)}px; font-weight: bold; background: transparent; }}
        QLabel#fortuneHint {{ color: {T['hint']}; font-size: {f(12)}px; background: transparent; }}
        QListWidget {{ background: {T['list_bg']}; color: {T['list_fg']}; border: 1px solid {T['field_border']};
            border-radius: {f(8)}px; font-size: {f(14)}px; }}
        QListWidget::item {{ padding: {f(5)}px {f(6)}px; }}
        QListWidget::item:selected {{ background: {T['select']}; color: {T['select_fg']}; }}
        QLineEdit {{ background: {T['list_bg']}; color: {T['edit_fg']}; border: 1px solid {T['field_border']};
            border-radius: {f(8)}px; padding: {f(6)}px; font-size: {f(14)}px; }}
        QPushButton {{ background: {T['btn_bg']}; color: {T['btn_fg']}; border: 1px solid {T['btn_border']};
            border-radius: {f(8)}px; padding: {f(6)}px {f(10)}px; font-size: {f(12)}px; text-align: center; }}
        QPushButton:hover {{ background: {T['btn_hover']}; }}
        QPushButton:disabled {{ color: {dis_fg}; background: {dis_bg}; border-color: {dis_border}; }}
        QPushButton#fortuneSpin {{ background: {spin}; color: {spin_fg}; border: {max(2, f(2))}px solid {spin_border};
            border-radius: {f(14)}px; font-family: Georgia, serif; font-size: {f(22)}px; font-weight: bold;
            padding: {f(10)}px {f(40)}px; }}
        QPushButton#fortuneSpin:hover {{ background: {spin_hover}; }}
        QPushButton#fortuneSpin:disabled {{ background: {sd_bg}; color: {sd_fg}; border-color: {sd_border}; }}
        QCheckBox {{ color: {T['check']}; font-size: {f(13)}px; spacing: {f(6)}px; }}
        QLabel#fortuneStyleLabel {{ color: {T['check']}; font-size: {f(13)}px; background: transparent; }}
        QComboBox {{ background: {T['btn_bg']}; color: {T['btn_fg']}; border: 1px solid {T['btn_border']};
            border-radius: {f(8)}px; padding: {f(4)}px {f(10)}px; font-size: {f(13)}px; min-width: {f(130)}px; }}
        QComboBox:hover {{ background: {T['btn_hover']}; }}
        QComboBox:disabled {{ color: {dis_fg}; background: {dis_bg}; border-color: {dis_border}; }}
        QComboBox::drop-down {{ border: none; width: {f(22)}px; }}
        QComboBox QAbstractItemView {{ background: {T['list_bg']}; color: {T['list_fg']};
            border: 1px solid {T['field_border']}; selection-background-color: {T['select']};
            selection-color: {T['select_fg']}; outline: none; font-size: {f(13)}px; }}
        QSplitter::handle {{ background: transparent; }}
    """


def _fortune_card_stylesheet(k: float, theme: str = "classic") -> str:
    f = lambda v: _fortune_px(v, k)
    W = FORTUNE_THEMES.get(theme, FORTUNE_THEMES["classic"])["win"]
    return f"""
        QFrame#winCard {{ background: qlineargradient(x1:0,y1:0,x2:1,y2:1, stop:0 {W['bg'][0]}, stop:1 {W['bg'][1]});
            border: {max(2, f(2))}px solid {W['border']}; border-radius: {f(18)}px; }}
        QLabel#winTop {{ color: {W['top']}; font-family: Georgia, serif; font-size: {f(13)}px; letter-spacing: {f(3)}px;
            background: transparent; }}
        QLabel#winText {{ color: {W['text']}; font-family: Georgia, serif; font-size: {f(26)}px; font-weight: bold;
            background: transparent; }}
        QLabel#winSub {{ color: {W['sub']}; font-family: Georgia, serif; font-size: {f(16)}px; font-style: italic;
            background: transparent; }}
        QPushButton {{ background: {W['btn_bg']}; color: {W['btn_fg']}; border: 1px solid {W['btn_border']};
            border-radius: {f(10)}px; padding: {f(6)}px {f(22)}px; font-size: {f(14)}px; font-weight: bold; }}
        QPushButton:hover {{ background: {W['btn_hover']}; }}
    """


# ----------------------------------------------------------------------------
# НОВОЕ: внутренний рендерер карточки «Поделиться» (ShareCardRenderer)
# ----------------------------------------------------------------------------
# Карточка рисуется целиком в памяти (QImage + QPainter) на холсте фиксированного размера
# по проектной сетке 3840x2160. Размеры окна, экрана, масштаб Windows и состояние окна
# (свёрнуто / обычное / во весь экран) на результат НЕ влияют: рендерер получает только
# данные (словарь), собранные функцией collect_share_data(), и ничего не снимает с экрана.
SHARE_CANVAS_4K = (3840, 2160)


SHARE_CANVAS_2K = (2560, 1440)


SHARE_CANVAS_SIZE = SHARE_CANVAS_4K          # 3840x2160 или SHARE_CANVAS_2K


SHARE_RECENT_LIMIT = 10                      # сколько последних S показывать внизу карточки


SHARE_DIR_NAME = "screenshots"               # папка для PNG-копий рядом с базой данных


SHARE_FONT_FAMILIES = ["Segoe UI", "Segoe UI Emoji", "Noto Sans", "Arial", "DejaVu Sans"]


SHARE_TOAST_TEXT = "Скриншот высокого качества скопирован в буфер обмена!"


SHARE_WATERMARK = "NTE Wish Tracker — Neverness to Everness"


SHARE_POOL_SHORT = {EVENT_BANNER: "Ивентовый", STANDARD_BANNER: "Стандартный", ARC_BANNER: "Дуга"}


SHARE_POOL_ACCENTS = {EVENT_BANNER: "#b66cff", STANDARD_BANNER: "#8ab4ff", ARC_BANNER: "#7be0a8"}


# ----------------------------------------------------------------------------
# НОВОЕ: сбор данных для ShareCardRenderer (виджеты не снимаются — берутся только данные)
# ----------------------------------------------------------------------------
def _share_date(text) -> str:
    m = re.match(r"\s*(\d{4})-(\d{2})-(\d{2})", str(text or ""))
    return f"{m.group(3)}.{m.group(2)}.{m.group(1)}" if m else str(text or "")


def _map_translate_en_ru(text: str) -> str:
    import urllib.parse
    url = ("https://translate.googleapis.com/translate_a/single?client=gtx&sl=en&tl=ru&dt=t&q="
           + urllib.parse.quote(text))
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=8) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    return "".join(part[0] for part in data[0] if part and part[0]).strip()


# ----------------------------------------------------------------------------
# НОВОЕ: вкладка «Созвездие» — интерактивная сеть узлов вокруг портрета персонажа
# (QGraphicsView / QGraphicsScene). Колесо мыши — масштаб, перетаскивание фона — панорама,
# наведение — подсказка, клик — подробности (узлы без привязки к базе можно отмечать вручную).
# Названия типов узлов, подсказки и подписи редактируются в CONSTELLATION_TYPES ниже.
# ----------------------------------------------------------------------------
CONSTELLATION_CENTER = (625.0, 608.0)           # центр колец и портрета в координатах сцены


CONSTELLATION_BG_BLUR_KEY = "constellation_bg_blur"      # настройка профиля: размытие фона 0–100


CONSTELLATION_NO_GLOW_KEY = "constellation_no_glow"   # настройка профиля: «Отключить свечение»


CONSTELLATION_RINGS = (504.0, 408.0, 380.0)     # радиусы трёх концентрических колец (как на референсе)


CONSTELLATION_ZOOM_MIN, CONSTELLATION_ZOOM_MAX = 0.6, 8.0   # относительно «вписанного» масштаба


CONSTELLATION_DEFAULT_CHAR = "Аканэ Рин"


# тип узла: (название, тип предмета из базы или None, цвет, радиус, символ-заглушка, описание)
CONSTELLATION_TYPES = {
    "dice":   ("Шулерский кубик", "trick_cube", "#ff3b4e", 44.0, "⚃",
               "Кубик для бросков по доске. Берётся из вкладки «История» (тип «Шулерский кубик»)."),
    "record": ("Пластинка", None, "#ff5fa2", 44.0, "◉",
               "Памятная награда персонажа. Отметьте узел кликом, когда получите её."),
    "disc":   ("Диск", None, "#33c8ff", 44.0, "◎",
               "Награда за прохождение ветки доски. Отметьте узел кликом, когда получите её."),
    "orb":    ("Сфера", None, "#4d8dff", 44.0, "●",
               "Редкий ресурс развития. Отметьте узел кликом, когда получите его."),
    "egg":    ("Золотое яйцо", None, "#ffc83d", 24.0, "⬮",
               "Особый коллекционный предмет. Отметьте узел кликом, когда получите его."),
    "core":   ("Огненная капсула", None, "#ff8a1f", 40.0, "✹",
               "Ресурс усиления персонажа. Отметьте узел кликом, когда получите его."),
    "key":    ("Ключевой предмет", None, "#59d6ff", 40.0, "◆",
               "Центральная награда доски. Отметьте узел кликом, когда получите её."),
    "tube":   ("Пробирка", None, "#a86bff", 26.0, "▮",
               "Малый ресурс доски. Отметьте узел кликом, когда получите его."),
}


# ----------------------------------------------------------------------------
# Геометрия «магического круга» (точно по референсу). Все точки считаются от центра:
#   • внешняя декаграмма: 10 слотов через 36° (верхний слот пуст), радиус R_OUT;
#     нечётные слоты (кубики, сферы) — вершины большой пентаграммы (вершина внизу);
#   • «пробирки» стоят там, где линии большой пентаграммы пересекают кольцо R_RING
#     у каждой вершины (по две на вершину);
#   • «ключевой предмет» — внутренняя вершина большой пентаграммы (над портретом);
#   • малая пентаграмма (вершина вверху) R_SMALL: пробирка сверху, два яйца, две нижние пробирки;
#   • пентаграмма из пяти «огненных капсул» R_FIRE (вершина внизу);
#   • радиальные лучи: чётные внешние узлы (пластинки, диски) — к вершинам малой пентаграммы.
# ----------------------------------------------------------------------------
CONSTELLATION_R_OUT, CONSTELLATION_R_RING = 502.0, 380.0


CONSTELLATION_R_SMALL, CONSTELLATION_R_FIRE = 348.0, 255.0


CONSTELLATION_OUTER_SLOTS = {1: "dice", 2: "record", 3: "orb", 4: "disc", 5: "dice",
                             6: "disc", 7: "orb", 8: "record", 9: "dice"}   # слот 0 (верх) пуст


def _cpt(angle_deg: float, radius: float):
    a = math.radians(angle_deg)
    return (CONSTELLATION_CENTER[0] + radius * math.cos(a), CONSTELLATION_CENTER[1] + radius * math.sin(a))


def _constellation_geometry():
    """Возвращает (узлы [(тип, x, y, метка)], линии [(метка A, метка B)])."""
    pts = {}
    for k, t in CONSTELLATION_OUTER_SLOTS.items():
        pts[f"o{k}"] = (t,) + _cpt(-90 + 36 * k, CONSTELLATION_R_OUT)
    for k in range(5):                                       # огненные капсулы: 90°, 162°, 234°, 306°, 18°
        pts[f"f{k}"] = ("core",) + _cpt(90 + 72 * k, CONSTELLATION_R_FIRE)
    for tag, ang, t in (("sT", -90, "tube"), ("sR", -18, "egg"), ("sBR", 54, "tube"),
                        ("sBL", 126, "tube"), ("sL", 198, "egg")):
        pts[tag] = (t,) + _cpt(ang, CONSTELLATION_R_SMALL)
    inner = CONSTELLATION_R_OUT * math.cos(math.radians(72)) / math.cos(math.radians(36))
    pts["key"] = ("key",) + _cpt(-90, inner)
    # пробирки на пересечении рёбер большой пентаграммы с кольцом (ближе к вершине ребра)
    cx, cy = CONSTELLATION_CENTER
    for k in (1, 3, 5, 7, 9):
        for step in (4, -4):
            v, w = pts[f"o{k}"], pts[f"o{(k + step) % 10}"]
            dx, dy, fx, fy = w[1] - v[1], w[2] - v[2], v[1] - cx, v[2] - cy
            qa, qb = dx * dx + dy * dy, 2 * (fx * dx + fy * dy)
            qc = fx * fx + fy * fy - CONSTELLATION_R_RING ** 2
            t = (-qb - math.sqrt(qb * qb - 4 * qa * qc)) / (2 * qa)
            pts[f"t{k}_{step}"] = ("tube", v[1] + t * dx, v[2] + t * dy)
    order = ("dice", "record", "orb", "disc", "core", "egg", "key", "tube")
    nodes = sorted(((t, x, y, tag) for tag, (t, x, y) in pts.items()),
                   key=lambda n: (order.index(n[0]), n[3]))
    edges = []
    for k in (1, 3, 5, 7, 9):                                # большая пентаграмма (через одну вершину)
        edges.append((f"o{k}", f"o{(k + 4) % 10}"))
    edges += [("sT", "sBR"), ("sBR", "sL"), ("sL", "sR"), ("sR", "sBL"), ("sBL", "sT")]   # малая
    edges += [(f"f{k}", f"f{(k + 2) % 5}") for k in range(5)]                             # огненная
    edges += [("o2", "sR"), ("o8", "sL"), ("o4", "sBR"), ("o6", "sBL")]                   # лучи
    return tuple(nodes), tuple(edges)


CONSTELLATION_NODES, CONSTELLATION_EDGES = _constellation_geometry()


# ----------------------------------------------------------------------------
# Точка входа
# ----------------------------------------------------------------------------
WEBENGINE_GPU_RASTER = True      # НОВОЕ: False — вернуть программную растеризацию встроенной карты

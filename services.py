"""Бизнес-логика мобильного приложения БЕЗ UI.

Повторяет то, что в десктопе делает MainWindow: refresh(), разбор пачки скриншотов,
порядок и «хронология» пачки, запись в базу одной транзакцией, карточки баннеров.
Всё считают функции из nte_core (сгенерированы из main.py) — формулы гарантов,
правила бонусов, разбор русских дат и словари имён не переписываются.
"""
import json
import time
import urllib.request
from datetime import datetime
from pathlib import Path

import nte_core as C

MASS_MAX_FILES = 300


class Tracker:
    """Фасад над базой: профили, пересчёт статистики, история, импорт."""

    def __init__(self, db_path):
        self.db = C.Database(db_path)
        self.rows, self.rewards = [], []
        self.stats, self.pity_at, self.history, self.known = {}, {}, [], {}
        self.banner_info = None            # результат parse_banner_payload или None
        if self.db.profile_count():
            self.refresh()

    # ---------- профили ----------
    @property
    def has_profile(self) -> bool:
        return self.db.profile_count() > 0

    def create_profile(self, name: str) -> int:
        pid = self.db.create_profile(name)
        self.db.set_active_profile(pid)
        self.refresh()
        return pid

    def switch_profile(self, pid: int) -> None:
        self.db.set_active_profile(pid)
        self.refresh()

    # ---------- пересчёт (аналог MainWindow.refresh) ----------
    def refresh(self) -> None:
        self.rows = self.db.fetch_all()
        self.rewards = self.db.fetch_rewards()
        events = C.build_timeline(self.rows, self.rewards)
        self.stats, self.pity_at = C.compute_stats(events)
        self.history = C.history_entries(events, self.pity_at)
        self.known = {}
        for r in self.rows:
            if r.get("cashback") or r["name"] in ("Персонаж", "Дуга"):
                continue
            self.known[r["name"].lower()] = (r["name"], r["rarity"], r["banner"])
        for key, value in C.ROSTER_KNOWN.items():
            self.known.setdefault(key, value)
        for key, value in C.ARC_KNOWN.items():
            self.known.setdefault(key, value)
        C.refresh_master_names(self.rewards)

    # ---------- сводка «Стафф» ----------
    def pool_summary(self, banner: str) -> dict:
        s = self.stats[banner]
        avg = (sum(s["pities"]) / len(s["pities"])) if s["pities"] else 0
        return {"title": C.POOL_TITLES[banner], "total": s["total"], "s": s["r5"], "a": s["r4"],
                "b": s["r3"], "bonus": s["bonus"], "avg_pity": round(avg, 1),
                "counter": s["counter"], "counter_std": s["counter_std"],
                "counter_ev": s["counter_ev"], "last5": s["last5"]}

    def banner_cards(self, now: datetime = None) -> list:
        """Карточки текущего баннера / рерана для «Стафф»: счётчики только в окне start..end."""
        now = now or datetime.now()
        info = self.banner_info or {}
        cards = []
        for title, entry in (("Текущий ивентовый персонаж", self._entry(info, "name")),
                             ("Реран персонажа", info.get("rerun"))):
            if not entry or not entry.get("name"):
                cards.append({"title": title, "name": "Не определён", "countdown": C.BANNER_NO_TIME_TEXT,
                              "kind": "none", "pulls": 0, "s": 0, "pity": 0})
                continue
            start, end = C.banner_pull_window(entry)
            st = C.banner_period_stats(self.history, C.EVENT_BANNER, start, end)
            text, hint, kind = C.banner_countdown(entry, now)
            cards.append({"title": title, "name": entry["name"], "countdown": text, "hint": hint,
                          "kind": kind, "pulls": st["pulls"], "s": st["s"], "pity": st["pity"],
                          "entry": entry})
        for title, entry in (("Дуга текущего персонажа", info.get("arc")),
                             ("Дуга реран персонажа", info.get("arc_rerun"))):
            if not entry or not entry.get("name"):
                cards.append({"title": title, "name": "Не объявлена", "countdown": C.BANNER_NO_TIME_TEXT,
                              "kind": "none", "pulls": 0, "s": 0, "std": 0, "ev": 0})
                continue
            start, end = C.banner_pull_window(entry)
            st = C.arc_period_stats(self.history, start, end)
            text, hint, kind = C.banner_countdown(entry, now)
            cards.append({"title": title, "name": entry["name"], "countdown": text, "hint": hint,
                          "kind": kind, "pulls": st["pulls"], "s": st["s"],
                          "std": st["std"], "ev": st["ev"], "entry": entry})
        return cards

    @staticmethod
    def _entry(info: dict, name_key: str):
        if not info or not info.get(name_key):
            return None
        return {"name": info[name_key], "start": info.get("start"), "end": info.get("end")}

    # ---------- баннеры из banners.json (без Qt; логика BannerFetchThread) ----------
    def fetch_banners(self) -> bool:
        errors = []
        for url in C.BANNER_URLS:
            try:
                headers = {"User-Agent": C.BANNER_USER_AGENT, "Accept": "application/json",
                           "Cache-Control": "no-cache"}
                full = f"{url}{'&' if '?' in url else '?'}t={int(time.time())}"
                with urllib.request.urlopen(urllib.request.Request(full, headers=headers),
                                            timeout=C.BANNER_TIMEOUT * 3) as resp:
                    raw = resp.read(C.BANNER_MAX_BYTES + 1)
                if len(raw) > C.BANNER_MAX_BYTES:
                    raise ValueError("ответ слишком большой")
                self.banner_info = C.parse_banner_payload(json.loads(raw.decode("utf-8-sig")))
                return True
            except Exception as e:  # noqa: BLE001 — сеть ломается десятком способов
                errors.append(f"{type(e).__name__}: {e}")
        self.last_banner_error = "; ".join(errors)
        return False

    # ---------- ручное добавление ----------
    def add_manual(self, loot: str, banner: str, rank: int, name: str, stamp: str,
                   qty=None, is_bonus: bool = False, arc_kind: str = "standard") -> None:
        """Ручное добавление теми же правилами, что и OCR: любой тип из LOOT_TYPES."""
        when = C.QDateTime.fromString(stamp, C.QT_DATE_FMT)
        if not when.isValid():
            raise ValueError("Дата: ГГГГ-ММ-ДД ЧЧ:ММ:СС")
        pull = {"loot": loot, "name": name.strip(), "rarity": rank, "qty": qty, "timestamp": when,
                "has_time": True, "is_bonus": is_bonus, "rarity_src": "цвет"}
        kind, rec = record_from_pull(pull, banner, arc_kind)
        (self.db.add_many if kind == "wish" else self.db.add_rewards)([rec])
        self.refresh()

    def delete_history_item(self, entry: dict) -> None:
        if entry["src"] == "wish":
            self.db.delete_ids([entry["id"]])
        else:
            self.db.delete_reward_ids([entry["id"]])
        self.refresh()


class ScanSession:
    """Пачка скриншотов (одиночный режим = пачка из одного файла).

    scan() — тяжёлый шаг, вызывать из фонового потока. build() — лёгкий: разбор текстов,
    порядок снимков, хронология; повторяется после правок строк."""

    def __init__(self, tracker: Tracker, paths: list, banner: str, arc_kind: str = "standard"):
        self.t = tracker
        self.paths = sorted(paths, key=C.mass_sort_key)[:MASS_MAX_FILES]   # старые снимки первыми
        self.banner = banner
        self.arc_kind = arc_kind
        self.data = {p: C.new_file_data() for p in self.paths}
        self.found = []                    # итоговые записи (старые первыми внутри снимка — снизу вверх)
        self.warnings = []
        self.errors = {}

    @property
    def default_loot(self) -> str:
        return "arc" if self.banner == C.ARC_BANNER else "character"

    def scan(self, progress=None, cancelled=lambda: False) -> None:
        total = len(self.paths)
        for i, path in enumerate(self.paths):
            if cancelled():
                break
            if progress:
                progress(i, total, Path(path).name)
            d = self.data[path]
            try:
                res = C.run_ocr_pipeline(path)
            except C.OcrError as e:
                self.errors[path], d["status"] = str(e), "Ошибка"
                continue
            except Exception as e:  # noqa: BLE001 — один плохой файл не роняет пачку
                self.errors[path], d["status"] = f"Ошибка распознавания:\n{e}", "Ошибка"
                continue
            d.update(text=res["text"], ranks=res["ranks"], glob=res["glob"], confs=res.get("confs"),
                     page=res.get("page"), page_alts=C.PAGE_ALTS.get(path) or [],
                     status="Готово", done=True)
            if (i + 1) % C.MASS_GC_EVERY == 0:
                import gc
                gc.collect()

    def build(self) -> None:
        """Тот же порядок шагов, что в MainWindow._mass_job_gen."""
        per_file = []
        for order, path in enumerate(self.paths):
            d = self.data[path]
            if not d["done"]:
                continue
            pulls, _skipped = C.parse_file_with_edits(d, self.t.known, self.default_loot)
            d["count"] = len(pulls)
            per_file.append({"order": order, "path": path, "pulls": pulls, "page": d.get("page"),
                             "page_alts": d.get("page_alts") or [], "edits": d.get("edits")})
        C.mark_locked_times(per_file)
        C.repair_stamp_misreads([e["pulls"] for e in per_file])
        per_file, warns, page_mode = C.order_shots(per_file, len(self.paths))
        if page_mode:
            warns += C.enforce_chronology(per_file)[1]
        C.refresh_flagged(per_file, self.data)
        self.warnings = warns
        self.found = []
        for pos, e in enumerate(per_file, 1):
            self.data[e["path"]]["chrono"] = pos
            name = Path(e["path"]).name
            self.found += [dict(p, file=name, path=e["path"]) for p in C.bottom_to_top_order(e["pulls"])]

    def review_count(self) -> int:
        return C.review_total(self.data)

    def set_edit(self, path: str, line: int, edit: dict) -> None:
        """edit: {'loot','name','qty','rank','ts','include'} — как в RowEditorDialog."""
        self.data[path]["edits"][line] = edit

    # ---------- запись в базу ----------
    def to_records(self, picked: list):
        wishes, rewards = [], []
        for seq, p in enumerate(C.bottom_to_top_order(picked)):
            kind, rec = record_from_pull(p, self.banner, self.arc_kind)
            rec["seq"] = seq
            (wishes if kind == "wish" else rewards).append(rec)
        return wishes, rewards

    def already_in_db(self, wishes: list, rewards: list) -> int:
        from collections import Counter
        have_w = Counter(C._wish_key(r) for r in self.t.db.fetch_all())
        have_r = Counter(C._reward_key(r) for r in self.t.db.fetch_rewards())
        total = 0
        for keys, have in ((Counter(C._wish_key(r) for r in wishes), have_w),
                           (Counter(C._reward_key(r) for r in rewards), have_r)):
            total += sum(min(n, have.get(k, 0)) for k, n in keys.items())
        return total

    def commit(self, picked: list):
        wishes, rewards = self.to_records(picked)
        added = self.t.db.import_batch(wishes, rewards)
        self.t.refresh()
        return added


def record_from_pull(p: dict, banner: str, arc_kind: str = "standard"):
    """MainWindow._record_from_ocr без виджетов (тип S дуги берётся из arc_kind)."""
    key = p["loot"]
    info = C.LOOT_TYPES[key]
    stamp = (p["timestamp"].toString(C.QT_DATE_FMT) if p["has_time"]
             else C.QDateTime.currentDateTime().toString(C.QT_DATE_FMT))
    name = C.finalize_loot_name(key, p["name"])
    mode = info["mode"]
    if mode == "reward":
        if info.get("qty"):
            detail = C.pick_item_qty(info, p.get("qty"))
        elif info.get("bind"):
            detail = ""
        else:
            detail = info.get("detail", "")
        return "reward", {
            "kind": info["kind"], "name": name or C.default_reward_name(info["kind"], detail),
            "detail": detail, "obtained_at": stamp, "banner": banner,
            "no_pity": int(bool(info.get("no_pity")) or info["kind"] in C.NO_PITY_KINDS
                           or bool(p.get("is_bonus")) or bool(p.get("no_pity"))),
            "rarity": (C.rank_letter(p["rarity"]) if p.get("rarity_src") == "цвет" else "")}
    is_bonus = bool(p.get("is_bonus")) and mode == "wish"
    rarity = (C.loot_rarity(info) if mode == "cashback" else 4 if is_bonus else p["rarity"])
    arc_kind = ""
    if mode == "wish" and banner == C.ARC_BANNER and rarity == 5 and not is_bonus:
        arc_kind = C.arc_kind_by_name(name, arc_kind or "")
    return "wish", {"banner": banner, "rarity": rarity, "name": name or info["default"],
                    "pulled_at": stamp, "is_bonus": int(is_bonus), "arc_kind": arc_kind,
                    "cashback": info.get("cashback", "") if mode == "cashback" else ""}

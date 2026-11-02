"""Бизнес-логика мобильного приложения БЕЗ UI.

Повторяет то, что в десктопе делает MainWindow: refresh(), разбор пачки скриншотов,
порядок и «хронология» пачки, запись в базу одной транзакцией, карточки баннеров.
Всё считают функции из nte_core (сгенерированы из main.py) — формулы гарантов,
правила бонусов, разбор русских дат и словари имён не переписываются.
"""
import colorsys
import json
import time
import urllib.request
from datetime import datetime
from pathlib import Path

import imgutil
import nte_core as C

MASS_MAX_FILES = 300
RANK_HEX = {5: "ffd740", 4: "d6a0e0", 3: "90caf9"}        # S золотой, A фиолетовый, B синий


def pity_hex(pulls: int, hard: int = C.PITY_CHAR_HARD) -> str:
    """Цвет числа круток: 1 — зелёный, середина — жёлтый/оранжевый, hard — красный
    (замена pity_color из десктопа, которая зависела от QColor)."""
    t = 0.0 if hard <= 1 else (pulls - 1) / (hard - 1)
    t = min(max(t, 0.0), 1.0)
    r, g, b = colorsys.hsv_to_rgb((1.0 - t) / 3.0, 0.80, 0.95)
    return "%02x%02x%02x" % (int(r * 255), int(g * 255), int(b * 255))


class Tracker:
    """Фасад над базой: профили, пересчёт статистики, история, импорт."""

    def __init__(self, db_path):
        self.db = C.Database(db_path)
        self.rows, self.rewards = [], []
        self.stats, self.pity_at, self.history, self.known = {}, {}, [], {}
        self.banner_info = None            # результат parse_banner_payload или None
        self.last_banner_error = ""
        self._icons = {}
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
        self._icons = {}
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
                "qty": dict(s.get("qty", {})), "counter": s["counter"], "counter_std": s["counter_std"],
                "counter_ev": s["counter_ev"], "last5": s["last5"]}

    def banner_cards(self, banner: str, now: datetime = None) -> list:
        """Карточки панели баннеров пула (как BannerDashboard на десктопе).
        Для не-баннерных пулов (стандартный) возвращает пустой список."""
        now = now or datetime.now()
        info = self.banner_info
        is_arc = banner == C.ARC_BANNER
        if banner not in (C.EVENT_BANNER, C.ARC_BANNER):
            return []
        s = self.stats[banner]
        if is_arc:
            cur = dict(info["arc"]) if info and info.get("arc") else None
            rer = dict(info["arc_rerun"]) if info and info.get("arc_rerun") else None
            specs = (("Дуга текущего персонажа", "Не определена", cur, True, ("arc_current", "arc", "current_arc")),
                     ("Дуга реран персонажа", "Не объявлена", rer, False, ("arc_rerun", "rerun_arc")))
        else:
            cur = ({"name": info["name"], "start": info.get("start"), "end": info.get("end"),
                    "activated": info.get("activated")} if info and info.get("name") else None)
            rer = info.get("rerun") if info else None
            specs = (("Текущий ивентовый персонаж", "Не определён", cur, True, ("current", "event")),
                     ("Реран персонажа", "Не объявлен", rer, False, ("rerun",)))
        cards = []
        for caption, empty, entry, is_current, generic in specs:
            if entry is None and info is not None:
                continue                                  # JSON получен, а этого баннера в нём нет
            text, hint, kind = C.banner_countdown(entry, now)
            card = {"caption": caption, "name": entry["name"] if entry else empty, "entry": entry,
                    "countdown": text, "hint": hint, "kind": kind, "arc": is_arc, "lines": [],
                    "art": self.banner_art(entry["name"] if entry else "", generic)}
            lines = []
            if is_arc:
                std, ev = s["counter_std"], s["counter_ev"]
                if entry:
                    lo, hi = C.banner_pull_window(entry)
                    st = C.arc_period_stats(self.history, lo, hi)
                    std, ev = st["std"], st["ev"]
                    lines.append(f"Круток за период: {st['pulls']} · S: {st['s']}")
                    lines.append(self._period_line(entry, lo, hi))
                elif is_current:
                    lines.append(f"Круток в пуле: {s['total']} · S: {s['r5']}")
                else:
                    lines.append("Реран дуги пока не объявлен в banners.json")
                lines.append(f"До гаранта S дуги: {max(0, C.PITY_ARC_STD - std)} · "
                             f"ивентовой S дуги: {max(0, C.PITY_ARC_EVENT - ev)}")
                card.update(std=std, ev=ev)
            else:
                pity = s["counter"]
                if entry:
                    lo, hi = C.banner_pull_window(entry)
                    st = C.banner_period_stats(self.history, C.EVENT_BANNER, lo, hi)
                    pity = st["pity"]
                    lines.append(f"Круток за период: {st['pulls']} · S: {st['s']}")
                    lines.append(self._period_line(entry, lo, hi))
                elif is_current:
                    lines.append(f"Круток в пуле: {s['total']} · S: {s['r5']}")
                else:
                    lines.append("Реран пока не объявлен в banners.json")
                lines.append(f"До жёсткого гаранта осталось: {max(0, C.PITY_CHAR_HARD - pity)}")
                card["pity"] = min(pity, C.PITY_CHAR_HARD)
            card["lines"] = lines
            cards.append(card)
        return cards

    @staticmethod
    def _period_line(entry, lo, hi) -> str:
        finish = f"{hi:%d.%m.%Y}" if hi else "…"
        if entry.get("start"):
            return f"Период: {entry['start']:%d.%m.%Y} — {finish}"
        if lo:
            return f"Учёт с {lo:%d.%m.%Y %H:%M} (старт не указан) — {finish}"
        return f"Период: … — {finish}"

    # ---------- иконки, арт, фон ----------
    @staticmethod
    def blurred_background(src: str, cache_dir) -> str:
        """Размытая копия фона (Pillow), как BACKGROUND_BLUR_RADIUS на десктопе; кэшируется.
        При любой ошибке возвращается исходный файл."""
        import os
        try:
            from PIL import Image, ImageFilter
            st = os.stat(src)
            out = Path(cache_dir) / f"bg_blur_{st.st_size}_{int(st.st_mtime)}.jpg"
            if out.is_file():
                return str(out)
            side = 640                                   # рабочая копия: быстро и достаточно мягко
            img = Image.open(src).convert("RGB")
            img.thumbnail((side, side))
            img = img.filter(ImageFilter.GaussianBlur(C.BACKGROUND_BLUR_RADIUS * side / C.BACKGROUND_WORK_SIDE))
            img.save(out, "JPEG", quality=88)
            return str(out)
        except Exception:  # noqa: BLE001
            return src

    @staticmethod
    def find_background():
        """assets/background.(png|jpg|jpeg|webp) — как на десктопе; None, если файла нет."""
        roots = [C.app_dir()] + ([Path(C._DATA_DIR)] if C._DATA_DIR is not None else [])   # noqa: SLF001
        for ext in C.BACKGROUND_EXTS:
            for root in roots:
                for base in C.ICON_DIR_NAMES:
                    p = root / base / f"{C.BACKGROUND_NAME}{ext}"
                    if p.is_file():
                        return str(p)
        return None

    def icon(self, name, aliases=(), rarity=None):
        key = (name, tuple(aliases or ()), rarity)
        if key not in self._icons:
            try:
                p = C.find_icon_path(name, aliases or (), rarity)
            except Exception:  # noqa: BLE001
                p = None
            self._icons[key] = imgutil.thumb(p) if p else None   # чистое уменьшение вместо рваного
        return self._icons[key]

    def banner_art(self, name, generic=()):
        try:
            p = C._search_banner_art(name or "", generic)
        except Exception:  # noqa: BLE001
            p = None
        return str(p) if p else None

    # ---------- «История выпадения S» и составы (как PoolPage на десктопе) ----------
    def drops(self, banner: str, hide_std: bool = False) -> list:
        is_arc = banner == C.ARC_BANNER
        drops = [e for e in self.history
                 if e["banner"] == banner and e["kind"] == "main" and e["rarity"] == 5]
        if is_arc and hide_std:
            drops = [e for e in drops
                     if C.arc_kind_by_name(e.get("name"), e.get("arc_kind") or "") == "event"]
        if not C.DROP_HISTORY_NEWEST_FIRST:
            drops.reverse()
        tiles = []
        for e in drops:
            if is_arc:
                is_event = C.arc_kind_by_name(e.get("name"), e.get("arc_kind") or "") == "event"
                pulls = e["ce"] if is_event else e["cs"]
                hard = C.PITY_ARC_EVENT if is_event else C.PITY_ARC_STD
                label = C.arc_short_name(e["name"])
            else:
                pulls, hard, label = e["p5"], C.PITY_CHAR_HARD, e["name"]
            tiles.append({"name": e["name"], "label": label, "value": str(pulls), "rank": 5,
                          "color": pity_hex(pulls, hard), "icon": self.icon(e["name"], e["aliases"], 5),
                          "dim": False})
        return tiles

    def rosters(self, banner: str) -> list:
        is_arc = banner == C.ARC_BANNER
        groups = (C.ARC_POOL_ROSTERS.get(banner) if is_arc else C.POOL_ROSTERS.get(banner)) or []
        counts = C.arc_roster_counts(self.history) if is_arc else C.roster_counts(self.history, banner)
        out = []
        for title, rarity, roster in groups:
            tiles, owned, seen = [], 0, set()
            if is_arc and rarity == 5:
                known_other = {C.roster_key(n) for t2, r2, ro2 in groups if ro2 is not roster and r2 == 5
                               for n in ro2}
            else:
                known_other = set()

            def tile(name, n):
                label = C.arc_short_name(name) if is_arc else name
                if n:
                    return {"name": name, "label": label, "value": f"×{n}", "rank": rarity,
                            "color": RANK_HEX.get(rarity, "ffffff"), "dim": False,
                            "icon": self.icon(name, (), rarity)}
                return {"name": name, "label": label, "value": "—", "rank": rarity, "color": "b4b9cc",
                        "dim": True, "icon": self.icon(name, (), rarity)}
            for name in roster:
                rk = C.roster_key(name)
                seen.add(rk)
                n = counts.get((rarity, rk), (name, 0))[1]
                owned += bool(n)
                tiles.append(tile(name, n))
            for (r, rk), (name, n) in counts.items():
                if r == rarity and rk not in seen and rk not in known_other:
                    tiles.append(tile(name, n))
            out.append({"title": f"{title} — получено {owned} из {len(roster)}", "tiles": tiles})
        return out

    # ---------- баннеры из banners.json (без Qt; логика BannerFetchThread) ----------
    @staticmethod
    def _ssl_contexts() -> list:
        """Контексты по очереди: certifi, системные сертификаты Android, умолчание Python и, в самом
        конце, без проверки (публичный JSON с названиями и датами баннеров)."""
        import os
        import ssl
        ctxs = []
        try:
            import certifi
            ctxs.append((ssl.create_default_context(cafile=certifi.where()), "certifi"))
        except Exception:  # noqa: BLE001
            pass
        for d in ("/system/etc/security/cacerts", "/apex/com.android.conscrypt/cacerts"):
            if os.path.isdir(d):
                try:
                    c = ssl.create_default_context()
                    c.load_verify_locations(capath=d)
                    ctxs.append((c, "системные"))
                except Exception:  # noqa: BLE001
                    pass
        ctxs.append((None, "умолчание"))
        ctxs.append((ssl._create_unverified_context(), "без проверки сертификата"))   # noqa: SLF001
        return ctxs

    def fetch_banners(self) -> bool:
        errors = []
        for url in C.BANNER_URLS:
            full = f"{url}{'&' if '?' in url else '?'}t={int(time.time())}"
            headers = {"User-Agent": C.BANNER_USER_AGENT, "Accept": "application/json",
                       "Cache-Control": "no-cache"}
            for ctx, label in self._ssl_contexts():
                try:
                    req = urllib.request.Request(full, headers=headers)
                    with urllib.request.urlopen(req, timeout=max(C.BANNER_TIMEOUT, 10), context=ctx) as resp:
                        raw = resp.read(C.BANNER_MAX_BYTES + 1)
                    if len(raw) > C.BANNER_MAX_BYTES:
                        raise ValueError("ответ слишком большой")
                    self.banner_info = C.parse_banner_payload(json.loads(raw.decode("utf-8-sig")))
                    self.last_banner_error = ""
                    return True
                except Exception as e:  # noqa: BLE001 — urllib оборачивает SSLError в URLError
                    errors.append(f"{label}: {type(e).__name__}")
                    if "CERTIFICATE" not in str(e).upper() and "SSL" not in str(e).upper():
                        break                           # не про сертификаты — другой контекст не поможет
        self.last_banner_error = "; ".join(errors)[:300]
        return False

    # ---------- импорт истории с ПК (JSON / CSV / файл базы .db) ----------
    @staticmethod
    def _normalize_keep_seq(raw: list, fn, label: str):
        """Как normalize_all, но сохраняет номер seq (порядок внутри одной секунды), если он есть."""
        valid, errors = [], []
        for i, r in enumerate(raw, 1):
            try:
                rec = fn(r)
            except Exception as e:  # noqa: BLE001
                errors.append(f"{label} {i}: {e}")
                continue
            try:
                if r.get("seq") not in (None, ""):
                    rec["seq"] = int(r["seq"])
            except (TypeError, ValueError, AttributeError):
                pass
            valid.append(rec)
        return valid, errors

    def read_import(self, path: str) -> dict:
        """Читает файл и проверяет записи, ничего не меняя. Формат определяется по содержимому:
        SQLite-файл (nte_wishes.db с ПК), JSON (крутки + предметы) или CSV."""
        p = Path(path)
        with open(p, "rb") as f:
            head = f.read(16)
        if head.startswith(b"SQLite format 3"):
            return self._read_desktop_db(p)
        raw, raw_rw = [], []
        if p.suffix.lower() == ".csv":
            raw = C.load_csv_records(p)
        else:
            raw = C.parse_game_logs(str(p))
            if p.suffix.lower() == ".json" or head.lstrip()[:1] in (b"{", b"["):
                raw_rw = C.load_json_rewards(p)
        valid, errors = self._normalize_keep_seq(raw, C.normalize_record, "запись")
        valid_rw, errors_rw = self._normalize_keep_seq(raw_rw, C.normalize_reward, "предмет")
        has_seq = any("seq" in r for r in valid + valid_rw)
        return {"kind": "file", "valid": valid, "valid_rw": valid_rw, "errors": errors + errors_rw,
                "has_rewards": bool(raw_rw), "has_seq": has_seq}

    def _read_desktop_db(self, p: Path) -> dict:
        import sqlite3
        src = sqlite3.connect(str(p))
        src.row_factory = sqlite3.Row
        try:
            cols = {r[1] for r in src.execute("PRAGMA table_info(wishes)")}
            if not {"banner", "rarity", "name", "pulled_at"} <= cols:
                raise ValueError("Это не база NTE Wish Tracker.")
            has_pid = "profile_id" in cols
            try:
                profs = [dict(r) for r in src.execute("SELECT id, name FROM profiles ORDER BY id")]
            except sqlite3.Error:
                profs = []
            if not profs:
                profs = [{"id": 0, "name": "Импорт"}]
            out, all_errors = [], []
            for pr in profs:
                where, args = (" WHERE profile_id = ?", (pr["id"],)) if has_pid else ("", ())
                wishes = [dict(r) for r in src.execute(
                    f"SELECT {', '.join(C.WISH_COLS)}, seq FROM wishes{where} "
                    "ORDER BY pulled_at ASC, seq ASC, id ASC", args)]
                try:
                    rewards = [dict(r) for r in src.execute(
                        f"SELECT {', '.join(C.REWARD_COLS)}, seq FROM rewards{where} "
                        "ORDER BY obtained_at ASC, seq ASC, id ASC", args)]
                except sqlite3.Error:
                    rewards = []
                valid, errors = self._normalize_keep_seq(wishes, C.normalize_record, "запись")
                valid_rw, errors_rw = self._normalize_keep_seq(rewards, C.normalize_reward, "предмет")
                all_errors += errors + errors_rw
                if valid or valid_rw:
                    out.append({"name": pr["name"], "valid": valid, "valid_rw": valid_rw,
                                "errors": errors + errors_rw})
        finally:
            src.close()
        return {"kind": "db", "profiles": out, "has_seq": True,
                "valid": sum(len(x["valid"]) for x in out), "valid_rw": sum(len(x["valid_rw"]) for x in out),
                "errors": all_errors}

    def apply_import(self, data: dict, into_current: bool = True) -> str:
        """Записывает проверенные данные; дубликаты (то же название и время) пропускаются."""
        def put(valid, valid_rw):
            if any("seq" in r for r in valid + valid_rw):
                # порядок внутри одной секунды (seq) сохраняется точно как на ПК
                new_w = C.Database._new_only(valid, self.db.fetch_all(), C._wish_key)          # noqa: SLF001
                new_r = C.Database._new_only(valid_rw, self.db.fetch_rewards(), C._reward_key)  # noqa: SLF001
                a, ar = self.db.import_batch(new_w, new_r)
                return a, len(valid) - a, ar, len(valid_rw) - ar
            a, sk = self.db.import_records(valid) if valid else (0, 0)
            ar, skr = self.db.import_rewards(valid_rw) if valid_rw else (0, 0)
            return a, sk, ar, skr
        lines = []
        if data["kind"] == "file":
            a, sk, ar, skr = put(data["valid"], data["valid_rw"])
            lines.append(f"Круток добавлено: {a}, пропущено (дубликаты): {sk}")
            if data["valid_rw"]:
                lines.append(f"Предметов добавлено: {ar}, пропущено: {skr}")
        else:
            original = self.db.profile_id
            profs = data["profiles"]
            for pr in profs:
                if into_current and len(profs) == 1:
                    target = original
                else:
                    match = next((x for x in self.db.list_profiles() if x["name"] == pr["name"]), None)
                    target = match["id"] if match else self.db.create_profile(pr["name"])
                self.db.set_active_profile(target)
                a, sk, ar, skr = put(pr["valid"], pr["valid_rw"])
                lines.append(f"«{pr['name']}»: круток {a} (дубликатов {sk}), предметов {ar} (дубликатов {skr})")
            self.db.set_active_profile(original)
        self.refresh()
        return "\n".join(lines)

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

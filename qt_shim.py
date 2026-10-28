"""Минимальные замены QDateTime и QColor, чтобы логика из main.py работала без Qt."""
import re
from datetime import datetime, timedelta

_TOKENS = [("yyyy", "%Y"), ("MM", "%m"), ("dd", "%d"), ("HH", "%H"), ("mm", "%M"), ("ss", "%S")]


def _to_strptime(fmt: str) -> str:
    for qt, py in _TOKENS:
        fmt = fmt.replace(qt, py)
    return fmt


class QDateTime:
    """Обёртка над datetime с методами Qt, которые реально использует логика импорта."""

    __slots__ = ("_dt",)

    def __init__(self, dt: datetime = None):
        self._dt = dt

    @classmethod
    def fromString(cls, text: str, fmt: str = "yyyy-MM-dd HH:mm:ss") -> "QDateTime":
        try:
            return cls(datetime.strptime(str(text), _to_strptime(fmt)))
        except (ValueError, TypeError):
            return cls(None)                      # как в Qt: невалидная дата

    @classmethod
    def currentDateTime(cls) -> "QDateTime":
        return cls(datetime.now().replace(microsecond=0))

    @classmethod
    def fromPyDateTime(cls, dt: datetime) -> "QDateTime":
        return cls(dt)

    def isValid(self) -> bool:
        return self._dt is not None

    def toString(self, fmt: str = "yyyy-MM-dd HH:mm:ss") -> str:
        return self._dt.strftime(_to_strptime(fmt)) if self._dt else ""

    def toPyDateTime(self) -> datetime:
        return self._dt

    def toSecsSinceEpoch(self) -> int:
        return int(self._dt.timestamp()) if self._dt else 0

    def addSecs(self, s: int) -> "QDateTime":
        return QDateTime(self._dt + timedelta(seconds=s) if self._dt else None)

    def secsTo(self, other: "QDateTime") -> int:
        return int((other._dt - self._dt).total_seconds())

    def _key(self):
        return self._dt or datetime.min

    def __eq__(self, o):
        return isinstance(o, QDateTime) and self._dt == o._dt

    def __lt__(self, o):
        return self._key() < o._key()

    def __le__(self, o):
        return self._key() <= o._key()

    def __gt__(self, o):
        return self._key() > o._key()

    def __ge__(self, o):
        return self._key() >= o._key()

    def __hash__(self):
        return hash(self._dt)

    def __repr__(self):
        return f"QDateTime({self.toString()!r})"


class QColor:
    """Цвет как RGBA-кортеж; name() нужен тем, кто красит текст в hex."""

    def __init__(self, r=0, g=0, b=0, a=255):
        if isinstance(r, str):
            h = r.lstrip("#")
            r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
        self.r, self.g, self.b, self.a = r, g, b, a

    def name(self) -> str:
        return f"#{self.r:02x}{self.g:02x}{self.b:02x}"

    def rgba_float(self):
        return (self.r / 255, self.g / 255, self.b / 255, self.a / 255)

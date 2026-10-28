#!/usr/bin/env python3
"""Извлекает из десктопного main.py (PyQt6) модуль nte_core.py БЕЗ Qt.

Берутся все top-level узлы AST, которые не зависят от Qt: константы, OCR-конвейер,
парсеры русских дат, словари имён, класс Database, compute_stats, разбор banners.json,
сортировка пакетного импорта и т.д. Узлы, использующие виджеты/рисование/потоки Qt,
отбрасываются (вместе с теми, кто на них ссылается). QDateTime и QColor подменяются
лёгкими классами из qt_shim.py.

Запуск:  python tools/extract_core.py ../main.py nte_core.py
Повторяйте после каждой правки логики в main.py — Android-версия получит её автоматически.
"""
import ast
import builtins
import sys
from pathlib import Path

QT_NAMES = set("""
QEasingCurve QElapsedTimer QEvent QObject QPoint QPointF QPropertyAnimation QRect QRectF QSize Qt
QParallelAnimationGroup QSequentialAnimationGroup QThread QTimer QUrl QVariantAnimation pyqtSignal
QBrush QDesktopServices QFont QFontMetricsF QGuiApplication QIcon QImage QLinearGradient QPainter
QPainterPath QPen QPixmap QPolygonF QRadialGradient QStandardItem QStandardItemModel QTransform
QCursor QGraphicsObject QGraphicsPathItem QGraphicsView QMenu QToolTip QAbstractItemView
QApplication QCheckBox QComboBox QCompleter QDateTimeEdit QDialog QDoubleSpinBox QFileDialog
QFormLayout QFrame QGraphicsBlurEffect QGraphicsDropShadowEffect QGraphicsOpacityEffect
QGraphicsPixmapItem QGraphicsScene QGridLayout QGroupBox QHBoxLayout QHeaderView QLabel QLineEdit
QListWidget QListWidgetItem QMainWindow QMessageBox QPlainTextEdit QProgressBar QPushButton QLayout
QScrollArea QSizePolicy QSlider QSpinBox QSplitter QStackedWidget QStyle QTableWidget
QTableWidgetItem QTabWidget QToolButton QVBoxLayout QWidget QSizeGrip QAudioOutput QMediaPlayer
QAudio QSoundEffect
""".split())

SHIMMED = {"QDateTime", "QColor"}   # реализованы в qt_shim.py


def node_names(node) -> set:
    out = set()
    for x in ast.walk(node):
        if isinstance(x, ast.Name):
            out.add(x.id)
    return out


def defined_names(node) -> set:
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
        return {node.name}
    out = set()
    for stmt in ast.walk(node):
        if isinstance(stmt, ast.Name) and isinstance(stmt.ctx, ast.Store):
            out.add(stmt.id)
        elif isinstance(stmt, (ast.Import, ast.ImportFrom)):
            for a in stmt.names:
                out.add((a.asname or a.name).split(".")[0])
    return out


def main(src_path: str, dst_path: str) -> None:
    text = Path(src_path).read_text(encoding="utf-8", errors="replace")
    lines = text.split("\n")
    tree = ast.parse(text)

    nodes = []
    prev_end = 0
    for n in tree.body:
        start = min([n.lineno] + [d.lineno for d in getattr(n, "decorator_list", [])])
        if isinstance(n, ast.Expr) and isinstance(getattr(n, "value", None), ast.Constant) \
                and n.lineno == 1:
            prev_end = n.end_lineno
            continue
        seg_start = prev_end + 1                      # забираем комментарии перед узлом
        src = "\n".join(lines[seg_start - 1:n.end_lineno]).strip("\n")
        nodes.append({"node": n, "src": src, "start": start, "end": n.end_lineno,
                      "defs": defined_names(n), "refs": node_names(n)})
        prev_end = n.end_lineno

    dropped = set()
    for i, d in enumerate(nodes):
        seg = d["src"]
        if "PyQt6" in seg or (d["refs"] & (QT_NAMES - SHIMMED)):
            dropped.add(i)
        elif isinstance(d["node"], ast.If) and "__main__" in seg:
            dropped.add(i)

    changed = True
    while changed:                                    # замыкание: кто ссылается на выброшенное
        changed = False
        gone = set()
        for i in dropped:
            gone |= nodes[i]["defs"]
        alive_defs = set()
        for i, d in enumerate(nodes):
            if i not in dropped:
                alive_defs |= d["defs"]
        gone -= alive_defs | SHIMMED
        for i, d in enumerate(nodes):
            if i not in dropped and (d["refs"] & gone):
                dropped.add(i)
                changed = True

    kept = [d for i, d in enumerate(nodes) if i not in dropped]
    alive_defs = set()
    for d in kept:
        alive_defs |= d["defs"]

    # грубая проверка неопределённых имён
    known = alive_defs | set(dir(builtins)) | SHIMMED | {"__file__", "__name__"}
    problems = {}
    for d in kept:
        local = set()
        for x in ast.walk(d["node"]):
            if isinstance(x, ast.Name) and isinstance(x.ctx, (ast.Store, ast.Del)):
                local.add(x.id)
            elif isinstance(x, ast.arg):
                local.add(x.arg)
            elif isinstance(x, (ast.FunctionDef, ast.ClassDef, ast.AsyncFunctionDef)):
                local.add(x.name)
            elif isinstance(x, ast.ExceptHandler) and x.name:
                local.add(x.name)
            elif isinstance(x, (ast.Import, ast.ImportFrom)):
                for a in x.names:
                    local.add((a.asname or a.name).split(".")[0])
        for x in ast.walk(d["node"]):
            if isinstance(x, ast.Name) and isinstance(x.ctx, ast.Load) \
                    and x.id not in known and x.id not in local:
                problems.setdefault(x.id, d["src"].split("\n")[0][:70])

    header = ('"""АВТОГЕНЕРАЦИЯ: tools/extract_core.py из main.py. Не редактируйте вручную."""\n'
              "from qt_shim import QDateTime, QColor  # noqa: F401\n\n\n")
    body = "\n\n\n".join(d["src"] for d in kept)
    Path(dst_path).write_text(header + body + "\n", encoding="utf-8")

    print(f"узлов всего: {len(nodes)}, оставлено: {len(kept)}, выброшено: {len(dropped)}")
    for i in sorted(dropped):
        n = nodes[i]
        print(f"  выброшено: {n['start']:>6}  {sorted(n['defs'])[:3]}")
    if problems:
        print("ВНИМАНИЕ, неопределённые имена в оставшемся коде:")
        for k, v in sorted(problems.items()):
            print(f"  {k}  (первое упоминание в: {v})")
    else:
        print("неопределённых имён нет")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    main(sys.argv[1], sys.argv[2])

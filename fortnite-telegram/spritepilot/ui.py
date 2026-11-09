from __future__ import annotations

from datetime import datetime
import json
from pathlib import Path
import time
import uuid

import cv2
from PySide6.QtCore import Qt, QTimer, QRect, QPoint, QUrl
from PySide6.QtGui import QPixmap, QImage, QPainter, QColor, QPen, QDesktopServices
from PySide6.QtWidgets import (QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QFrame, QStackedWidget, QGridLayout, QFormLayout, QComboBox,
    QSpinBox, QDoubleSpinBox, QCheckBox, QLineEdit, QScrollArea, QFileDialog,
    QMessageBox, QDialog, QTableWidget, QTableWidgetItem, QHeaderView)

from .rewards import crop_rect, read_image, write_image
from .settings import atomic_json, save_token

STYLE = """
QWidget { background: #10151e; color: #e9eef7; font-family: 'Segoe UI', 'DejaVu Sans'; font-size: 13px; }
QMainWindow { background: #10151e; }
QLabel { background: transparent; }
QLabel#Muted { color: #8d9bb0; }
QLabel#Title { font-size: 29px; font-weight: 700; }
QLabel#Stat { font-size: 35px; font-weight: 600; }
QLabel#Accent { color: #77d4f4; }
QFrame#Sidebar { background: #151c28; border-right: 1px solid #263142; }
QFrame#Card { background: #192230; border: 1px solid #2b3749; border-radius: 15px; }
QFrame#Card QLabel { background: transparent; }
QPushButton { background: #243044; border: 1px solid #334359; padding: 10px 16px; border-radius: 8px; font-weight: 600; }
QPushButton:hover { background: #30415b; }
QPushButton:disabled { color: #68768b; background: #1b2433; }
QPushButton#Primary { background: #78d5ef; color: #11232b; border: none; }
QPushButton#Primary:hover { background: #a1e8fa; }
QPushButton#Danger { color: #ffb4b4; border-color: #69404a; background: #36232e; }
QPushButton#Nav { text-align: left; padding: 13px 16px; border: none; background: transparent; color: #9eabc0; }
QPushButton#Nav:checked { background: #253c50; color: #9ce7ff; }
QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox { background: #101923; border: 1px solid #354258; border-radius: 7px; padding: 8px; min-height: 20px; }
QComboBox QAbstractItemView { background: #1b2636; selection-background-color: #33536b; }
QCheckBox { spacing: 9px; padding: 5px; }
QCheckBox::indicator { width: 18px; height: 18px; }
QScrollArea { border: none; }
QTableWidget { background: #192230; border: 1px solid #2b3749; gridline-color: #263246; alternate-background-color: #17202c; }
QHeaderView::section { background: #202c3c; padding: 10px; border: none; color: #a8b9cf; }
QToolTip { background: #26364a; color: #edf4ff; border: 1px solid #536987; padding: 6px; }
"""


def label(text, kind="", wrap=False):
    widget = QLabel(text)
    widget.setObjectName(kind)
    widget.setWordWrap(wrap)
    return widget


def button(text, callback, kind=""):
    widget = QPushButton(text)
    widget.setObjectName(kind)
    widget.clicked.connect(callback)
    return widget


def card():
    widget = QFrame()
    widget.setObjectName("Card")
    layout = QVBoxLayout(widget)
    layout.setContentsMargins(22, 20, 22, 20)
    layout.setSpacing(12)
    return widget, layout


def pixmap(frame):
    rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
    h, w = rgb.shape[:2]
    return QPixmap.fromImage(QImage(rgb.data, w, h, rgb.strides[0], QImage.Format.Format_RGB888).copy())


class ImageDialog(QDialog):
    def __init__(self, frame, title, parent=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        layout = QVBoxLayout(self)
        view = QLabel()
        view.setPixmap(pixmap(frame).scaled(1000, 650, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
        layout.addWidget(view)
        layout.addWidget(button("Закрыть", self.accept))


class CropCanvas(QLabel):
    def __init__(self, frame):
        super().__init__()
        self.frame = frame
        self.image = pixmap(frame).scaled(960, 570, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
        self.setFixedSize(self.image.size())
        self.start = None
        self.rect = QRect()
        self.setCursor(Qt.CursorShape.CrossCursor)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.start = event.position().toPoint()
            self.rect = QRect(self.start, self.start)
            self.update()

    def mouseMoveEvent(self, event):
        if self.start is not None:
            point = event.position().toPoint()
            point.setX(max(0, min(self.width()-1, point.x())))
            point.setY(max(0, min(self.height()-1, point.y())))
            self.rect = QRect(self.start, point).normalized()
            self.update()

    def mouseReleaseEvent(self, event):
        self.start = None

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.drawPixmap(0, 0, self.image)
        if not self.rect.isNull():
            painter.setPen(QPen(QColor("#80ddff"), 2))
            painter.fillRect(self.rect, QColor(100, 210, 250, 45))
            painter.drawRect(self.rect)

    def selected(self):
        scale_x, scale_y = self.frame.shape[1]/self.width(), self.frame.shape[0]/self.height()
        rect = [round(self.rect.x()*scale_x), round(self.rect.y()*scale_y), round(self.rect.width()*scale_x), round(self.rect.height()*scale_y)]
        crop_rect(self.frame, rect)
        return rect


class CalibrationDialog(QDialog):
    def __init__(self, frame, settings, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Sprite Gizmo · настройка распознавания")
        self.anchor = self.icon = None
        self.step = 0
        layout = QVBoxLayout(self)
        self.help = label("1 / 2 · Обведите только общую надпись SPRITE GIZMO, без иконки.", "Accent")
        layout.addWidget(self.help)
        self.canvas = CropCanvas(frame)
        layout.addWidget(self.canvas)
        row = QHBoxLayout()
        self.variant = QComboBox()
        self.variant.addItem("Сохранить только области · вариант неизвестен", "unknown")
        for key, name in settings.variants.items():
            self.variant.addItem(name, key)
        row.addWidget(self.variant)
        self.next_button = button("Далее →", self.advance, "Primary")
        row.addWidget(self.next_button)
        row.addWidget(button("Отмена", self.reject))
        layout.addLayout(row)

    def advance(self):
        try:
            selected = self.canvas.selected()
        except ValueError as error:
            QMessageBox.information(self, "Область", str(error))
            return
        if self.step == 0:
            self.anchor = selected
            self.canvas.rect = QRect()
            self.canvas.update()
            self.step = 1
            self.help.setText("2 / 2 · Обведите квадрат с устройством над надписью. Выберите его вариант ниже.")
            self.next_button.setText("Сохранить")
        else:
            self.icon = selected
            self.accept()


class MainWindow(QMainWindow):
    def __init__(self, settings, store, engine, bridge, demo=False):
        super().__init__()
        self.s, self.store, self.engine, self.bridge, self.demo = settings, store, engine, bridge, demo
        self.setWindowTitle("Sprite Pilot" + (" · демонстрация" if demo else ""))
        self.resize(1240, 850)
        self.setMinimumSize(1080, 760)
        self.setStyleSheet(STYLE)
        self.last_rewards = None
        root = QWidget()
        self.setCentralWidget(root)
        shell = QHBoxLayout(root)
        shell.setContentsMargins(0, 0, 0, 0)
        shell.setSpacing(0)
        side = QFrame()
        side.setObjectName("Sidebar")
        side.setFixedWidth(215)
        nav = QVBoxLayout(side)
        nav.setContentsMargins(22, 30, 18, 24)
        brand = label("◈  SPRITE\n    PILOT", "Title")
        brand.setStyleSheet("font-size: 24px; letter-spacing: 2px; color: #a3e9fb;")
        nav.addWidget(brand)
        nav.addWidget(label("Ваш локальный помощник", "Muted"))
        nav.addSpacing(32)
        self.nav = []
        self.pages = QStackedWidget()
        builders = [("Обзор", self.build_overview), ("Автоматизация", self.build_automation),
                    ("Награды", self.build_rewards), ("Telegram", self.build_telegram), ("Журнал", self.build_log)]
        for index, (name, builder) in enumerate(builders):
            item = button(name, lambda checked=False, i=index: self.show_page(i), "Nav")
            item.setCheckable(True)
            self.nav.append(item)
            nav.addWidget(item)
            page = QWidget()
            outer = QVBoxLayout(page)
            outer.setContentsMargins(32, 28, 32, 24)
            outer.setSpacing(20)
            outer.addWidget(label(name, "Title"))
            builder(outer)
            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            scroll.setWidget(page)
            self.pages.addWidget(scroll)
        nav.addStretch()
        nav.addWidget(label("ДЕМО · без управления" if demo else "Локально · Windows", "Accent"))
        nav.addWidget(label("v0.1.0 · предварительная", "Muted"))
        nav.addWidget(label("F8 — остановить", "Muted"))
        shell.addWidget(side)
        shell.addWidget(self.pages, 1)
        self.show_page(0)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.refresh)
        self.timer.start(750)
        self.refresh()

    def show_page(self, index):
        self.pages.setCurrentIndex(index)
        for i, item in enumerate(self.nav):
            item.setChecked(i == index)

    def build_overview(self, layout):
        hero, body = card()
        body.addWidget(label("СЕССИЯ / LIVE", "Accent"))
        self.live_state = label("Готов к запуску", "Title")
        body.addWidget(self.live_state)
        self.live_note = label("Откройте Fortnite и выберите режим работы.", "Muted", True)
        body.addWidget(self.live_note)
        actions = QHBoxLayout()
        actions.addWidget(button("▶  Запустить", lambda: self.engine.submit("start"), "Primary"))
        actions.addWidget(button("Пауза", lambda: self.engine.submit("pause")))
        actions.addWidget(button("■  Остановить", lambda: self.engine.submit("stop"), "Danger"))
        actions.addStretch()
        actions.addWidget(button("Скриншот", self.capture))
        body.addLayout(actions)
        layout.addWidget(hero)
        stats = QHBoxLayout()
        self.stats = {}
        for key, title in (("elapsed", "ДЛИТЕЛЬНОСТЬ"), ("loops", "ЦИКЛЫ"), ("rewards", "НАГРАДЫ")):
            box, inner = card()
            inner.addWidget(label(title, "Muted"))
            value = label("00:00" if key == "elapsed" else "0", "Stat")
            self.stats[key] = value
            inner.addWidget(value)
            stats.addWidget(box)
        layout.addLayout(stats)
        status, body = card()
        body.addWidget(label("Подключения и распознавание", "Accent"))
        self.game_status = label("Игра · ожидание", wrap=True)
        self.telegram_status = label("Telegram · отключён", wrap=True)
        self.detector_status = label("Sprite Gizmo · настройте образцы пяти вариантов", wrap=True)
        for widget in (self.game_status, self.telegram_status, self.detector_status):
            body.addWidget(widget)
        body.addWidget(button("Настроить награды →", lambda: self.show_page(2)))
        layout.addWidget(status)
        self.last_event = label("", "Muted", True)
        layout.addWidget(self.last_event)
        layout.addStretch()

    def build_automation(self, layout):
        box, inner = card()
        form = QFormLayout()
        form.setSpacing(15)
        self.fields = {}
        for key, title, choices in (("mode", "Режим", [("A · Обычный цикл", "A"), ("B · Остров и выход", "B")]),
                                    ("lang", "Язык игры", [("English", "en"), ("Русский · beta", "ru"), ("日本語", "ja"), ("Español · beta", "es"), ("Português · beta", "pt")])):
            widget = QComboBox()
            for name, value in choices:
                widget.addItem(name, value)
            widget.setCurrentIndex(max(0, widget.findData(getattr(self.s, key))))
            self.fields[key] = widget
            form.addRow(title, widget)
        for key, title, low, high, step in (("wait_b", "Ожидание режима B, с", 10, 600, 5),
                ("threshold", "Порог совпадения кнопок", .3, .99, .01),
                ("afk_interval", "Интервал WASD, с", 1, 600, 1), ("afk_hold", "Удержание WASD, с", .1, 30, .5),
                ("summary_minutes", "Сводка в Telegram, мин · 0 = выкл", 0, 1440, 15),
                ("stuck_minutes", "Сообщать о зависании через, мин", 1, 240, 1)):
            widget = QDoubleSpinBox()
            widget.setRange(low, high)
            widget.setSingleStep(step)
            widget.setDecimals(2 if key == "threshold" else 1 if key == "afk_hold" else 0)
            widget.setValue(getattr(self.s, key))
            self.fields[key] = widget
            form.addRow(title, widget)
        self.afk_check = QCheckBox("Периодически нажимать WASD в матче")
        self.afk_check.setChecked(self.s.afk_enabled)
        form.addRow(self.afk_check)
        inner.addLayout(form)
        inner.addWidget(label("Захват и нажатия работают, пока окно Fortnite открыто на переднем плане. F8 останавливает цикл.", "Muted", True))
        inner.addWidget(button("Сохранить настройки", self.save_automation, "Primary"))
        layout.addWidget(box)
        profiles = QHBoxLayout()
        profiles.addWidget(button("Экспорт профиля", self.export_profile))
        profiles.addWidget(button("Импорт профиля", self.import_profile))
        profiles.addWidget(button("Настроить кнопки игры", self.calibrate_button))
        layout.addLayout(profiles)
        layout.addStretch()

    def build_rewards(self, layout):
        box, inner = card()
        inner.addWidget(label("Пять устройств. Одна надпись.", "Accent"))
        inner.addWidget(label("Общая плашка находит событие; иконка определяет вариант. Пока не добавлены все пять образцов, находки сохраняются без предположения о варианте.", "Muted", True))
        row = QHBoxLayout()
        row.addWidget(button("＋  Добавить образец", self.calibrate_reward, "Primary"))
        row.addWidget(button("Названия и избранное", self.edit_variants))
        row.addWidget(button("Папка изображений", lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.store.root / 'rewards')))))
        inner.addLayout(row)
        self.calibration_status = label("", "Muted")
        inner.addWidget(self.calibration_status)
        layout.addWidget(box)
        filters = QHBoxLayout()
        self.variant_filter = QComboBox()
        self.variant_filter.addItem("Все варианты", "")
        self.variant_filter.addItem("Не определён", "unknown")
        self.variant_filter.addItem("Экраны наград", "reward_screen")
        for key, name in self.s.variants.items():
            self.variant_filter.addItem(name, key)
        self.date_filter = QComboBox()
        self.date_filter.addItems(["Все даты", "Сегодня", "Последние 7 дней"])
        self.match_filter = QLineEdit()
        self.match_filter.setPlaceholderText("Поиск по ID матча")
        for widget in (self.variant_filter, self.date_filter, self.match_filter):
            filters.addWidget(widget)
        self.variant_filter.currentIndexChanged.connect(self.refresh_gallery)
        self.date_filter.currentIndexChanged.connect(self.refresh_gallery)
        self.match_filter.textChanged.connect(self.refresh_gallery)
        layout.addLayout(filters)
        self.gallery = QWidget()
        self.gallery_layout = QGridLayout(self.gallery)
        self.gallery_layout.setContentsMargins(0, 0, 0, 0)
        self.gallery_layout.setSpacing(16)
        layout.addWidget(self.gallery)
        layout.addStretch()

    def build_telegram(self, layout):
        box, inner = card()
        inner.addWidget(label("Управление там, где удобно", "Accent"))
        inner.addWidget(label("Создайте личного бота через @BotFather. После подключения откройте его в Telegram и отправьте /panel. Доступ разрешён только указанному пользователю в личном чате.", "Muted", True))
        form = QFormLayout()
        self.token_input = QLineEdit()
        self.token_input.setEchoMode(QLineEdit.EchoMode.Password)
        self.token_input.setPlaceholderText("Новый токен · сохранённый не отображается")
        self.user_input = QLineEdit(str(self.s.telegram_user_id or ""))
        self.user_input.setPlaceholderText("Ваш числовой Telegram user ID")
        form.addRow("Токен бота", self.token_input)
        form.addRow("Telegram ID", self.user_input)
        inner.addLayout(form)
        self.telegram_checks = {}
        for key, text in (("telegram_enabled", "Подключить Telegram"), ("remote_control", "Разрешить удалённое управление"),
                          ("remote_screenshots", "Разрешить запросы скриншотов окна игры"),
                          ("notify_rewards", "Отправлять найденные награды"), ("notify_unknown", "Отправлять находки с неопределённым вариантом"),
                          ("pause_on_favorite", "Ставить на паузу при избранной находке")):
            widget = QCheckBox(text)
            widget.setChecked(getattr(self.s, key))
            self.telegram_checks[key] = widget
            inner.addWidget(widget)
        self.telegram_detail = label("", "Accent", True)
        inner.addWidget(self.telegram_detail)
        controls = QHBoxLayout()
        controls.addWidget(button("Сохранить и подключить", self.save_telegram, "Primary"))
        controls.addWidget(button("Тестовое сообщение", self.test_telegram))
        inner.addLayout(controls)
        inner.addWidget(label("Токен хранится в системном хранилище учётных данных и не попадает в профиль настроек. Недоставленные сообщения сохраняются локально.", "Muted", True))
        layout.addWidget(box)
        layout.addStretch()

    def build_log(self, layout):
        layout.addWidget(label("События сохраняются на компьютере. Последние 200 записей.", "Muted"))
        self.log_table = QTableWidget(0, 3)
        self.log_table.setHorizontalHeaderLabels(["Время", "Уровень", "Событие"])
        self.log_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.log_table.setColumnWidth(0, 150)
        self.log_table.setColumnWidth(1, 90)
        self.log_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.log_table.setWordWrap(True)
        self.log_table.setMinimumHeight(480)
        layout.addWidget(self.log_table)
        layout.addWidget(button("Открыть папку данных", lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.store.root)))))

    def save_automation(self):
        values = {key: widget.currentData() if isinstance(widget, QComboBox) else widget.value() for key, widget in self.fields.items()}
        values["afk_enabled"] = self.afk_check.isChecked()
        self.engine.submit("configure", values)

    def export_profile(self):
        path, _ = QFileDialog.getSaveFileName(self, "Экспорт профиля", "spritepilot-profile.json", "JSON (*.json)")
        if path:
            self.s.export_profile(Path(path))
            self.store.event("Профиль экспортирован без токена и Telegram ID")

    def import_profile(self):
        path, _ = QFileDialog.getOpenFileName(self, "Импорт профиля", "", "JSON (*.json)")
        if not path:
            return
        try:
            values = json.loads(Path(path).read_text(encoding="utf-8"))
            if not isinstance(values, dict):
                raise ValueError("Ожидается объект настроек")
            for key in ("telegram_user_id", "telegram_enabled", "remote_control", "remote_screenshots", "calibration"):
                values.pop(key, None)
            self.engine.submit("configure", values)
            from copy import deepcopy
            preview = deepcopy(self.s)
            preview.apply(values)
            for key, widget in self.fields.items():
                if isinstance(widget, QComboBox):
                    widget.setCurrentIndex(max(0, widget.findData(getattr(preview, key))))
                else:
                    widget.setValue(getattr(preview, key))
            self.afk_check.setChecked(preview.afk_enabled)
        except (OSError, ValueError) as error:
            QMessageBox.warning(self, "Профиль", str(error))

    def capture(self):
        try:
            frame, _, _ = self.engine.current_frame(fresh=True)
            ImageDialog(frame, "Текущий кадр игры", self).exec()
        except Exception as error:
            QMessageBox.information(self, "Скриншот", str(error))

    def source_image(self):
        path, _ = QFileDialog.getOpenFileName(self, "Выберите полный кадр игры с нужной плашкой", "", "Изображения (*.png *.jpg *.jpeg *.bmp)")
        if not path:
            return None
        frame = read_image(Path(path))
        if frame is None:
            QMessageBox.warning(self, "Изображение", "Не удалось прочитать изображение")
        return frame

    def calibrate_reward(self):
        frame = self.source_image()
        if frame is None:
            return
        dialog = CalibrationDialog(frame, self.s, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        try:
            write_image(self.store.root / "templates/anchor.png", crop_rect(frame, dialog.anchor))
            key = dialog.variant.currentData()
            if key != "unknown":
                write_image(self.store.root / "templates" / key / (uuid.uuid4().hex+".png"), crop_rect(frame, dialog.icon))
            values = {"calibration": {"anchor": dialog.anchor, "icon": dialog.icon}}
            self.engine.submit("configure", values)
            self.store.event("Области награды сохранены. Вариант определяется только по иконке.")
        except (ValueError, OSError) as error:
            QMessageBox.warning(self, "Шаблон", str(error))

    def calibrate_button(self):
        dialog = QDialog(self)
        dialog.setWindowTitle("Изображения кнопок игры")
        layout = QVBoxLayout(dialog)
        layout.addWidget(label("Выберите кнопку, затем снимок игры и обведите только нужную кнопку.", wrap=True))
        choice = QComboBox()
        from .engine import FILENAMES
        for key, stem in FILENAMES.items():
            choice.addItem(key, stem)
        layout.addWidget(choice)
        layout.addWidget(button("Выбрать кадр", dialog.accept, "Primary"))
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        frame = self.source_image()
        if frame is None:
            return
        crop_dialog = QDialog(self)
        crop_dialog.setWindowTitle("Обведите кнопку")
        body = QVBoxLayout(crop_dialog)
        canvas = CropCanvas(frame)
        body.addWidget(canvas)
        body.addWidget(button("Сохранить", crop_dialog.accept))
        if crop_dialog.exec() != QDialog.DialogCode.Accepted:
            return
        try:
            stem = choice.currentData()
            if self.s.lang == "en" and choice.currentText() in ("play", "return_lobby", "claim", "claim_single"):
                stem += "_en"
            if self.s.lang in ("ru", "es", "pt") and choice.currentText() in ("play", "return_lobby", "claim"):
                QMessageBox.information(self, "Шаблон", "Для своих текстовых кнопок выберите English и добавьте шаблоны Play / Return / Claim с вашего экрана.")
                return
            write_image(self.store.root / "buttons" / (stem+".png"), crop_rect(frame, canvas.selected()))
            self.engine.submit("reload_buttons")
            self.store.event("Шаблон кнопки сохранён")
        except (ValueError, OSError) as error:
            QMessageBox.warning(self, "Шаблон", str(error))

    def edit_variants(self):
        dialog = QDialog(self)
        dialog.setWindowTitle("Варианты Sprite Gizmo")
        form = QFormLayout(dialog)
        edits, checks = {}, {}
        for key, name in self.s.variants.items():
            row = QHBoxLayout()
            edit = QLineEdit(name)
            check = QCheckBox("Избранное")
            check.setChecked(key in self.s.favorites)
            edits[key], checks[key] = edit, check
            row.addWidget(edit)
            row.addWidget(check)
            form.addRow(key.replace("gizmo_", "#"), row)
        form.addRow(button("Сохранить", dialog.accept, "Primary"))
        if dialog.exec() == QDialog.DialogCode.Accepted:
            values = {"variants": {key: edit.text().strip() or self.s.variants[key] for key, edit in edits.items()},
                      "favorites": [key for key, check in checks.items() if check.isChecked()]}
            self.engine.submit("configure", values)
            self.last_rewards = None

    def save_telegram(self):
        if self.demo:
            QMessageBox.information(self, "Демонстрация", "Telegram отключён в демонстрационном режиме")
            return
        try:
            user = int(self.user_input.text().strip())
            if user <= 0 or user > 2**53:
                raise ValueError("Укажите положительный числовой Telegram ID")
            token = self.token_input.text().strip()
            if token:
                save_token(token)
                self.token_input.clear()
            values = {key: widget.isChecked() for key, widget in self.telegram_checks.items()}
            values["telegram_user_id"] = user
            self.s.apply(values)
            self.s.save(self.store.root)
            self.bridge.stop(wait=False)
            self.telegram_detail.setText("Завершаем предыдущее соединение…")
            self._reconnect()
        except Exception as error:
            QMessageBox.warning(self, "Telegram", "Не удалось сохранить подключение. Проверьте Telegram ID и доступность системного хранилища токена.\n"+str(error).split("\n")[0][:180])

    def _reconnect(self):
        if any(thread.is_alive() for thread in self.bridge.threads):
            QTimer.singleShot(600, self._reconnect)
            return
        self.bridge.start()

    def test_telegram(self):
        if not self.demo and self.s.telegram_enabled and self.s.telegram_user_id:
            from .telegram import panel
            self.store.enqueue(self.s.telegram_user_id, "Sprite Pilot подключён. Это тестовое сообщение.", markup=panel())
            self.store.event("Тестовое сообщение добавлено в очередь Telegram")
        else:
            QMessageBox.information(self, "Telegram", "Сначала сохраните и включите подключение")

    def refresh_gallery(self, *args):
        while self.gallery_layout.count():
            item = self.gallery_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        rows = self.store.rewards(limit=200)
        selected = self.variant_filter.currentData()
        day = self.date_filter.currentIndex()
        now = datetime.now()
        count = 0
        for row in rows:
            if selected and row["variant"] != selected:
                continue
            stamp = datetime.fromtimestamp(row["at"])
            if day == 1 and stamp.date() != now.date() or day == 2 and time.time()-row["at"] > 7*86400:
                continue
            if self.match_filter.text().strip() not in row["match_id"]:
                continue
            tile, inner = card()
            image = read_image(Path(row["crop_path"]))
            if image is not None:
                view = QLabel()
                view.setAlignment(Qt.AlignmentFlag.AlignCenter)
                view.setPixmap(pixmap(image).scaled(180, 125, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
                inner.addWidget(view)
            inner.addWidget(label(self.engine.label(row["variant"]), wrap=True))
            inner.addWidget(label(f"{stamp:%d.%m · %H:%M:%S}\nМатч {row['match_id'][:10]}", "Muted"))
            inner.addWidget(button("Посмотреть", lambda checked=False, value=row: self.open_reward(value)))
            self.gallery_layout.addWidget(tile, count//3, count%3)
            count += 1
            if count >= 60:
                break
        if not count:
            self.gallery_layout.addWidget(label("Здесь появятся найденные награды.\nДобавьте образцы и запустите наблюдение.", "Muted", True), 0, 0)

    def open_reward(self, row):
        frame = read_image(Path(row["full_path"]))
        if frame is None:
            return
        dialog = QDialog(self)
        dialog.setWindowTitle(self.engine.label(row["variant"]))
        body = QVBoxLayout(dialog)
        view = QLabel()
        view.setPixmap(pixmap(frame).scaled(950, 530, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
        body.addWidget(view)
        body.addWidget(label("Совпадение с образцом: "+f"{row['confidence']:.0%}"+" · исправлено вручную"*bool(row["corrected"]), "Muted"))
        choice = QComboBox()
        choice.addItem("Не определён", "unknown")
        for key, name in self.s.variants.items():
            choice.addItem(name, key)
        choice.setCurrentIndex(max(0, choice.findData(row["variant"])))
        body.addWidget(choice)
        def correct():
            key = choice.currentData()
            if key != "unknown" and row["variant"] == "reward_screen":
                QMessageBox.information(dialog, "Образец", "Для экрана наград используйте «Добавить образец», чтобы выделить иконку отдельно.")
                return
            if key != "unknown":
                icon = read_image(Path(row["crop_path"]))
                if icon is not None:
                    write_image(self.store.root / "templates" / key / (uuid.uuid4().hex+".png"), icon)
            self.store.execute("UPDATE rewards SET variant=?,corrected=1 WHERE id=?", (key, row["id"]))
            self.engine.submit("reload_detector")
            self.last_rewards = None
            dialog.accept()
        body.addWidget(button("Уточнить вариант и сохранить образец", correct, "Primary"))
        body.addWidget(button("Закрыть", dialog.accept))
        dialog.exec()

    def refresh(self):
        snap = self.engine.snapshot()
        for index in range(self.variant_filter.count()):
            key = self.variant_filter.itemData(index)
            if key in self.s.variants:
                self.variant_filter.setItemText(index, self.s.variants[key])
        self.live_state.setText(snap["state"])
        self.live_note.setText(f"Режим {snap['mode']} · "+(snap["note"] or "Откройте игру и запустите цикл"))
        seconds = snap["elapsed"]
        self.stats["elapsed"].setText(f"{seconds//3600:02}:{seconds//60%60:02}:{seconds%60:02}")
        self.stats["loops"].setText(str(snap["loops"]))
        self.stats["rewards"].setText(str(snap["rewards"]))
        self.game_status.setText("Игра · "+snap["game"])
        connection = f"Telegram · {self.bridge.status} · в очереди {snap['pending']}"
        self.telegram_status.setText(connection)
        self.telegram_detail.setText(connection)
        self.detector_status.setText(f"Sprite Gizmo · образцы {snap['calibrated']}/5 · "+("области настроены" if snap["configured"] else "нужна настройка областей"))
        self.calibration_status.setText(snap["detector"]+f" · образцы {snap['calibrated']}/5")
        rewards = self.store.rewards(limit=200)
        signature = tuple((r["id"], r["variant"]) for r in rewards)
        if signature != self.last_rewards:
            self.last_rewards = signature
            self.refresh_gallery()
        events = self.store.query("SELECT * FROM events ORDER BY id DESC LIMIT 200")
        self.log_table.setRowCount(len(events))
        for index, event in enumerate(events):
            for col, value in enumerate((datetime.fromtimestamp(event["at"]).strftime("%d.%m %H:%M:%S"), event["level"], event["message"])):
                self.log_table.setItem(index, col, QTableWidgetItem(value))
        if events:
            self.last_event.setText("Последнее событие · "+events[0]["message"])

    def closeEvent(self, event):
        self.timer.stop()
        self.engine.close()
        self.bridge.stop()
        self.s.save(self.store.root)
        self.store.close()
        event.accept()

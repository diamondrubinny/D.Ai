# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Diamond Rubinny (d.Ai)
"""D.Ai Welcome window (docs/WELCOME.md).

  welcome ──► security ──► local AI & voice ──► privacy ──► summary ──► running ──► done

Nothing changes before the summary is confirmed. System changes go through
D.Ai Tune (polkit asks for the administrator password); downloads go through
the pinned model catalog. Long work runs in a background thread.
"""

from __future__ import annotations

import sys
from typing import Any, Callable

from PyQt6.QtCore import QSize, Qt, QThread
from PyQt6.QtGui import QFont, QFontDatabase, QGuiApplication, QIcon, QKeySequence, QShortcut
from PyQt6.QtWidgets import (
    QApplication, QButtonGroup, QCheckBox, QFrame, QGridLayout, QHBoxLayout, QLabel, QLayout, QProgressBar, QPushButton, QRadioButton,
    QScrollArea, QStackedWidget, QVBoxLayout, QWidget,
)

from dai_forge.cli import is_admin
from dai_forge.gui import ACCENT, ACCENT_2, ACCENT_SOFT, BG_900, BORDER, DANGER, LOGO, MUTED, OK_GREEN, STYLE as FORGE_STYLE
from dai_forge.gui import Bridge, Worker
from dai_tune import posture
from dai_tune.cli import describe
from dai_tune.context import Context, detect_lang

from dai_i18n import NATIVE_NAMES, SUPPORTED, is_rtl, pick, qt_direction
from dai_style import color

from . import __author__, __version__, core

APP_ID = "dai-welcome"
STEPS = ("welcome", "security", "ai", "privacy", "summary")

STYLE = FORGE_STYLE.replace("QWidget#Forge", "QWidget#Welcome") + f"""
QLabel#Dot {{ color: {color('dot')}; font-size: 12pt; }}  /* a step still to come: 3.8:1 (WCAG 1.4.11) */
QLabel#DotOn {{ color: {ACCENT_2}; font-size: 12pt; }}
QLabel#Hero {{ font-size: 24pt; font-weight: 700; }}
QRadioButton {{ spacing: 10px; font-weight: 600; }}
QRadioButton::indicator {{ width: 16px; height: 16px; border-radius: 10px; border: 2px solid {BORDER}; background: {BG_900}; }}
QRadioButton::indicator:checked {{ border: 2px solid {ACCENT};
    background: qradialgradient(cx:0.5, cy:0.5, radius:0.5, fx:0.5, fy:0.5, stop:0 {ACCENT}, stop:0.5 {ACCENT}, stop:0.56 {BG_900}); }}
QRadioButton:focus, QCheckBox:focus {{ color: {ACCENT_2}; }}
QProgressBar {{ background: {BG_900}; border: 1px solid {BORDER}; border-radius: 6px; height: 12px; text-align: center; }}
QProgressBar::chunk {{ border-radius: 5px; background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 {ACCENT}, stop:1 {ACCENT_2}); }}
"""

STRINGS = {
    "window": ("Welcome to D.Ai OS", "ברוכים הבאים ל־D.Ai OS"),
    "hero": ("Welcome to D.Ai OS", "ברוכים הבאים ל־D.Ai OS"),
    "intro": ("A fast, private and secure system with a built-in assistant that runs on this computer. "
              "A few short questions and you are ready — every step can be skipped and changed later.",
              "מערכת מהירה, פרטית ומאובטחת, עם עוזר מובנה שרץ על המחשב הזה. "
              "כמה שאלות קצרות ואתם מוכנים. אפשר לדלג על כל שלב ולשנות אותו אחר כך."),
    "start": ("Let's start ✦", "מתחילים ✦"),
    "language": ("Language", "שפה"),
    "language_note": ("D.Ai will speak this language from the next login. It is set up with the other changes, "
                      "at the end.", "D.Ai ידבר בשפה הזו מהכניסה הבאה. היא מוגדרת יחד עם שאר השינויים, בסוף."),
    "language_admin": ("Only an administrator can add a language to this computer.",
                       "רק מנהל המחשב יכול להוסיף שפה למחשב הזה."),
    "not_now": ("Not now", "לא עכשיו"),
    "back": ("Back", "חזרה"),
    "next": ("Next", "הבא"),
    "apply": ("Apply ✦", "אישור ✦"),
    "finish": ("Finish", "סיום"),
    "security_title": ("Security", "אבטחה"),
    "score": ("Security score now: {score}", "ציון האבטחה כרגע: {score}"),
    "recommended": ("Recommended", "מומלץ"),
    "recommended_d": ("Lock the screen after 5 minutes and keep automatic security updates on.",
                      "נעילת מסך אחרי 5 דקות, ועדכוני אבטחה אוטומטיים פעילים."),
    "strict": ("Strict", "מחמיר"),
    "strict_d": ("Recommended, plus blocking USB storage devices and turning Bluetooth off. "
                 "Good for computers that hold sensitive data.",
                 "כמו מומלץ, ובנוסף חסימת דיסק און קי וכיבוי Bluetooth. מתאים למחשבים עם מידע רגיש."),
    "keep": ("Keep as it is", "להשאיר כמו שזה"),
    "keep_d": ("No changes now. You can always type them in D.Ai Command, e.g. “lock the screen after 5 minutes”.",
               "בלי שינויים כרגע. תמיד אפשר לכתוב אותם ב־D.Ai Command, למשל „נעל מסך אחרי 5 דקות”."),
    "not_admin": ("Only an administrator can change system security. Ask the administrator of this computer.",
                  "רק מנהל המחשב יכול לשנות את אבטחת המערכת. פנו למנהל המחשב."),
    "ai_title": ("Diamond, the local AI, and voice", "Diamond, הבינה המקומית, וקול"),
    "ai_intro": ("Models run on this computer: your questions, code and voice never leave it. "
                 "Choose what to download now (once, verified by SHA-256 from Hugging Face). You can add more later.",
                 "המודלים רצים על המחשב הזה: השאלות, הקוד והקול שלכם לא יוצאים ממנו. "
                 "בחרו מה להוריד עכשיו (פעם אחת, מאומת ב־SHA-256, מ־Hugging Face). אפשר להוסיף עוד אחר כך."),
    "assistant": ("Assistant — answers questions and helps with the system", "עוזר — עונה על שאלות ועוזר במערכת"),
    "code": ("Coding — explains and edits code (D.Ai Code, D.Ai Forge)", "קוד — מסביר ועורך קוד (D.Ai Code, ‏D.Ai Forge)"),
    "voice": ("Voice typing — dictate in Hebrew and English (Super+H)", "הקלדה קולית — הכתבה בעברית ובאנגלית (Super+H)"),
    "size": ("{size} download · needs {ram} RAM", "הורדה של {size} · דורש {ram} RAM"),
    "included": ("included in the assistant on this computer", "כלול בעוזר במחשב הזה"),
    "installed": ("already installed", "כבר מותקן"),
    "low_ram": ("this computer has little memory; it may be slow", "למחשב הזה מעט זיכרון; זה עלול להיות איטי"),
    "ram_now": ("This computer: {ram} RAM", "המחשב הזה: {ram} RAM"),
    "privacy_title": ("Your privacy", "הפרטיות שלכם"),
    "privacy": [
        ("No telemetry, no ads, no account. D.Ai OS does not report anything about you.",
         "אין טלמטריה, אין פרסומות ואין חשבון. D.Ai OS לא מדווח עליכם כלום."),
        ("Diamond, the AI, runs on this computer. Prompts, files and code are not sent anywhere.",
         "Diamond, ה־AI, רץ על המחשב הזה. שאלות, קבצים וקוד לא נשלחים לשום מקום."),
        ("The microphone records only while you press the voice button; a notification is shown the whole time.",
         "המיקרופון מקליט רק כשלוחצים על כפתור הקול, ומוצגת הודעה כל הזמן."),
        ("Apps you build with D.Ai Forge run in a sandbox without internet or your files, unless you allow it.",
         "אפליקציות שבונים ב־D.Ai Forge רצות בארגז חול, בלי אינטרנט ובלי גישה לקבצים, אלא אם תאשרו."),
        ("Security updates from Debian install automatically; D.Ai updates only when you choose to.",
         "עדכוני אבטחה של Debian מותקנים אוטומטית. עדכוני D.Ai רק כשאתם בוחרים."),
        ("The disk is encrypted if you chose encryption during installation.",
         "הדיסק מוצפן, אם בחרתם בהצפנה בזמן ההתקנה."),
    ],
    "summary_title": ("Ready to set up", "מוכן להגדרה"),
    "changes": ("System changes (the administrator password will be requested):",
                "שינויים במערכת (תתבקש סיסמת מנהל):"),
    "downloads": ("Downloads ({total} in total):", "הורדות ({total} בסך הכל):"),
    "nothing": ("Nothing to change — you can finish.", "אין מה לשנות. אפשר לסיים."),
    "undo_note": ("Every system change can be undone: dai-tune undo", "אפשר לבטל כל שינוי במערכת: dai-tune undo"),
    "running": ("Setting up…", "מגדיר…"),
    "step_security": ("Security settings", "הגדרות אבטחה"),
    "step_system": ("Security settings and language", "הגדרות אבטחה ושפה"),
    "done_title": ("You're all set ✓", "הכל מוכן ✓"),
    "some_failed": ("Some steps did not complete. You can retry later from the menu (Welcome to D.Ai).",
                    "חלק מהשלבים לא הושלמו. אפשר לנסות שוב אחר כך מהתפריט (ברוכים הבאים)."),
    "shortcuts_title": ("Good to know", "כדאי לדעת"),
    "shortcuts": [
        ("Super+Space", "D.Ai Command: search, commands, “?” to ask the AI",
         "חיפוש, פקודות ו־„?” לשאלה ל־AI ‏(D.Ai Command)"),
        ("Super+B", "D.Ai Forge: “install antivirus”, “build an app for…”",
         "„תתקין אנטי וירוס”, „תבנה אפליקציה ל…” ‏(D.Ai Forge)"),
        ("Super+H", "Voice typing into any app", "הקלדה קולית לכל אפליקציה"),
        ("Super+L", "Lock the screen", "נעילת מסך"),
        ("Alt+Shift", "Switch Hebrew / English", "מעבר עברית / אנגלית"),
    ],
    "go": ("Start using D.Ai", "מתחילים להשתמש"),
    "retry": ("Try again", "לנסות שוב"),
    "error": ("Something went wrong", "משהו השתבש"),
}


def human_size(size: int) -> str:
    return f"{size / 2**30:.1f} GB" if size >= 2**30 else f"{size // 2**20} MB"


def ltr(text: str) -> str:
    """Keep a left-to-right run (a size, a model name) in order inside Hebrew text."""
    return f"\u202a{text}\u202c"


def _installed_models() -> set[str]:
    try:
        from dai_ai import models

        return {m.id for m in models.load_catalog().values() if m.installed}
    except Exception:  # no catalog: offer everything
        return set()


def _catalog() -> dict[str, Any]:
    try:
        from dai_ai import models

        return models.load_catalog()
    except Exception:
        return {}


class WelcomeWindow(QWidget):
    def __init__(self, lang: str, ctx: Context | None = None, ram: int | None = None,
                 installed: set[str] | None = None, catalog: dict | None = None,
                 admin: bool | None = None, runner: Callable | None = None) -> None:
        super().__init__(objectName="Welcome")
        self.lang = lang
        self.ctx = ctx or Context(lang=lang)
        self.admin = is_admin() if admin is None else admin
        self.catalog = _catalog() if catalog is None else catalog
        self.ram = core.ram_mb() if ram is None else ram
        self.options = core.ai_options(self.ram, _installed_models() if installed is None else installed)
        self.options = [o for o in self.options if o.model_id in self.catalog]
        self.level = "recommended" if self.admin else "keep"
        self.system_lang = lang  # the language of this session; another choice is set up at the end
        self.score, self.checks = posture.assess(self.ctx, lang)
        self.runner = runner or core.run_setup
        self.threads: list[tuple[QThread, Worker]] = []
        self.setup: core.Setup | None = None
        self.step = "welcome"

        self.setWindowTitle(self.t("window"))
        if LOGO.is_file():
            self.setWindowIcon(QIcon(str(LOGO)))
        self.resize(760, 640)
        self.setMinimumSize(QSize(540, 480))

        root = QVBoxLayout(self)
        root.setContentsMargins(28, 22, 28, 16)
        root.setSpacing(12)
        root.addLayout(self._header())
        self.pages = QStackedWidget()
        root.addWidget(self.pages, 1)
        nav = QFrame(objectName="Actions")
        self.nav = QHBoxLayout(nav)
        self.nav.setContentsMargins(0, 10, 0, 0)
        root.addWidget(nav)
        credit = QLabel(f"D.Ai Welcome {__version__} · {__author__}", objectName="Muted")
        credit.setStyleSheet("font-size: 9pt;")
        root.addWidget(credit)
        QShortcut(QKeySequence("Esc"), self, self._escape)
        self.show_step("welcome")

    # -- helpers ------------------------------------------------------------

    def t(self, key: str, **kwargs: Any) -> str:
        return pick(self.lang, *STRINGS[key]).format(**kwargs)

    def pick(self, pair: tuple[str, str]) -> str:
        return pick(self.lang, *pair)

    def _header(self) -> QHBoxLayout:
        row = QHBoxLayout()
        logo = QLabel("◆")
        logo.setStyleSheet(f"color: {ACCENT}; font-size: 28pt;")
        pixmap = QIcon(str(LOGO)).pixmap(QSize(44, 44)) if LOGO.is_file() else None
        if pixmap is not None and not pixmap.isNull():
            logo.setPixmap(pixmap)
        logo.setAccessibleName("D.Ai")
        row.addWidget(logo)
        row.addWidget(QLabel("D.Ai OS", objectName="Title"), 1)
        self.dots = []
        for index, name in enumerate(STEPS):
            dot = QLabel("●", objectName="Dot")
            dot.setAccessibleName(f"{index + 1}/{len(STEPS)}")
            self.dots.append(dot)
            row.addWidget(dot)
        return row

    def _page(self) -> QVBoxLayout:
        while self.pages.count():
            widget = self.pages.widget(0)
            self.pages.removeWidget(widget)
            widget.hide()  # gone now for screen readers too, not only after deleteLater
            widget.deleteLater()
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        inner = QWidget()
        layout = QVBoxLayout(inner)
        # Never squeeze content: when it does not fit, the page scrolls.
        layout.setSizeConstraint(QLayout.SizeConstraint.SetMinimumSize)
        layout.setContentsMargins(0, 4, 6, 4)
        layout.setSpacing(10)
        scroll.setWidget(inner)
        self.pages.addWidget(scroll)
        return layout

    def _card(self, layout: QVBoxLayout, name: str = "Card") -> QVBoxLayout:
        frame = QFrame(objectName=name)
        inner = QVBoxLayout(frame)
        inner.setContentsMargins(16, 12, 16, 12)
        inner.setSpacing(6)
        layout.addWidget(frame)
        return inner

    def _wrap(self, text: str, name: str = "") -> QLabel:
        # In Hebrew, a line that starts with a Latin word (a model, a shortcut)
        # must still read right to left: start it with a right-to-left mark.
        if is_rtl(self.lang):
            text = "\u200f" + text
        label = QLabel(text, objectName=name) if name else QLabel(text)
        label.setWordWrap(True)
        return label

    def _nav(self, *buttons: QPushButton, focus: QPushButton | None = None) -> None:
        while self.nav.count():
            item = self.nav.takeAt(0)
            if item.widget():
                item.widget().hide()
                item.widget().deleteLater()
        self.nav.addStretch(1)
        for button in buttons:
            button.setAccessibleName(button.text())
            self.nav.addWidget(button)
        target = focus or (buttons[-1] if buttons else None)
        if target is not None:
            target.setFocus()

    def _button(self, key: str, slot: Callable[[], None], primary: bool = False) -> QPushButton:
        button = QPushButton(self.t(key), objectName="Primary" if primary else "")
        button.clicked.connect(slot)
        return button

    def _title(self, layout: QVBoxLayout, key: str) -> None:
        layout.addWidget(QLabel(self.t(key), objectName="Hero"))

    def _escape(self) -> None:
        if not self.threads:
            self.not_now()

    # -- navigation ---------------------------------------------------------

    def show_step(self, step: str) -> None:
        self.step = step
        if step in STEPS:
            for index, dot in enumerate(self.dots):
                dot.setObjectName("DotOn" if index <= STEPS.index(step) else "Dot")
                dot.style().unpolish(dot)
                dot.style().polish(dot)
        getattr(self, f"page_{step}")()

    def go(self, delta: int) -> None:
        self.show_step(STEPS[max(0, min(len(STEPS) - 1, STEPS.index(self.step) + delta))])

    def not_now(self) -> None:
        core.mark_done(self.ctx.home, {"skipped": True})
        self.close()

    # -- pages --------------------------------------------------------------

    def page_welcome(self) -> None:
        layout = self._page()
        layout.addStretch(1)
        self._title(layout, "hero")
        layout.addWidget(self._wrap(self.t("intro")))
        layout.addStretch(1)
        self._languages(layout)
        layout.addStretch(1)
        self._nav(self._button("not_now", self.not_now), self._button("start", lambda: self.go(1), primary=True))

    def _languages(self, layout: QVBoxLayout) -> None:
        card = self._card(layout, "Step")
        card.addWidget(QLabel(self.t("language"), objectName="Section"))
        grid = QGridLayout()
        grid.setHorizontalSpacing(18)
        self.language_group = QButtonGroup(self)
        for index, code in enumerate(SUPPORTED):
            radio = QRadioButton(NATIVE_NAMES[code])
            radio.setLayoutDirection(qt_direction(code))  # each name reads in its own direction
            radio.setChecked(code == self.lang)
            radio.setEnabled(self.admin or code == self.system_lang)
            radio.toggled.connect(lambda on, c=code: on and self.choose_language(c))
            self.language_group.addButton(radio)
            grid.addWidget(radio, index // 4, index % 4)
        card.addLayout(grid)
        note = self.t("language_note") if self.admin else self.t("language_admin")
        card.addWidget(self._wrap(note, "Muted"))

    def choose_language(self, code: str) -> None:
        """Speak the chosen language at once; Tune sets it up for the next login with the other changes."""
        if code == self.lang:
            return
        self.lang = code
        self.ctx.lang = code
        self.score, self.checks = posture.assess(self.ctx, code)
        self.setLayoutDirection(qt_direction(code))
        self.setWindowTitle(self.t("window"))
        self.show_step("welcome")
        checked = self.language_group.checkedButton()
        if checked is not None:
            checked.setFocus()

    def page_security(self) -> None:
        layout = self._page()
        self._title(layout, "security_title")
        color = OK_GREEN if self.score >= 80 else ACCENT_SOFT
        score = QLabel(f"<span style='color:{color}; font-weight:700'>{self.t('score', score=ltr(f'{self.score}/100'))}</span>")
        layout.addWidget(score)
        card = self._card(layout)
        for check in self.checks:
            mark, mark_color = ("✓", OK_GREEN) if check.ok else ("✗", DANGER)
            detail = f" <span style='color:{MUTED}'>({ltr(check.detail)})</span>" if check.detail else ""
            card.addWidget(self._wrap(f"<span style='color:{mark_color}'>{mark}</span> {posture.title(check, self.lang)}{detail}"))
        self.level_group = QButtonGroup(self)
        for level in core.LEVELS:
            box = self._card(layout, "Step")
            radio = QRadioButton(self.t(level))
            radio.setAccessibleDescription(self.t(f"{level}_d"))
            radio.setChecked(level == self.level)
            radio.setEnabled(self.admin or level == "keep")
            radio.toggled.connect(lambda on, lv=level: on and setattr(self, "level", lv))
            self.level_group.addButton(radio)
            box.addWidget(radio)
            box.addWidget(self._wrap(self.t(f"{level}_d"), "Muted"))
        if not self.admin:
            layout.addWidget(self._wrap("🔑 " + self.t("not_admin"), "Muted"))
        layout.addStretch(1)
        self._nav(self._button("back", lambda: self.go(-1)), self._button("next", lambda: self.go(1), primary=True))

    def page_ai(self) -> None:
        layout = self._page()
        self._title(layout, "ai_title")
        layout.addWidget(self._wrap(self.t("ai_intro"), "Muted"))
        layout.addWidget(self._wrap(self.t("ram_now", ram=ltr(human_size(self.ram * 2**20))), "Muted"))
        self.boxes: list[tuple[QCheckBox, core.Option]] = []
        for option in self.options:
            model = self.catalog[option.model_id]
            card = self._card(layout, "Step")
            box = QCheckBox(self.t(option.key))
            box.setChecked(option.checked)
            box.setEnabled(option.enabled)
            box.toggled.connect(lambda on, o=option: setattr(o, "checked", on))
            info = self.t("size", size=ltr(human_size(model.size)), ram=ltr(human_size(model.ram_mb * 2**20)))
            if option.note:
                info += " · " + self.t(option.note)
            box.setAccessibleDescription(info)
            card.addWidget(box)
            card.addWidget(self._wrap(f"{ltr(model.name)} — {info}", "Muted"))
            self.boxes.append((box, option))
        layout.addStretch(1)
        self._nav(self._button("back", lambda: self.go(-1)), self._button("next", lambda: self.go(1), primary=True))

    def page_privacy(self) -> None:
        layout = self._page()
        self._title(layout, "privacy_title")
        card = self._card(layout)
        for pair in STRINGS["privacy"]:
            card.addWidget(self._wrap(f"<span style='color:{OK_GREEN}'>✓</span> {self.pick(pair)}"))
        layout.addStretch(1)
        self._nav(self._button("back", lambda: self.go(-1)), self._button("next", lambda: self.go(1), primary=True))

    def page_summary(self) -> None:
        layout = self._page()
        self._title(layout, "summary_title")
        try:
            language = core.language_sentence(self.lang, self.system_lang)
            plan = core.security_plan(self.level, self.ctx, language) if self.admin else None
        except ValueError as exc:
            return self.show_error(str(exc))
        self.setup = core.Setup(plan, core.chosen_models(self.options))
        if plan is not None:
            card = self._card(layout)
            card.addWidget(QLabel(self.t("changes"), objectName="Section"))
            for row in describe(plan, self.lang):
                card.addWidget(self._wrap(f"🛡 {row['summary']}"))
            card.addWidget(self._wrap(self.t("undo_note"), "Muted"))
        if self.setup.models:
            total = sum(self.catalog[m].size for m in self.setup.models)
            card = self._card(layout)
            card.addWidget(QLabel(self.t("downloads", total=ltr(human_size(total))), objectName="Section"))
            for model_id in self.setup.models:
                model = self.catalog[model_id]
                card.addWidget(self._wrap(f"⬇ {ltr(f'{model.name} ({human_size(model.size)})')}"))
        empty = plan is None and not self.setup.models
        if empty:
            layout.addWidget(self._wrap(self.t("nothing")))
        layout.addStretch(1)
        action = self._button("finish", self.finish_empty, True) if empty else self._button("apply", self.run, True)
        self._nav(self._button("back", lambda: self.go(-1)), action)

    def finish_empty(self) -> None:
        core.mark_done(self.ctx.home, {"level": self.level, "models": []})
        self.close()

    # -- running ------------------------------------------------------------

    def run(self) -> None:
        self.step = "running"
        layout = self._page()
        self._title(layout, "running")
        self.rows: dict[str, tuple[QLabel, QProgressBar | None]] = {}
        setup = self.setup or core.Setup()
        items = ([("security", self._system_step())] if setup.plan is not None else []) + \
                [(m, self.catalog[m].name) for m in setup.models]
        for key, text in items:
            card = self._card(layout, "Step")
            label = QLabel(f"• {text}")
            card.addWidget(label)
            bar = None
            if key != "security":
                bar = QProgressBar()
                bar.setRange(0, 100)
                bar.setAccessibleName(text)
                card.addWidget(bar)
            self.rows[key] = (label, bar)
        layout.addStretch(1)
        self._nav()

        def work(progress):
            return self.runner(setup, self.ctx, progress)

        self._start(work, self.done, self.on_progress)

    def on_progress(self, text: str) -> None:
        if text == "security":
            label, _ = self.rows.get("security", (None, None))
            if label is not None:
                label.setText("… " + label.text().lstrip("• "))
            return
        if text.startswith("model:"):
            _, model_id, percent = (text.split(":", 2) + ["", ""])[:3]
            _, bar = self.rows.get(model_id, (None, None))
            if bar is not None and percent.isdigit():
                bar.setValue(min(int(percent), 100))

    def _start(self, fn, done, progress) -> None:
        thread, worker = QThread(self), Worker(fn)
        bridge = Bridge(self, done, progress, lambda: self._forget(thread))
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.progress.connect(bridge.on_progress)
        worker.finished.connect(bridge.on_finished)
        worker.failed.connect(self.show_error)
        for signal in (worker.finished, worker.failed):
            signal.connect(thread.quit)
        thread.finished.connect(bridge.on_ended)
        self.threads.append((thread, worker))
        thread.start()

    def _forget(self, thread: QThread) -> None:
        self.threads = [(t, w) for t, w in self.threads if t is not thread]

    def done(self, results: list[core.Result]) -> None:
        self.step = "done"
        failed = [r for r in results if not r.ok]
        core.mark_done(self.ctx.home, {"level": self.level, "models": self.setup.models if self.setup else [],
                                       "failed": [r.label for r in failed]})
        layout = self._page()
        self._title(layout, "done_title")
        card = self._card(layout)
        for result in results:
            name = self._system_step() if result.label == "security" else self.catalog[result.label].name
            mark, color = ("✓", OK_GREEN) if result.ok else ("✗", DANGER)
            detail = f" — {result.detail}" if result.detail else ""
            card.addWidget(self._wrap(f"<span style='color:{color}'>{mark}</span> {name}{detail}"))
        if failed:
            layout.addWidget(self._wrap(self.t("some_failed"), "Muted"))
        self._shortcuts(layout)
        layout.addStretch(1)
        buttons = [self._button("retry", lambda: self.show_step("summary"))] if failed else []
        self._nav(*buttons, self._button("go", self.close, primary=True))

    def _system_step(self) -> str:
        plan = self.setup.plan if self.setup else None
        language = plan is not None and any(step.action == "session.language" for step in plan.steps)
        return self.t("step_system" if language else "step_security")

    def _shortcuts(self, layout: QVBoxLayout) -> None:
        card = self._card(layout)
        card.addWidget(QLabel(self.t("shortcuts_title"), objectName="Section"))
        for keys, en, he in STRINGS["shortcuts"]:
            text = pick(self.lang, en, he)
            card.addWidget(self._wrap(f"<b style='color:{ACCENT_2}'>{ltr(keys)}</b>&nbsp;&nbsp;{text}"))

    def show_error(self, text: str) -> None:
        self.step = "error"
        layout = self._page()
        card = self._card(layout, "Warn")
        card.addWidget(QLabel(f"<span style='font-size:15pt; font-weight:700; color:{DANGER}'>{self.t('error')}</span>"))
        card.addWidget(self._wrap(text))
        layout.addStretch(1)
        self._nav(self._button("back", lambda: self.show_step("summary")), self._button("not_now", self.close))


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv if argv is None else argv)
    if "--version" in argv:
        print(f"dai-welcome {__version__} — {__author__}")
        return 0
    lang = detect_lang()
    if "--first-run" in argv and not core.first_run_needed(Context().home):
        reason = "live session" if core.is_live() else "already done"
        print(f"dai-welcome: not needed ({reason})")
        return 0
    QGuiApplication.setDesktopFileName(APP_ID)
    app = QApplication(argv)
    app.setApplicationName("D.Ai Welcome")
    app.setApplicationVersion(__version__)
    app.setOrganizationName(__author__)
    app.setLayoutDirection(qt_direction(lang))
    if "Noto Sans" in QFontDatabase.families():
        app.setFont(QFont("Noto Sans", 11))
    app.setStyleSheet(STYLE)
    window = WelcomeWindow(lang, Context(lang=lang))
    window.show()
    return app.exec()


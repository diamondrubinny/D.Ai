# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Diamond Rubinny (d.Ai)
"""What Diamond knows about D.Ai OS itself (docs/AI.md §6): a small, curated list of facts in English and
Hebrew, chosen by keywords and put in front of the model when a question is about the system.

Deterministic and local: no index, no model call; a fact is text the project wrote, never something learned
from the person. Keep every fact true to the shortcuts in etc/skel/.config/labwc/rc.xml and the docs."""
from __future__ import annotations

import re
from dataclasses import dataclass

from dai_i18n import pick


@dataclass(frozen=True)
class Fact:
    keys: tuple[str, ...]   # lower-case words or phrases, English and Hebrew, that make the fact relevant
    en: str
    he: str

    def text(self, lang: str) -> str:
        return pick(lang, self.en, self.he)


RAW = (
    (("command", "bar", "search", "launch", "open", "start menu", "super+space", "שורת הפקודה", "חיפוש", "לפתוח", "התחל"),
         "The command bar opens with Super+Space (or the diamond button at the bottom left): type an app's name, a file to find, a calculation, or a question.",
         "שורת הפקודה נפתחת ב־Super+Space (או כפתור היהלום משמאל למטה): כותבים שם אפליקציה, קובץ לחיפוש, חישוב או שאלה."),
    (("question", "ask", "ai", "diamond", "assistant", "copilot", "שאלה", "לשאול", "בינה"),
         "A question to Diamond starts with ? in the command bar, or with dai-ai in a terminal. It runs on this computer; nothing is sent unless you set up an AI provider with your own key.",
         "שאלה ל־Diamond מתחילה ב־? בשורת הפקודה, או dai-ai בטרמינל. הוא רץ על המחשב הזה; שום דבר לא נשלח אלא אם הגדרתם ספק AI במפתח שלכם."),
    (("settings", "setting", "configure", "change", "tune", "lock after", "block usb", "firewall", "הגדרות", "להגדיר", "שינוי", "חסום", "נעל"),
         "Settings are sentences: ! in the command bar, or dai-tune, e.g. 'lock the screen after 5 minutes', 'block usb storage', 'open port 8080 to the local network'. The plan is shown first, applied through polkit, and dai-tune undo takes it back. D.Ai Settings (type 'settings') is the same catalog as a window.",
         "הגדרות הן משפטים: ! בשורת הפקודה, או dai-tune, למשל 'נעל מסך אחרי 5 דקות', 'חסום דיסק און קי', 'פתח פורט 8080 לרשת המקומית'. התוכנית מוצגת קודם, מוחלת דרך polkit, ו־dai-tune undo מבטל. D.Ai Settings (כותבים 'הגדרות') הוא אותו קטלוג כחלון."),
    (("install", "app", "software", "program", "store", "flathub", "forge", "recipe", "antivirus", "להתקין", "תוכנה", "אפליקציה", "חנות", "אנטי וירוס"),
         "Software comes from D.Ai Store (type 'store') or + in the command bar (D.Ai Forge): recipes such as antivirus, Syncthing, WireGuard, OnlyOffice, and Flathub apps. Forge can also build a small app from a description and runs it in a sandbox.",
         "תוכנות מגיעות מ־D.Ai Store (כותבים 'חנות') או + בשורת הפקודה (D.Ai Forge): מתכונים כמו אנטי וירוס, Syncthing, WireGuard, OnlyOffice, ואפליקציות Flathub. Forge גם בונה אפליקציה קטנה מתיאור ומריץ אותה בארגז חול."),
    (("lock", "lock screen", "win+l", "super+l", "נעילה", "נעל", "נועל", "לנעול", "נעילת"),
         "Super+L locks the screen. The automatic lock delay is a Tune sentence: 'lock the screen after 10 minutes'.",
         "Super+L נועל את המסך. זמן הנעילה האוטומטית הוא משפט של Tune: 'נעל מסך אחרי 10 דקות'."),
    (("language", "keyboard", "layout", "hebrew", "english", "alt+shift", "switch", "wrong layout", "gibberish", "שפה", "מקלדת", "פריסה", "עברית", "אנגלית", "ג'יבריש"),
         "Alt+Shift switches the keyboard language. Text typed in the wrong layout is fixed with the Pause key or Super+Alt+L. The interface language changes with a Tune sentence such as 'language russian', from the next login.",
         "Alt+Shift מחליף שפת מקלדת. טקסט שהוקלד בפריסה הלא נכונה מתוקן במקש Pause או Super+Alt+L. שפת הממשק משתנה במשפט Tune כמו 'שפה רוסית', מהכניסה הבאה."),
    (("clipboard", "copy", "paste", "history", "super+v", "לוח", "העתק", "הדבק", "היסטוריה"),
         "Super+V opens D.Ai Clip, the clipboard history. Passwords, tokens and card numbers are never kept; it clears after 12 hours.",
         "Super+V פותח את D.Ai Clip, היסטוריית ההעתקות. סיסמאות, טוקנים ומספרי כרטיס לא נשמרים; היא מתנקה אחרי 12 שעות."),
    (("quick", "wifi", "wi-fi", "volume", "battery", "do not disturb", "super+n", "tray", "ווייפיי", "עוצמה", "סוללה", "נא לא להפריע"),
         "Super+N opens D.Ai Quick next to the clock: Wi-Fi, do not disturb, battery saver, volume, the security score and who used the camera.",
         "Super+N פותח את D.Ai Quick ליד השעון: Wi-Fi, נא לא להפריע, חיסכון בסוללה, עוצמה, ציון האבטחה ומי השתמש במצלמה."),
    (("crash", "crashed", "failed", "broken", "not working", "error", "heal", "super+f1", "קרס", "נפל", "לא עובד", "שגיאה", "תקלה"),
         "When a program crashes or a service fails, D.Ai Heal shows a notification and explains it; Super+F1 opens it. Fixes come from a closed list and happen only when you click.",
         "כשתוכנה קורסת או שירות נכשל, D.Ai Heal מציג התראה ומסביר; Super+F1 פותח אותו. תיקונים באים מרשימה סגורה וקורים רק בלחיצה."),
    (("slow", "why is", "task manager", "processes", "memory", "cpu", "mom", "ctrl+shift+esc", "disk full", "doctor", "איטי", "למה", "מנהל משימות", "זיכרון", "דיסק מלא"),
         "'Why is the computer slow?' in the command bar runs D.Ai Doctor (also what fills the disk and battery health). Ctrl+Shift+Esc opens MOM, the task manager that shows apps, not processes, and guards against runaway programs.",
         "'למה המחשב איטי?' בשורת הפקודה מריץ את D.Ai Doctor (גם מה ממלא את הדיסק ובריאות הסוללה). Ctrl+Shift+Esc פותח את MOM, מנהל המשימות שמציג אפליקציות ולא תהליכים ושומר מתוכנות משתוללות."),
    (("terminal", "console", "shell", "command line", "super+enter", "טרמינל", "מסוף"),
         "Super+Enter opens a terminal (qterminal). Super+E opens the file manager.",
         "Super+Enter פותח טרמינל (qterminal). Super+E פותח את מנהל הקבצים."),
    (("files", "file manager", "explorer", "folder", "find", "search file", "pdf", "document", "קבצים", "תיקייה", "מנהל קבצים", "למצוא", "מסמך"),
         "Super+E opens the file manager. D.Ai Find works from the command bar in words: 'the PDF I downloaded last week', 'photos from today', or by content: 'the file about the lease'.",
         "Super+E פותח את מנהל הקבצים. D.Ai Find עובד משורת הפקודה במילים: 'ה־PDF שהורדתי בשבוע שעבר', 'תמונות מהיום', או לפי תוכן: 'הקובץ על חוזה השכירות'."),
    (("screenshot", "print screen", "capture", "screen shot", "צילום מסך", "צלם מסך"),
         "Print takes a screenshot of the whole screen and Shift+Print of an area; both go to ~/Pictures/Screenshots and the clipboard.",
         "Print מצלם את כל המסך ו־Shift+Print אזור; שניהם נשמרים ב־~/Pictures/Screenshots ובלוח."),
    (("ocr", "text from the screen", "copy text", "image text", "super+shift+t", "טקסט מהמסך", "טקסט מתמונה"),
         "Super+Shift+T (D.Ai OCR) copies the text in an area of the screen, read on this computer in eight languages.",
         "Super+Shift+T (D.Ai OCR) מעתיק את הטקסט שבאזור של המסך, נקרא על המחשב הזה בשמונה שפות."),
    (("explain", "what is this", "what am i looking at", "understand", "super+shift+e", "מה זה", "להסביר", "הסבר"),
         "Super+Shift+E (D.Ai Explain) reads the screen and Diamond explains it in your language, with at most one suggested Tune step that opens in the command bar for approval.",
         "Super+Shift+E (D.Ai מסביר) קורא את המסך ו־Diamond מסביר בשפה שלכם, עם לכל היותר הצעה אחת של Tune שנפתחת בשורת הפקודה לאישור."),
    (("captions", "subtitles", "hearing", "super+alt+c", "כתוביות", "שמיעה"),
         "Super+Alt+C shows live captions for whatever the computer plays, on the computer, nothing saved.",
         "Super+Alt+C מציג כתוביות חיות למה שהמחשב משמיע, על המחשב, בלי שמירה."),
    (("voice", "dictate", "dictation", "speak", "microphone", "super+h", "דיבור", "הכתבה", "מיקרופון", "קול"),
         "Super+H dictates into the focused window and Super+Shift+Space speaks a command, both with local Whisper; nothing is recorded or sent.",
         "Super+H מכתיב לחלון הפעיל ו־Super+Shift+Space אומר פקודה, שניהם עם Whisper מקומי; שום דבר לא מוקלט ולא נשלח."),
    (("accessibility", "screen reader", "orca", "magnifier", "zoom", "on-screen keyboard", "large text", "contrast", "night light", "נגישות", "קורא מסך", "זכוכית מגדלת", "הגדלה", "מקלדת על המסך", "ניגודיות", "תאורת לילה"),
         "Accessibility: Super+Alt+S starts the Orca screen reader, Super+= and Super+- zoom, Super+Alt+M toggles the magnifier, Super+Alt+K the on-screen keyboard, Super+Alt+N the night light; 'high contrast' is a Tune sentence.",
         "נגישות: Super+Alt+S מפעיל את קורא המסך Orca, Super+= ו־Super+- מגדילים, Super+Alt+M זכוכית מגדלת, Super+Alt+K מקלדת על המסך, Super+Alt+N תאורת לילה; 'ניגודיות גבוהה' הוא משפט של Tune."),
    (("window", "snap", "tile", "half", "third", "arrange", "windows side by side", "חלון", "חלונות", "לסדר", "חצי"),
         "Windows snap with Super+Shift+Arrow (thirds) and Super+Ctrl+Arrow (quarters); Super+Shift+Down unsnaps.",
         "חלונות נצמדים עם Super+Shift+חץ (שלישים) ו־Super+Ctrl+חץ (רבעים); Super+Shift+למטה משחרר."),
    (("undo", "revert", "go back", "rescue", "update broke", "בטל", "לבטל", "לחזור", "העדכון"),
         "Every change made with Tune, Forge, Settings, Store or Way is in one journal: dai-tune undo takes the last one back. 'Undo the last update' goes back to the snapshot before it (Btrfs); if the computer no longer starts, D.Ai Rescue from the USB stick does the same.",
         "כל שינוי שנעשה עם Tune, Forge, Settings, Store או Way נמצא ביומן אחד: dai-tune undo מבטל את האחרון. 'בטל את העדכון האחרון' חוזר לתמונת המצב שלפניו (Btrfs); אם המחשב לא עולה, D.Ai Rescue מהדיסק און קי עושה אותו דבר."),
    (("backup", "restore", "external drive", "גיבוי", "שחזור", "לגבות"),
         "D.Ai Backup makes encrypted automatic backups (restic) to an external drive; the recovery key is shown once and kept in ~/.config/dai/backup.key.",
         "D.Ai Backup מגבה אוטומטית ומוצפן (restic) לדיסק חיצוני; מפתח השחזור מוצג פעם אחת ונשמר ב־~/.config/dai/backup.key."),
    (("windows", "move", "migrate", "bookmarks", "outlook", "from windows", "מווינדוס", "להעביר", "מעבר"),
         "D.Ai Move brings files and bookmarks over from a Windows disk; J imports Outlook PST mail; D.Ai VM runs Windows in a window with your own installation media and key.",
         "D.Ai Move מעביר קבצים וסימניות מדיסק של Windows; J מייבא דואר מ־Outlook PST; D.Ai VM מריץ Windows בחלון עם מדיית ההתקנה והמפתח שלכם."),
    (("mail", "email", "j", "gmail", "imap", "encrypted mail", "pgp", "דואר", "מייל", "אימייל"),
         "J is the mail client: it finds the server settings by itself, supports OpenPGP and S/MIME, blocks tracking pixels, and Diamond can summarize or draft a reply.",
         "J הוא תוכנת הדואר: מוצא את הגדרות השרת לבד, תומך ב־OpenPGP ו־S/MIME, חוסם פיקסלי מעקב, ו־Diamond יכול לסכם או לנסח תשובה."),
    (("browser", "ruby", "firefox", "internet", "web", "ad", "tracking", "דפדפן", "אינטרנט", "פרסומות"),
         "Ruby is the browser: Firefox ESR with strict tracking protection, uBlock Origin and containers; its telemetry is off.",
         "Ruby הוא הדפדפן: Firefox ESR עם הגנת מעקב מחמירה, uBlock Origin ומכולות; הטלמטריה שלו כבויה."),
    (("chat", "message", "messages", "send a picture", "tor", "diamond chat", "צ'אט", "הודעה", "הודעות", "לשלוח תמונה"),
         "Diamond Chat sends encrypted messages and pictures between D.Ai computers with no server and no account, on the local network or through Tor; pairing uses a code and six symbols.",
         "Diamond Chat שולח הודעות ותמונות מוצפנות בין מחשבי D.Ai בלי שרת ובלי חשבון, ברשת המקומית או דרך Tor; הצימוד נעשה בקוד ובשישה סמלים."),
    (("privacy", "camera", "microphone", "who used", "telemetry", "data", "sent", "פרטיות", "מצלמה", "מיקרופון", "מי השתמש", "נשלח"),
         "D.Ai OS sends no telemetry. The privacy indicator shows who uses the microphone and camera now, with a local 30-day log (dai-privacy). AI, dictation and search run on the computer.",
         "D.Ai OS לא שולחת טלמטריה. מחוון הפרטיות מראה מי משתמש עכשיו במיקרופון ובמצלמה, עם יומן מקומי של 30 יום (dai-privacy). AI, הכתבה וחיפוש רצים על המחשב."),
    (("provider", "openai", "anthropic", "gemini", "api key", "cloud ai", "chatgpt", "claude", "ספק", "מפתח api"),
         "An external AI provider is optional: dai-models provider add NAME, provider key, then provider use with a typed consent; speech always stays local, and 'answer on this computer' goes back.",
         "ספק AI חיצוני הוא אופציונלי: dai-models provider add NAME, ‏provider key, ואז provider use עם הסכמה מוקלדת; דיבור תמיד נשאר מקומי, ו'תענה במחשב הזה' מחזיר."),
    (("update", "updates", "upgrade", "security updates", "apt", "עדכון", "עדכונים", "לעדכן"),
         "Security updates from Debian install automatically; D.Ai updates come from a signed repository. 'Enable automatic updates' and 'snapshots before updates' are Tune sentences.",
         "עדכוני אבטחה מ־Debian מותקנים אוטומטית; עדכוני D.Ai מגיעים ממאגר חתום. 'הפעל עדכונים אוטומטיים' ו'צילום מצב לפני כל עדכון' הם משפטים של Tune."),
    (("focus", "concentrate", "no interruptions", "pomodoro", "game mode", "פוקוס", "ריכוז", "בלי הפרעות", "מצב משחק"),
         "'Focus for 25 minutes' hides pop-ups and warms the light until the timer ends; 'game mode' does the same for a game.",
         "'פוקוס ל־25 דקות' מסתיר חלונות קופצים ומחמם את האור עד שהטיימר נגמר; 'מצב משחק' עושה אותו דבר למשחק."),
    (("offline", "no internet", "block app", "network for", "memory saver", "low memory", "ram", "בלי אינטרנט", "לא יוצא לאינטרנט", "חיסכון בזיכרון"),
         "'firefox does not go online' runs an app without network (bubblewrap, no root); 'memory saver on' uses compressed swap first and the small Diamond model.",
         "'פיירפוקס לא יוצא לאינטרנט' מריץ אפליקציה בלי רשת (bubblewrap, בלי root); 'מצב חיסכון בזיכרון' משתמש קודם בהחלפה דחוסה ובמודל הקטן של Diamond."),
    (("way", "dway", "whole computer", "classroom", "same setup", "export", "דרך היהלום", "אותה הגדרה", "ייצוא"),
         "Diamond's Way describes a whole computer in one .dway file (Tune sentences, recipes, timers, files): dai-way check, plan, apply, undo, export; a .dway in /etc/dai/policy.d is an organization policy.",
         "דרך היהלום מתארת מחשב שלם בקובץ .dway אחד (משפטי Tune, מתכונים, טיימרים, קבצים): dai-way check, plan, apply, undo, export; קובץ .dway ב־/etc/dai/policy.d הוא מדיניות ארגונית."),
    (("help", "manual", "documentation", "docs", "guide", "tutorial", "עזרה", "מדריך", "תיעוד", "הדרכה"),
         "The guides are in /usr/share/doc/dai (docs/BASICS.md, docs/FROM-WINDOWS.md) and at github.com/diamondrubinny/D.Ai; D.Ai Welcome (type 'welcome') repeats the first-run tour.",
         "המדריכים נמצאים ב־/usr/share/doc/dai (docs/BASICS.md, docs/FROM-WINDOWS.md) וב־github.com/diamondrubinny/D.Ai; ‏D.Ai Welcome (כותבים 'welcome') חוזר על הסיור הראשון."),
)
FACTS: tuple[Fact, ...] = tuple(Fact(keys, en, he) for keys, en, he in RAW)  # i18n: en/he only; other languages read English

def _hit(key: str, text: str) -> bool:
    """A keyword as a whole word; a Hebrew key may carry a prefix letter (ה, ו, ב, ל, מ, ש, כ) and a suffix."""
    if key.isascii():
        return re.search(r"(?<![a-z0-9])" + re.escape(key) + r"(?![a-z0-9])", text) is not None
    return re.search(r"(?<![\u05d0-\u05ea])[\u05d0-\u05ea]{0,2}" + re.escape(key), text) is not None


def relevant(question: str, lang: str, limit: int = 5) -> list[str]:
    """The facts whose keywords appear in the question, best first; [] when none do."""
    lowered = " " + re.sub(r"\s+", " ", question.casefold()) + " "
    scored = []
    for fact in FACTS:
        hits = [key for key in fact.keys if _hit(key, lowered)]
        if hits:
            scored.append((len(max(hits, key=len)) + len(hits), fact))
    scored.sort(key=lambda pair: -pair[0])
    return [fact.text(lang) for _, fact in scored[:limit]]


def briefing(question: str, lang: str) -> str:
    """A system-prompt section with the relevant facts, or "" when the question is not about the system."""
    facts = relevant(question, lang)
    if not facts:
        return ""
    return ("Facts about D.Ai OS, the system you are part of; rely on them when the question is about it, and never "
            "invent shortcuts or commands beyond them:\n" + "\n".join("- " + fact for fact in facts))

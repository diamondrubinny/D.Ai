# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Diamond Rubinny (d.Ai)
"""Turn "the PDF I downloaded last week" / "התמונות מאתמול" into search criteria.

Rule-based and local: no AI is needed for the common phrasings, so it is
instant and predictable. Words that are not a type, a time or a place are
matched against file names.
"""

from __future__ import annotations

import calendar
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Callable

# Hebrew attaches prepositions and "that/the/and" to the next word.
HE_PREFIX = "והבלמשכ"

KINDS: dict[str, tuple[str, ...]] = {
    "pdf": (".pdf",),
    "document": (".pdf", ".doc", ".docx", ".odt", ".rtf", ".txt", ".md"),
    "spreadsheet": (".xls", ".xlsx", ".ods", ".csv"),
    "presentation": (".ppt", ".pptx", ".odp", ".key"),
    "image": (".jpg", ".jpeg", ".png", ".gif", ".webp", ".heic", ".bmp", ".svg", ".tif", ".tiff"),
    "video": (".mp4", ".mkv", ".webm", ".mov", ".avi", ".m4v"),
    "audio": (".mp3", ".ogg", ".opus", ".flac", ".wav", ".m4a", ".aac"),
    "archive": (".zip", ".tar", ".gz", ".tgz", ".xz", ".7z", ".rar", ".bz2"),
}

KIND_WORDS: dict[str, str] = {
    # English
    "pdf": "pdf", "pdfs": "pdf",
    "document": "document", "documents": "document", "doc": "document", "docs": "document", "docx": "document",
    "word": "document", "text": "document",
    "spreadsheet": "spreadsheet", "spreadsheets": "spreadsheet", "excel": "spreadsheet", "xlsx": "spreadsheet",
    "csv": "spreadsheet", "sheet": "spreadsheet", "sheets": "spreadsheet",
    "presentation": "presentation", "presentations": "presentation", "slides": "presentation",
    "powerpoint": "presentation", "pptx": "presentation",
    "image": "image", "images": "image", "photo": "image", "photos": "image", "picture": "image",
    "pictures": "image", "screenshot": "image", "screenshots": "image", "jpg": "image", "png": "image",
    "video": "video", "videos": "video", "movie": "video", "movies": "video", "mp4": "video",
    "music": "audio", "song": "audio", "songs": "audio", "audio": "audio", "mp3": "audio",
    "recording": "audio", "recordings": "audio",
    "zip": "archive", "archive": "archive", "archives": "archive",
    # Hebrew (without prefixes; see _bare)
    "מסמך": "document", "מסמכים": "document", "וורד": "document",
    "גיליון": "spreadsheet", "גליון": "spreadsheet", "אקסל": "spreadsheet", "טבלה": "spreadsheet",
    "מצגת": "presentation", "מצגות": "presentation",
    "תמונה": "image", "תמונות": "image", "צילום": "image", "צילומים": "image",
    "סרטון": "video", "סרטונים": "video", "וידאו": "video", "סרט": "video",
    "שיר": "audio", "שירים": "audio", "מוזיקה": "audio", "הקלטה": "audio", "הקלטות": "audio",
    "ארכיון": "archive", "זיפ": "archive",
}
KIND_PHRASES = [
    (r"פי\s*די\s*אף", "pdf"),
    (r"צילומי\s+מסך|צילום\s+מסך|screen\s*shots?", "image"),
    (r"קובץ\s+דחוס|קבצים\s+דחוסים", "archive"),
]

FOLDERS = ("downloads", "documents", "desktop", "pictures", "music", "videos")
FOLDER_PATTERNS = [
    (r"\bdownload(?:s|ed)?\b|הורד(?:ות|תי|נו|ת|ה)?\b", "downloads"),
    (r"\bdesktop\b|שולחן\s+העבודה", "desktop"),
    (r"(?:folder|תיקי(?:י)?ת)\s+(?:ה)?(?:documents|מסמכים)", "documents"),
]

MONTHS_EN = {name.lower(): i for i, name in enumerate(calendar.month_name) if name}
MONTHS_HE = {name: i for i, name in enumerate(
    ["", "ינואר", "פברואר", "מרץ", "אפריל", "מאי", "יוני", "יולי", "אוגוסט", "ספטמבר", "אוקטובר", "נובמבר", "דצמבר"]) if name}

STOP = {
    "find", "search", "show", "where", "is", "are", "the", "a", "an", "my", "i", "me", "that", "which", "from",
    "in", "on", "of", "for", "with", "called", "named", "about", "file", "files", "folder", "last", "this",
    "ago", "days", "day", "week", "month", "year", "all", "any", "some", "got", "saved", "made", "took",
    "מצא", "תמצא", "למצוא", "חפש", "תחפש", "לחפש", "איפה", "את", "של", "שלי", "קובץ", "קבצים", "אני", "לי",
    "תראה", "הראה", "להראות", "עם", "על", "בשם", "שנקרא", "שנקראת", "כל", "יש", "הוא", "היא", "זה", "אותו",
    "שמרתי", "צילמתי", "קיבלתי", "תיקייה", "תיקיית", "ימים", "יום", "שבוע", "חודש", "שנה", "לפני",
}
TRIGGERS = re.compile(r"^\s*(?:find|search(?:\s+for)?|where(?:'s|\s+is|\s+are)?|show\s+me|"
                      r"מצא|תמצא|חפש|תחפש|איפה|תראה\s+לי|הראה\s+לי)\b", re.IGNORECASE)


@dataclass
class Query:
    text: str
    kinds: set[str] = field(default_factory=set)
    since: datetime | None = None
    until: datetime | None = None
    folders: list[str] = field(default_factory=list)
    words: list[str] = field(default_factory=list)
    time_label: str = ""

    @property
    def extensions(self) -> set[str]:
        return {ext for kind in self.kinds for ext in KINDS[kind]}

    @property
    def specific(self) -> bool:
        """Enough to search without listing every file in the home folder."""
        return bool(self.kinds or self.since or self.words or self.folders)


def is_find_request(text: str) -> bool:
    return bool(TRIGGERS.match(text))


def _bare(token: str) -> list[str]:
    """The token and its forms without Hebrew prefixes (שהורדתי → הורדתי, ורדתי…)."""
    forms = [token]
    while forms[-1] and forms[-1][0] in HE_PREFIX and len(forms[-1]) > 2:
        forms.append(forms[-1][1:])
    return forms


def _start_of_day(moment: datetime) -> datetime:
    return moment.replace(hour=0, minute=0, second=0, microsecond=0)


def _week_start(moment: datetime, hebrew: bool) -> datetime:
    # Israel starts the week on Sunday; ISO weeks start on Monday.
    offset = (moment.weekday() + 1) % 7 if hebrew else moment.weekday()
    return _start_of_day(moment) - timedelta(days=offset)


def _month_start(year: int, month: int) -> datetime:
    return datetime(year, month, 1)


def _next_month(start: datetime) -> datetime:
    return datetime(start.year + start.month // 12, start.month % 12 + 1, 1)


def _time_window(text: str, now: datetime, hebrew: bool) -> tuple[datetime | None, datetime | None, str, str]:
    """(since, until, label, text without the time phrase)."""
    today = _start_of_day(now)
    rules: list[tuple[str, Callable]] = [
        (r"(?:last|past)\s+(\d{1,3})\s+days|(?:ב)?[־-]?\s*(\d{1,3})\s+(?:ה)?ימים\s+(?:ה)?אחרונים",
         lambda m: (today - timedelta(days=int(m.group(1) or m.group(2)) - 1), None, "last_n_days")),
        (r"(\d{1,3})\s+days?\s+ago|לפני\s+(\d{1,3})\s+ימים",
         lambda m: (today - timedelta(days=int(m.group(1) or m.group(2))),
                    today - timedelta(days=int(m.group(1) or m.group(2)) - 1), "days_ago")),
        (r"\byesterday\b|[מב]?אתמול", lambda m: (today - timedelta(days=1), today, "yesterday")),
        (r"\btoday\b|[מב]?היום", lambda m: (today, None, "today")),
        (r"\blast\s+week\b|[במ]?(?:ה)?שבוע\s+(?:ה)?שעבר",
         lambda m: (_week_start(now, hebrew) - timedelta(days=7), _week_start(now, hebrew), "last_week")),
        (r"\bthis\s+week\b|[במ]?השבוע", lambda m: (_week_start(now, hebrew), None, "this_week")),
        (r"\blast\s+month\b|[במ]?(?:ה)?חודש\s+(?:ה)?שעבר",
         lambda m: (_month_start(*((now.year - 1, 12) if now.month == 1 else (now.year, now.month - 1))),
                    _month_start(now.year, now.month), "last_month")),
        (r"\bthis\s+month\b|[במ]?החודש", lambda m: (_month_start(now.year, now.month), None, "this_month")),
        (r"\blast\s+year\b|[במ]?(?:ה)?שנה\s+(?:ה)?שעברה",
         lambda m: (datetime(now.year - 1, 1, 1), datetime(now.year, 1, 1), "last_year")),
        (r"\bthis\s+year\b|[במ]?השנה", lambda m: (datetime(now.year, 1, 1), None, "this_year")),
    ]
    for pattern, window in rules:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            since, until, label = window(match)
            return since, until, label, text[:match.start()] + " " + text[match.end():]
    # A month name: its most recent occurrence that is not in the future.
    for token in re.findall(r"[\w֐-׿]+", text):
        for form in _bare(token.lower()):
            month = MONTHS_EN.get(form) or MONTHS_HE.get(form)
            if month:
                year = now.year if month <= now.month else now.year - 1
                start = _month_start(year, month)
                rest = re.sub(rf"\b{re.escape(token)}\b", " ", text, count=1)
                return start, _next_month(start), f"month:{month}", rest
    return None, None, "", text


def parse(text: str, now: datetime | None = None, lang: str = "en") -> Query:
    now = now or datetime.now()
    hebrew = lang == "he" or bool(re.search(r"[֐-׿]", text))  # i18n: ok (Hebrew search words)
    query = Query(text)
    # "ה-PDF" / "ה־PDF": a Hebrew prefix joined with a hyphen or maqaf.
    rest = re.sub(r"(?<=[\u0590-\u05FF])[-\u05BE](?=\w)", " ", TRIGGERS.sub(" ", text, count=1))
    query.since, query.until, query.time_label, rest = _time_window(rest, now, hebrew)

    for pattern, kind in KIND_PHRASES:
        if re.search(pattern, rest, re.IGNORECASE):
            query.kinds.add(kind)
            rest = re.sub(pattern, " ", rest, flags=re.IGNORECASE)
    for pattern, folder in FOLDER_PATTERNS:
        if re.search(pattern, rest, re.IGNORECASE):
            if folder not in query.folders:
                query.folders.append(folder)
            rest = re.sub(pattern, " ", rest, flags=re.IGNORECASE)

    for token in re.findall(r"[\w֐-׿.+-]+", rest.lower()):
        token = token.strip(".-+")
        if not token:
            continue
        forms = _bare(token)
        kind = next((KIND_WORDS[f] for f in forms if f in KIND_WORDS), None)
        if kind:
            query.kinds.add(kind)
        elif not any(f in STOP for f in forms) and len(token) > 1:
            query.words.append(token)
    # "a document" includes PDFs; asking for PDFs specifically narrows it.
    if "pdf" in query.kinds and "document" in query.kinds:
        query.kinds.discard("document")
    return query


# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Diamond Rubinny (d.Ai)
"""J's words (docs/MAIL.md §6): short, plain, the same in both languages."""

from __future__ import annotations

from dai_i18n import pick, text, ui_lang

STRINGS = {
    "title": ("J – Mail", "J – דואר"),
    "all_inboxes": ("All inboxes", "כל תיבות הדואר"),
    "inbox": ("Inbox", "דואר נכנס"),
    "sent": ("Sent", "נשלח"),
    "drafts": ("Drafts", "טיוטות"),
    "trash": ("Trash", "אשפה"),
    "junk": ("Spam", "ספאם"),
    "archive": ("Archive", "ארכיון"),
    "all": ("All mail", "כל הדואר"),
    "folders": ("Folders", "תיקיות"),
    "messages": ("Messages", "הודעות"),
    "reader": ("Message", "הודעה"),
    "col_from": ("From", "מאת"),
    "col_subject": ("Subject", "נושא"),
    "col_date": ("Date", "תאריך"),
    "no_subject": ("(no subject)", "(בלי נושא)"),
    "row": ("{sender}, {subject}, {date}", "{sender}, {subject}, {date}"),
    "unread": ("unread", "לא נקראה"),
    "flagged": ("starred", "מסומנת בכוכב"),
    "new": ("New message", "הודעה חדשה"),
    "reply": ("Reply", "תשובה"),
    "reply_all": ("Reply all", "תשובה לכולם"),
    "forward": ("Forward", "העברה"),
    "delete": ("Delete", "מחיקה"),
    "mark_unread": ("Mark unread", "סימון כלא נקראה"),
    "refresh": ("Check mail", "בדיקת דואר"),
    "add_account": ("Add account", "הוספת חשבון"),
    "remove_account": ("Remove account", "הסרת חשבון"),
    "empty_title": ("Your mail, in one calm place", "הדואר שלכם, במקום אחד ורגוע"),
    "empty_body": ("Add your e-mail address; J finds the settings by itself.",
                   "הוסיפו את כתובת המייל שלכם, ו־J ימצא את ההגדרות בעצמו."),
    "empty_folder": ("No messages here.", "אין כאן הודעות."),
    "pick_message": ("Choose a message to read it.", "בחרו הודעה כדי לקרוא אותה."),
    "loading": ("Loading…", "טוען…"),
    "checking": ("Checking mail…", "בודק דואר…"),
    "arrived": ("{count} new message(s)", "הודעות חדשות: {count}"),
    "up_to_date": ("Up to date", "הכל מעודכן"),
    "image": ("image blocked", "תמונה חסומה"),
    "images_blocked": ("{count} image(s) blocked, to stop tracking.", "{count} תמונות נחסמו, כדי למנוע מעקב."),
    "attachments": ("Attachments: {names}", "קבצים מצורפים: {names}"),
    "to_line": ("To: {to}", "אל: {to}"),
    "from_line": ("From: {sender}", "מאת: {sender}"),
    # Setup
    "setup_title": ("Add an e-mail account", "הוספת חשבון דואר"),
    "your_name": ("Your name (what people see)", "השם שלכם (מה שאחרים רואים)"),
    "address": ("E-mail address", "כתובת מייל"),
    "password": ("Password", "סיסמה"),
    "remember": ("Remember the password in the keyring", "לזכור את הסיסמה במחזיק המפתחות"),
    "no_keyring": ("No keyring: the password is kept only until J closes.",
                   "אין מחזיק מפתחות: הסיסמה נשמרת רק עד שסוגרים את J."),
    "find": ("Find settings", "חיפוש הגדרות"),
    "finding": ("Looking for the settings of {domain}…", "מחפש את ההגדרות של {domain}…"),
    "found": ("Found: {host} (secure connection)", "נמצא: {host} (חיבור מאובטח)"),
    "found_guess": ("Not found; trying {host}. Check it under Advanced.", "לא נמצא; מנסה את {host}. אפשר לבדוק בהגדרות מתקדמות."),
    "note_app_password": ("Gmail: use an app password (Google account → Security → 2-Step Verification → App "
                          "passwords).", "Gmail: השתמשו בסיסמת אפליקציה (חשבון Google ← אבטחה ← אימות דו־שלבי ← "
                          "סיסמאות לאפליקציות)."),
    "note_oauth": ("This provider accepts only its own sign-in page, which J does not support yet. Meanwhile, "
                   "Thunderbird works: type \"+ thunderbird\" in D.Ai Command.",
                   "הספק הזה מקבל רק את דף הכניסה שלו, ו־J עוד לא תומך בזה. בינתיים Thunderbird עובד: "
                   "כתבו \"+ thunderbird\" ב־D.Ai Command."),
    "advanced": ("Advanced settings", "הגדרות מתקדמות"),
    "incoming": ("Incoming (IMAP)", "דואר נכנס (IMAP)"),
    "outgoing": ("Outgoing (SMTP)", "דואר יוצא (SMTP)"),
    "server": ("Server", "שרת"),
    "port": ("Port", "פורט"),
    "security": ("Encryption", "הצפנה"),
    "username": ("User name", "שם משתמש"),
    "sign_in": ("Sign in", "כניסה"),
    "signing_in": ("Signing in…", "נכנס…"),
    "cancel": ("Cancel", "ביטול"),
    "bad_address": ("That does not look like an e-mail address.", "זה לא נראה כמו כתובת מייל."),
    "ask_password": ("Password for {address}", "הסיסמה של {address}"),
    "confirm_remove": ("Remove {address} from J? The local copy of its mail and its saved password are deleted. "
                       "Nothing is deleted on the server.",
                       "להסיר את {address} מ־J? העותק המקומי של הדואר והסיסמה השמורה יימחקו. בשרת לא נמחק כלום."),
    # Errors (keys from mail.MailError)
    "e_login": ("The server did not accept the user name or password.", "השרת לא קיבל את שם המשתמש או הסיסמה."),
    "e_unreachable": ("Cannot reach the mail server. Check the Internet connection and the server name.",
                      "אין חיבור לשרת הדואר. בדקו את החיבור לאינטרנט ואת שם השרת."),
    "e_certificate": ("The server's security certificate is not valid, so J did not connect.",
                      "תעודת האבטחה של השרת לא תקינה, ולכן J לא התחבר."),
    "e_insecure": ("J connects only with encryption.", "J מתחבר רק עם הצפנה."),
    "e_server": ("The server refused the request.", "השרת סירב לבקשה."),
    "e_gone": ("This message is no longer on the server.", "ההודעה הזו כבר לא בשרת."),
    "e_recipients": ("The server refused one of the recipients.", "השרת סירב לאחד הנמענים."),
    "e_send": ("The message was not sent. It is still here; try again.", "ההודעה לא נשלחה. היא עדיין כאן; נסו שוב."),
    "e_unknown": ("Something went wrong: {detail}", "משהו השתבש: {detail}"),
    # Import (docs/MAIL.md §3.1)
    "import": ("Import from another mail app", "ייבוא מתוכנת דואר אחרת"),
    "import_title": ("Accounts found on this computer", "חשבונות שנמצאו במחשב הזה"),
    "import_none": ("No other mail app with accounts was found (Thunderbird, Betterbird, Evolution, Claws Mail, "
                    "Mutt).", "לא נמצאה תוכנת דואר אחרת עם חשבונות (Thunderbird, ‏Betterbird, ‏Evolution, "
                    "‏Claws Mail, ‏Mutt)."),
    "import_hint": ("Only the settings are copied; the other app is not changed. J asks for each password the "
                    "first time it signs in.", "רק ההגדרות מועתקות, והתוכנה האחרת לא משתנה. J יבקש כל סיסמה בכניסה "
                    "הראשונה."),
    "import_add": ("Add the checked accounts", "הוספת החשבונות המסומנים"),
    "import_row": ("{address} · from {source} · {host}", "{address} · מ־{source} · {host}"),
    "import_oauth": ("signs in only through the provider's page (not supported yet)",
                     "נכנס רק דרך הדף של הספק (עוד לא נתמך)"),
    "import_insecure": ("used without encryption; J connects only with encryption",
                        "השתמש בחיבור לא מוצפן; J מתחבר רק עם הצפנה"),
    "import_added": ("{count} account(s) added. Check mail to sign in.", "נוספו חשבונות: {count}. בדקו דואר כדי להיכנס."),
    # Compose
    "compose_title": ("New message", "הודעה חדשה"),
    "from": ("From", "מאת"),
    "to": ("To", "אל"),
    "cc": ("Cc", "עותק"),
    "subject": ("Subject", "נושא"),
    "body": ("Message", "תוכן ההודעה"),
    "send": ("Send", "שליחה"),
    "sending": ("Sending…", "שולח…"),
    "sent_ok": ("Sent.", "נשלח."),
    "rtl": ("Right to left", "מימין לשמאל"),
    "ltr": ("Left to right", "משמאל לימין"),
    "bad_recipients": ("Check these addresses: {bad}", "בדקו את הכתובות האלה: {bad}"),
    "no_recipients": ("Who is it for? Add an address in To.", "למי ההודעה? הוסיפו כתובת בשדה אל."),
    "discard": ("Discard this message?", "לוותר על ההודעה הזו?"),
    "discard_yes": ("Discard", "ויתור"),
}


def t(key: str, lang: str | None = None, **kwargs: object) -> str:
    lang = lang or ui_lang()
    return text(lang, *STRINGS[key], **kwargs) if kwargs else pick(lang, *STRINGS[key])


def error(key: str, lang: str | None = None) -> str:
    name = f"e_{key}"
    return t(name, lang) if name in STRINGS else t("e_unknown", lang, detail=key)

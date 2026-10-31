# D.Ai Remind: "תזכיר לי" (שלב 1)

> נכתב ב־2026-10-31 אחרי "המשך בפיתוח פיצרים". תזכורת היא המשפט הכי יומיומי שמחשב יכול להבין, והיא עוברת
> באותו מסלול כמו כל הגדרה ב־D.Ai: משפט → תוכנית → אישור → ביטול.

## 1. הרעיון

בשורת הפקודה (או ב־`dai-tune`): "remind me in 20 minutes to call Dana", "remind me at 18:30 to take the pills",
"remind me tomorrow at 8 to pay the bill" / "תזכיר לי בעוד 20 דקות לצלצל לדנה", "תזכיר לי ב־18:30 לקחת את
הכדורים", "תזכיר לי מחר ב־8 לשלם את החשבון". ‏Diamond מראה את התוכנית ("תזכורת ב־18:30: לקחת את הכדורים"),
מאשרים, ובזמן: הודעה עם הטקסט, צליל מהמשפחה של היהלום, ובלי שום דבר שעוזב את המחשב.

## 2. איך זה עובד

1. **פרסר** (dai_tune/parser.py): `REMIND` תופס "remind me / תזכיר לי", ואז `in N minutes|hours` / `בעוד N דקות|שעות`,
   או `at HH[:MM]` / `ב־HH[:MM]` עם `tomorrow` / `מחר` אופציונלי (אותם ביטויי שעה של Forge: `בבוקר`, `בערב`, `pm`),
   והטקסט אחרי `to` / `ל…`/`ש…`. טקסט: 1–200 תווים, בלי שורות חדשות.
2. **פעולה** `reminder.add` (תחום משתמש, ניטרלית, ניתנת לביטול): בוולידציה הזמן היחסי הופך למוחלט (`at`, ISO,
   דקות שלמות; שעה שכבר עברה היום = מחר; עד 365 ימים קדימה). ההחלה כותבת
   `~/.local/share/dai/reminders/<id>.json` (0600; `text`, `at`, `created`) ושני קובצי systemd של המשתמש:
   `dai-remind-<id>.timer` (`OnCalendar=YYYY-MM-DD HH:MM:00`, ‏`AccuracySec=1s`) ו־`.service`
   (`ExecStart=/usr/bin/dai-remind fire <id>`), ואז `daemon-reload` ו־`enable --now`. ביטול (`dai-tune undo`) מחזיר את
   הקבצים ומכבה את הטיימר, כמו `way.when`.
3. **הפעלה** (`dai-remind fire <id>`): `notify-send -u critical "⏰ …"` עם הטקסט, `dai-sound bell`, ואם "להקריא הסברים"
   פועל ב־Explain (‏`~/.config/dai/explain.json`, ‏`voice`) גם `dai-speak`. אחר כך הטיימר מוסר (disable, מחיקת היחידות
   וה־json) ונכתב `<id>.fired` (זמן ההפעלה בלבד).
4. **רשימה:** `dai-remind list` (הקרובות, לפי זמן); ב־Command "my reminders" / "התזכורות שלי" פותח אותה.
   `dai-remind cancel <id>` מסיר אחת (אותו ניקוי כמו fire, בלי הודעה).

## 3. פרטיות ואבטחה

- הטקסט נשאר במחשב, בקובץ של המשתמש (0600), ועובר ל־notify-send ול־dai-speak כארגומנט/stdin: הוא **נתון**, לא
  פקודה (אין shell). שם היחידה הוא מזהה הקסדצימלי, לא הטקסט.
- היחידות רצות כמשתמש, `NoNewPrivileges=yes`; שום דבר לא דורש מנהל.
- ‏`fire` ו־`cancel` מקבלים רק מזהה `[0-9a-f]{8}` ונוגעים רק בקבצים בשמם.

## 4. בדיקות

יחידה: הפרסר (שני השפות, יחסי/מוחלט/מחר, שעה שעברה → מחר, טקסט ארוך נדחה), הפעולה (קבצים, 0600, ביטול מחזיר),
‏`fire` עם notify-send/dai-sound/dai-speak מדומים ומחיקת היחידות, ‏`list`/`cancel`, ‏Command מראה את התוכנית.
‏VM: `remind: in a minute` (‏`dai-tune --yes 'remind me in 1 minute to drink water'` → הטיימר רשום ב־systemctl, אחרי
~75 שניות `<id>.fired` קיים והיחידות נעלמו; תזכורת שנייה מבוטלת ב־`dai-tune undo`).

## 5. מצב

🔨 שלב 1 נבנה; ממתין ל־CI.

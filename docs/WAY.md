# דרך היהלום (Diamond's Way): מחשב שלם בקובץ אחד

מסמך תכנון ובנייה. © 2026 Diamond Rubinny (d.Ai) · D.Ai OS · Apache-2.0

## 1. הרעיון

ב־D.Ai כבר אומרים למחשב מה רוצים במשפט אחד: D.Ai Tune ("נעל מסך אחרי 5 דקות"), D.Ai Forge ("התקן אנטי וירוס"),
D.Ai Settings, D.Ai Store. **דרך היהלום** היא השפה שבה כותבים את *כל* המחשב בקובץ אחד, `.dway`, במשפטים
שה־D.Ai כבר מבין, בעברית או באנגלית, ומחילים אותו בפעולה אחת, עם אותה תוכנית, אותו אישור ואותו undo. ומהצד
השני: `dai-way export` כותב את המחשב הנוכחי כקובץ כזה. זה הכוח: מחשב שלם שאפשר לקרוא, לשתף, לשחזר ולהעתיק
למחשב הבא, בלי שורת shell אחת, בלי כלי של מנהלי שרתים.

## 2. השפה

```
# My family computer                       ← comments
diamond: family computer                   ← the name (one line; shown in the journal)
let minutes = 10                           ← values, used as $minutes

setup:                                     ← D.Ai Tune sentences, one per line
  lock the screen after $minutes minutes
  block usb storage
  memory saver on
  firefox does not go online

apps:                                      ← D.Ai Forge recipes (by id or by a sentence) and Flathub ids
  antivirus
  signal
  org.videolan.VLC

exact:                                     ← the catalog's own form (what export writes), one action per line
  @ firewall.open_port port=8080 proto=tcp source=lan
  @ appearance.theme theme=day

files:                                     ← folders and small text files in the home (stage 3)
  Documents/School/
  Documents/Welcome.txt: Hello! This computer is yours.
  Documents/Rules.md < rules.md            ← the text comes from a file next to this one

when:                                      ← a schedule, a colon, a sentence (user scope only; stage 2)
  every evening at 20:00: dark theme
  every morning at 7:00: light theme

use: shared/office.dway                    ← another file, from the same folder only
```

- **כותרות** (`setup:`, `apps:`, `exact:`) באנגלית או בעברית (`הגדרות:`, `אפליקציות:`, `מדויק:`); `diamond:` /
  `יהלום:`; `let` / `יהי`; `use:` / `כלול:`.
- **משפט** הוא כל מה ש־D.Ai Tune מבין (docs/TUNE.md); **אפליקציה** היא מזהה מתכון (`antivirus`), משפט שמתאים
  למתכון ("אנטי וירוס") או מזהה Flathub (`org.x.Y`).
- **שורת `when:`** (`כאשר:`) היא לוח זמנים של Evolve ("every day at 18:00", "כל בוקר", "every monday at 9",
  "every 30 minutes", "at login"; docs/EVOLVE.md §2), נקודתיים, ומשפט של D.Ai Tune. היא הופכת לפעולה אחת
  `way.when`: טיימר של systemd למשתמש שמריץ `dai-way run-when NAME` בזמן, וזה מחיל את המשפט דרך אותו קטלוג
  ואותו יומן ("Way when: NAME"; `dai-tune undo` מבטל גם הרצה כזו). **רק משפטים בהיקף משתמש**: טיימר לא יכול
  לבקש סיסמת מנהל, ולכן משפט מערכת ("memory saver on") נדחה כבר ב־`check`, עם מספר השורה. אין כאן סקריפט ואין
  AI: המשפט נשמר כטקסט ומפורש מחדש בכל הרצה דרך הפרסר הדטרמיניסטי.
- **שורת `files:`** (`קבצים:`) היא תיקייה (`Documents/School/`), קובץ טקסט עם התוכן אחרי נקודתיים, או קובץ שתוכנו
  מגיע מקובץ שכן (`< rules.md`, מאותה תיקייה בלבד, כמו `use:`). כל שורה היא פעולה `way.file` בהיקף משתמש, עם
  גבולות קשיחים: נתיב יחסי לבית בלבד, בלי `..`, בלי רכיבים מוסתרים (לא `.config`, לא `.local`), בלי `.desktop`,
  טקסט UTF-8 עד 64 KB, קובץ נכתב 0644 ותיקייה 0755 (לעולם לא קובץ הרצה). קובץ שכבר קיים עם תוכן אחר נדחה
  ב־`check` ("exists with other content"); אותו תוכן הוא לא־פעולה. `undo` מוחק קובץ שנוצר ומסיר תיקייה שנוצרה
  אם היא ריקה; תיקיות־אב שנוצרו בדרך נשארות. `export` לא כותב קבצים (הם של המשתמש, לא של המחשב).
- **שורה מדויקת** היא פעולה מהקטלוג עם הפרמטרים שלה; מספרים ו־true/false מזוהים, רשימות מופרדות בפסיק.
- הכול הופך ל**תוכנית אחת** של D.Ai Tune: כל הצעדים, היקף (משתמש/מערכת), סיכון, מה מחליש. אין הרצה חלקית:
  משפט אחד שלא מובן, והקובץ נדחה לפני שמשהו קורה (`dai-way check`).

### 2.1 מדיניות ארגונית (שלב 4)

קובץ `.dway` ב־`/etc/dai/policy.d/` (docs/EDU.md §2) הוא מדיניות: `dai-policy` קורא אותו דרך דרך היהלום, עם אותם
כללי אמון (root, לא ניתן לכתיבה, לא symlink, עד 64 KB) ואותו יומן. מותר: `setup:`, `apps:`, `exact:` בהיקף מערכת,
ו"lock the screen after N minutes" שהופך למגבלה לכל המשתמשים. נדחה עם הסבר ב־`dai-tune policy`: ‏`use:`, שורות
`when:` ו־`files:` (היקף משתמש), וכל משפט מערכת שלא מובן. כך בית ספר כותב קובץ אחד שמתאר את המחשב, ואותו קובץ
משמש גם ל־`dai-way apply` על מחשב בודד וגם כמדיניות לצי שלם.

## 3. הפקודות

| פקודה | מה |
|---|---|
| `dai-way check FILE` | מפרסר ובונה את התוכנית בלי להחיל; מדווח על כל שורה שלא הובנה, עם מספר שורה |
| `dai-way plan FILE` | מציג את התוכנית המלאה (כמו `dai-tune --dry-run`) |
| `dai-way apply FILE` | מראה, מבקש אישור (הקלדה כשיש החלשה), מחיל דרך ה־helper (polkit) ורושם ביומן: "Way: NAME" |
| `dai-way undo` | מבטל את ההחלה האחרונה (אותו יומן של D.Ai Tune) |
| `dai-way export [FILE]` | כותב את המחשב הזה: ההגדרות (מ־D.Ai Settings, כשורות מדויקות), המתכונים המותקנים, הטיימרים של `when:` |
| `dai-way examples` | הדוגמאות המובנות: בית, כיתה, עבודה (`/usr/share/dai/way/`) |
| `dai-way when` | הטיימרים של `when:` שמותקנים: שם, לוח זמנים, משפט |
| `dai-way when remove NAME` | מסיר טיימר (פעולת `way.when_off`, ביומן, עם undo) |
| `dai-way run-when NAME` | מה שהטיימר מריץ: מפרש את המשפט השמור ומחיל בהיקף משתמש, בלי שאלות (ההסכמה ניתנה ב־apply) |

## 4. אבטחה ופרטיות

- אין shell, אין קוד: רק פעולות מהקטלוג, עם הוולידציה שלהן; כל מה שלא מובן נדחה. **קובץ שמישהו שלח הוא לא
  סכנה**: לכל היותר הוא מבקש פעולות שהמערכת ממילא מציעה, ואת כולן רואים לפני האישור.
- `use:` רק מאותה תיקייה (לא נתיב מוחלט, לא `..`), עומק 3, עד 64 KB לקובץ, עד 400 שורות.
- `export` לא כותב סודות: אין סיסמאות, אין Wi-Fi, אין מפתחות; רק הגדרות ומתכונים.
- מנהל נדרש לצעדי מערכת, כמו תמיד.

## 5. מה לא (עדיין)

‏`when:` עם משפטי מערכת (טיימר לא יכול לבקש מנהל; אולי דרך מדיניות ארגונית בהמשך); אוטומציות עם סקריפט (אלה של
Evolve, שנכתבות על ידי Diamond ואינן דטרמיניסטיות: נשארות ב־Forge); קבצים מחוץ לבית, קבצים מוסתרים, קבצים
בינאריים או גדולים (העתקה היא עניין של גיבוי, לא של קובץ הגדרה);
מדיניות ארגונית (`policy.d` כבר קיימת, docs/EDU.md); ייצוא של אפליקציות ש־Forge בנה.

## 6. בדיקות

יחידה: הפרסר (שתי השפות, משתנים, כותרות, שגיאות עם מספרי שורה, `use:` ומגבלותיו); התוכנית (משפטים + מתכונים +
שורות מדויקות → תוכנית אחת; משפט לא מובן דוחה הכול); `when:` (לוח זמנים לא מובן, משפט מערכת, שם יציב, קובצי
היחידות, run-when מחיל ומתעד, when_off); `files:` (תיקייה, קובץ עם טקסט, `<` מקובץ שכן, כל גבול נתיב נדחה, קיים
עם תוכן אחר נדחה, undo מוחק); export → check חוזר (גם שורות `when:`); CLI. ‏VM: `way: a computer in one file`
(דוגמה מובנית נבדקת, מוחלת בהיקף משתמש, מבוטלת; export נבדק); `way: when, a timer runs a sentence` (קובץ עם
`when:`, הטיימר מופיע ב־systemctl --user, run-when מחיל, undo של ההרצה ושל הטיימר, משפט מערכת נדחה); מדיניות
`.dway` בתוך `policy: applied on drop`; `way: files
in the home` (תיקייה וקובץ נוצרים, `..` ו־`.config` נדחים, undo מוחק).

## 7. מצב

✅ שלב 1 (השפה, תוכנית אחת, export) ושלב 2 (`when:` טיימרים בהיקף משתמש) נבנו ואומתו ב־CI: ריצה 39911193558, 132 בדיקות VM עוברות כולל `way: a computer in one file` ו־`way: when, a timer runs a sentence`. שלב 3 (`files:`) אומת בריצה 40024357898 (133 בדיקות VM, 0 נכשלות); שלב 4 (`.dway` כמדיניות ב־policy.d) אומת בריצה 40047206790 (134 בדיקות VM, 0 נכשלות).

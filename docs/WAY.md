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

use: shared/office.dway                    ← another file, from the same folder only
```

- **כותרות** (`setup:`, `apps:`, `exact:`) באנגלית או בעברית (`הגדרות:`, `אפליקציות:`, `מדויק:`); `diamond:` /
  `יהלום:`; `let` / `יהי`; `use:` / `כלול:`.
- **משפט** הוא כל מה ש־D.Ai Tune מבין (docs/TUNE.md); **אפליקציה** היא מזהה מתכון (`antivirus`), משפט שמתאים
  למתכון ("אנטי וירוס") או מזהה Flathub (`org.x.Y`).
- **שורה מדויקת** היא פעולה מהקטלוג עם הפרמטרים שלה; מספרים ו־true/false מזוהים, רשימות מופרדות בפסיק.
- הכול הופך ל**תוכנית אחת** של D.Ai Tune: כל הצעדים, היקף (משתמש/מערכת), סיכון, מה מחליש. אין הרצה חלקית:
  משפט אחד שלא מובן, והקובץ נדחה לפני שמשהו קורה (`dai-way check`).

## 3. הפקודות

| פקודה | מה |
|---|---|
| `dai-way check FILE` | מפרסר ובונה את התוכנית בלי להחיל; מדווח על כל שורה שלא הובנה, עם מספר שורה |
| `dai-way plan FILE` | מציג את התוכנית המלאה (כמו `dai-tune --dry-run`) |
| `dai-way apply FILE` | מראה, מבקש אישור (הקלדה כשיש החלשה), מחיל דרך ה־helper (polkit) ורושם ביומן: "Way: NAME" |
| `dai-way undo` | מבטל את ההחלה האחרונה (אותו יומן של D.Ai Tune) |
| `dai-way export [FILE]` | כותב את המחשב הזה: ההגדרות (מ־D.Ai Settings, כשורות מדויקות), המתכונים המותקנים, הכלל "לא יוצא לאינטרנט", חיסכון בזיכרון |
| `dai-way examples` | הדוגמאות המובנות: בית, כיתה, עבודה (`/usr/share/dai/way/`) |

## 4. אבטחה ופרטיות

- אין shell, אין קוד: רק פעולות מהקטלוג, עם הוולידציה שלהן; כל מה שלא מובן נדחה. **קובץ שמישהו שלח הוא לא
  סכנה**: לכל היותר הוא מבקש פעולות שהמערכת ממילא מציעה, ואת כולן רואים לפני האישור.
- `use:` רק מאותה תיקייה (לא נתיב מוחלט, לא `..`), עומק 3, עד 64 KB לקובץ, עד 400 שורות.
- `export` לא כותב סודות: אין סיסמאות, אין Wi-Fi, אין מפתחות; רק הגדרות ומתכונים.
- מנהל נדרש לצעדי מערכת, כמו תמיד.

## 5. מה לא (עדיין)

`when ... :` (אוטומציות מתוזמנות דרך Evolve: הסקריפט שלהן נכתב על ידי Diamond ואינו דטרמיניסטי); קבצים ותיקיות;
מדיניות ארגונית (`policy.d` כבר קיימת, docs/EDU.md); ייצוא של אפליקציות ש־Forge בנה.

## 6. בדיקות

יחידה: הפרסר (שתי השפות, משתנים, כותרות, שגיאות עם מספרי שורה, `use:` ומגבלותיו); התוכנית (משפטים + מתכונים +
שורות מדויקות → תוכנית אחת; משפט לא מובן דוחה הכול); export → check חוזר; CLI. ‏VM: `way: a computer in one file`
(דוגמה מובנית נבדקת, מוחלת בהיקף משתמש, מבוטלת; export נבדק).

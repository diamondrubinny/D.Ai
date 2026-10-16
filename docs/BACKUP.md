# D.Ai Backup: גיבוי מוצפן שלא צריך לזכור (v0.1)

> ‏35% מהמשתמשים לא מגבים באופן קבוע. בסקר אחר, ‏32% לא יודעים איך ו־22% שוכחים ([RESEARCH.md](RESEARCH.md) §1, כאב 4). ב־D.Ai OS מגדירים גיבוי פעם אחת, במשפט, והוא רץ לבד בכל פעם שהדיסק החיצוני מחובר.

## 1. שימוש

```bash
dai-backup setup /media/$USER/MyDisk      # once: creates an encrypted backup there and shows the recovery key
dai-backup now                            # back up now (otherwise: daily, automatically)
dai-backup status                         # last backup, how many copies, how much space
dai-backup list                           # all copies (dates)
dai-backup restore ~/Documents/report.odt # bring a file back (to ~/Restored/<date>/…)
dai-backup check                          # verify the backup can really be restored
```

ב־D.Ai Command כותבים: "גבה את הקבצים שלי", ‏"מתי היה הגיבוי האחרון?", ‏"שחזר את report.odt", ‏"back up my files".

## 2. מה קורה מאחורי הקלעים

| נושא | החלטה | למה |
|------|-------|-----|
| כלי | ‏**restic** (חבילת Debian) | הצפנה (AES-256), ביטול כפילויות, אימות ושחזור. הכלי ותיק, נבדק ונמצא בשימוש רחב |
| יעד | תיקייה בדיסק חיצוני (`<disk>/D.Ai-Backup`) | גיבוי מקומי לא תלוי בענן. גיבוי לענן מתוכנן כאפשרות |
| מה מגובה | ‏`~/Documents`, ‏`~/Pictures`, ‏`~/Desktop`, ‏`~/Music`, ‏`~/Videos` ותיקיות ש־Forge יצר (אפשר להוסיף) | בלי cache, בלי `node_modules` ובלי סל המחזור |
| מתי | טיימר משתמש יומי (`dai-backup.timer`, ‏Persistent). אם הדיסק לא מחובר, מדלגים בשקט. אחרי 7 ימים בלי גיבוי מופיעה תזכורת | הגיבוי לא מפריע ולא נשכח |
| כמה עותקים | 7 יומיים, ‏4 שבועיים, ‏12 חודשיים | אפשר לחזור גם כמה חודשים אחורה |
| אימות | `restic check` על 5% מהנתונים, פעם בשבוע | גיבוי שלא בודקים הוא לא גיבוי |
| שחזור | לתיקייה חדשה, `~/Restored/<תאריך>`. אף פעם לא דורסים קבצים קיימים | בטוח |

## 3. אבטחה ופרטיות

- **מפתח שחזור:** נוצר בהתקנה (‏32 בתים אקראיים) ונשמר ב־`~/.config/dai/backup.key` ‏(0600). **הוא מוצג פעם אחת**, וצריך לרשום אותו במקום בטוח. אם המחשב נגנב או מתקלקל, אי אפשר לשחזר בלי המפתח, וגם אף אחד אחר לא יכול.
- הסיסמה לא מופיעה בשורת הפקודה (`--password-file`) ולא ביומנים.
- הדיסק החיצוני מכיל רק נתונים מוצפנים. מי שמוצא אותו לא יכול לקרוא כלום.
- הכל רץ כמשתמש, בלי הרשאות root, ושום דבר לא נשלח לרשת.

## 4. מגבלות (v0.1)

- יעד אחד בכל פעם. אין עדיין גיבוי לענן.
- גיבוי תיקיות המשתמש בלבד, לא של כל המערכת (בשביל זה יש התקנה מחדש ו־D.Ai Tune ‏undo).
- ‏`restore` משחזר קובץ או תיקייה לפי נתיב. דפדוף גרפי בגרסאות מתוכנן.

---

© 2026 Diamond Rubinny (d.Ai) · D.Ai OS · Apache-2.0

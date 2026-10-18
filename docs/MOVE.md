# D.Ai Move: מעבירים את הקבצים מ־Windows (v0.1)

> רוב מי שהורידו Zorin OS בזמן סיום התמיכה ב־Windows 10 הגיעו מ־Windows. הורדות הן לא מעברים, ומשתמשים חוזרים בגלל חיכוך ([GROWTH.md](GROWTH.md)). ‏Move מוריד את החיכוך הראשון: איפה הקבצים שלי?

## 1. שימוש

```bash
dai-move                      # looks for Windows on connected drives
dai-move /media/$USER/Windows # a Windows drive (dual boot, or the old computer's disk in a USB case)
dai-move /media/$USER/USB/Dana --dry-run   # a copied C:\Users\Dana folder; only show what would be copied
```

ב־D.Ai Command: ‏"תעביר את הקבצים מווינדוס", ‏"import my files from windows".

## 2. מה עובר

| מ־Windows | אל | הערות |
|-----------|----|-------|
| ‏`Users\<שם>\Documents`, ‏Pictures, ‏Desktop, ‏Music, ‏Videos, ‏Downloads | אותן תיקיות בבית | **שום דבר לא נדרס.** שם תפוס מקבל „(Windows)” |
| סימניות Chrome ו־Edge | `~/Bookmarks-from-Windows.html` | קובץ HTML סטנדרטי. מייבאים ב־Firefox: סימניות → ניהול → ייבוא מ־HTML. קישורי `javascript:` ו־`file:` מסוננים |
| רשתות Wi-Fi שמורות | רשימת שמות | **הסיסמאות לא עוברות:** ‏Windows מצפין אותן למחשב הישן (DPAPI). צריך להזין כל סיסמה פעם אחת |

מדלגים על: `desktop.ini`, ‏`Thumbs.db`, ‏`NTUSER.DAT`, סל המחזור, "My Music"/"My Pictures" (קיצורים של Windows) וקישורים סימבוליים.

## 3. בטיחות

- המקור **נקרא בלבד**.
- לפני ההעתקה מוצג סיכום: כמה קבצים, כמה מקום, מה יקבל שם חדש. נדרש אישור (או `--yes`).
- נבדק שיש מספיק מקום פנוי לפני שמתחילים.
- הכל רץ כמשתמש, בלי root.

## 4. מגבלות

- כונן עם **BitLocker** אי אפשר לקרוא כאן. מעתיקים קודם מתוך Windows לדיסק און קי. ‏Move אומר את זה כשהוא לא מוצא קבצים.
- הגדרות של תוכנות (Outlook, ‏WhatsApp Desktop וכו') לא עוברות.

---

© 2026 Diamond Rubinny (d.Ai) · D.Ai OS · Apache-2.0

# מחקר: מה משתמשים רוצים ואין להם במערכות ההפעלה (אוקטובר 2026)

> מטרה: לבחור את הפיצ'רים הבאים של D.Ai OS לפי כאבים אמיתיים של משתמשים, ולא לפי מה שקל לבנות. מקורות: סיקור עיתונאי, פורומים, דיווחי באגים וסקרים (רובם תעשייתיים; הממצאים **כיווניים** ולא מחקר מדעי). הקישורים בסוף.

## 1. ממצאים

| # | כאב | ראיות | מה המתחרות עושות |
|---|-----|-------|-------------------|
| 1 | **אובדן אמון: עדכונים כפויים, פרסומות, טלמטריה, חשבון חובה** | ב־2026 התלונות על Windows 11 מתרכזות בעדכונים חודשיים עם רגרסיות (תיקוני חירום בינואר 2026), טלמטריה חובה, פרסומות והמלצות בתוך המערכת, AI מופעל כברירת מחדל ולחץ לחשבון Microsoft | Microsoft הודיעה על "תוכנית תיקון", אבל הטלמטריה והחשבון לא כלולים בה |
| 2 | **AI כן, אבל פרטי ובשליטה** | ‏61% מהנשאלים בסקר CMR מעדיפים AI שרץ על המכשיר. ‏82% דורשים שקיפות לפני שהם סומכים. בסקר Circana ‏59% מהלא־מעוניינים מציינים פרטיות. Recall נדחה אחרי שמסד הנתונים נמצא לא מוצפן | Recall הפך ל־opt-in עם הצפנה |
| 3 | **"תחזיר לי את המצב הקודם"** (undo למערכת) | הבקשה חוזרת: rollback פשוט לכל שינוי, עם ממשק. ב־Linux יש snapshots (Btrfs), אבל "ממשק גרפי פשוט חסר" | ‏Windows: System Restore (חלקי). ‏macOS: Time Machine |
| 4 | **גיבוי שלא צריך לחשוב עליו** | ‏35% לא מגבים באופן קבוע (Acronis 2025). בסקר אחר: ‏32% לא יודעים איך, ו־22% שוכחים | ‏Windows: OneDrive (ענן, מופעל אוטומטית ומעורר כעס). ‏macOS: Time Machine |
| 5 | **"למה המחשב איטי?" ו"מה תופס לי את הדיסק?"** | השאלות הנפוצות ביותר באתרי תמיכה: איטיות, מקום בדיסק, זמן הפעלה, נוזקות | כלים מפוזרים (Task Manager, Storage Sense), בלי הסבר בשפה פשוטה |
| 6 | **למצוא קובץ "כמו שאני זוכר אותו"** ("ה־PDF שהורדתי בשבוע שעבר") | יש רק כלים חיצוניים וניסיוניים (monkeSearch, ‏File Brain). ב־Ubuntu יש הצעה שלא מומשה | Spotlight ו־Windows Search לא מבינים "בשבוע שעבר" |
| 7 | **פרטיות מצלמה ומיקרופון לכל אפליקציה** | Windows 11 רק מתחיל (2026, ‏Insider) לאפשר לחסום מצלמה ומיקרופון לכל תוכנה. ב־Linux אין מחוון כזה | בטלפונים זה קיים מזמן |
| 8 | **סוללה במחשב נייד** | דיווחים חוזרים על סוללה חלשה יותר ב־Linux (אנקדוטלי), ו־**ב־D.Ai עדיין אין חבילת ניהול צריכת חשמל** | ‏Windows ו־macOS: ניהול מובנה |
| 9 | **עברית ו־RTL** | באגים חוזרים: קיצורים שלא עובדים בפריסה עברית, כיוון פסקה שמתהפך, סוגריים הפוכים | ‏D.Ai: תיקון שפה שגויה ✅, ‏RTL בכל הכלים ✅ |
| 10 | **"אין לי את התוכנה שלי" ומשחקים** | הסיבה המרכזית לא לעבור ל־Linux. שיעור Linux ב־Steam עלה (5.33% במרץ 2026, מקור יחיד) | ‏Flatpak, ‏Wine ו־Proton קיימים, אבל לא מוצגים למשתמש |
| 11 | **סיסמאות שנשארות בהיסטוריית ההעתקות** | מנהלי לוח הדבקות שומרים סיסמאות. הפתרון (רמז `x-kde-passwordManagerHint`) לא נתמך בכל מקום | — |

## 2. איך D.Ai עונה, ומה חסר

| כאב | יש היום | חסר — מה בונים |
|-----|---------|----------------|
| 1 אמון | אין פרסומות, אין טלמטריה, אין חשבון, עדכוני D.Ai ידניים, ‏`docs/RELEASE.md` | — (עיקרון. מבחן אוטומטי שאין חיבורים יוצאים ללא בקשה: ✅ חומת אש) |
| 2 AI פרטי | ‏AI מקומי, ‏Welcome מסביר | — |
| 3 undo | ‏undo לכל שינוי של Tune, ‏Forge ו־Code. ✅ תמונות מצב לפני עדכון על Btrfs ([SNAPSHOTS.md](SNAPSHOTS.md)) | ‏Btrfs כברירת מחדל במתקין (מחכה לאישור) |
| 4 גיבוי | ✅ D.Ai Backup | **D.Ai Backup**: גיבוי מוצפן ואוטומטי לדיסק חיצוני בשורה אחת ("גבה את התיקיות שלי לדיסק החיצוני כל יום") |
| 5 איטיות ודיסק | ✅ D.Ai Doctor | **D.Ai Doctor**: ‏"למה המחשב איטי?" ו"מה תופס את הדיסק?" — תשובה בשפה פשוטה עם פעולות לתיקון |
| 6 חיפוש בשפה טבעית | ✅ D.Ai Find | **D.Ai Find**: ‏"ה־PDF שהורדתי בשבוע שעבר", ‏"תמונות מאתמול" — בעברית ובאנגלית, מקומי |
| 7 מצלמה ומיקרופון | ✅ מחוון פרטיות | **מחוון פרטיות**: מי משתמש כרגע במיקרופון או במצלמה, ויומן שימוש |
| 8 סוללה | ✅ power-profiles-daemon ו־Tune | **power-profiles-daemon** + פעולת Tune ‏("מצב חיסכון בסוללה") |
| 9 עברית | ✅ | ממשיכים |
| 10 תוכנות | ✅ מתכוני Forge (Steam, Bottles ועוד) | מתכונים: ‏Steam, ‏Bottles (Wine) |
| 11 לוח הדבקות | ✅ **D.Ai Clip** ([CLIP.md](CLIP.md)) | ‏`Super+V`, בזיכרון בלבד, מכבד את רמז הסיסמה, מזהה מפתחות וכרטיסים ומנקה אותם מהלוח |

## 3. סדר בנייה (לפי ערך × היתכנות)

1. ✅ **D.Ai Find** — חיפוש קבצים בשפה טבעית (עברית ואנגלית) בתוך D.Ai Command ([FIND.md](FIND.md)).
2. ✅ **D.Ai Doctor** — "למה המחשב איטי", "מה תופס את הדיסק", עם תיקונים בטוחים דרך Tune ([DOCTOR.md](DOCTOR.md)).
3. ✅ **סוללה** — ‏power-profiles-daemon ופעולת Tune ‏`power.profile`.
4. ✅ **מחוון פרטיות** — מיקרופון ומצלמה בשימוש: מחוון בפאנל ויומן ([PRIVACY.md](PRIVACY.md)).
5. ✅ **D.Ai Backup** — גיבוי מוצפן לדיסק חיצוני עם בדיקת שחזור ([BACKUP.md](BACKUP.md)).
6. ✅ מתכוני Forge למשחקים ול־Windows apps ‏(Steam, ‏Bottles ועוד, [FROM-WINDOWS.md](FROM-WINDOWS.md)).
7. ✅ **לוח הדבקות בטוח** ([CLIP.md](CLIP.md)). ✅ ‏snapshots לפני עדכון, על Btrfs ([SNAPSHOTS.md](SNAPSHOTS.md)).

כל פיצ'ר נבנה באותה שיטה: מסמך תכנון, קוד, בדיקות יחידה, בדיקה ב־VM וצילום מסך.

## 4. מקורות

- [Thurrott — Making Windows 11 Suck Less in 2026](https://www.thurrott.com/windows/windows-11/332300/making-windows-11-suck-less-in-2026)
- [WebProNews — Microsoft's Windows 11 Credibility Crisis](https://www.webpronews.com/microsofts-windows-11-credibility-crisis-inside-the-companys-pledge-to-rebuild-user-confidence/)
- [WindowsForum — Windows 11 trust gap: updates, ads and AI prompts](https://windowsforum.com/windows-news.4/windows-11-trust-gap-updates-ads-and-ai-prompts.398972/)
- [NewsBytes — CMR: AI top priority for young smartphone buyers](https://www.newsbytesapp.com/news/science/cmr-finds-ai-top-priority-for-young-indian-smartphone-buyers/tldr)
- [Home Textiles Today — Circana: US consumers' AI reluctance](https://www.hometextilestoday.com/industry-news/us-consumers-ai-reluctance-circana)
- [InfoWorld — SUSE rollback](https://www.infoworld.com/article/2249817/suse-enterprise-linux-can-take-your-system-back-in-time-3.html)
- [Acronis — Data Privacy in 2025 survey](https://www.acronis.com/en-gb/resource-center/resource/data-privacy-in-2025-survey/)
- [CXOToday — 45% of Indians do not back up](https://cxotoday.com/media-coverage/45-of-indians-do-not-back-up-their-data-and-files/)
- [Computer Hope — Top 10 most frequently asked computer questions](https://computerhope.com/issues/ch002294.htm)
- [Ubuntu Discourse — offline semantic search proposal](https://discourse.ubuntu.com/t/architecture-proposal-native-100-offline-semantic-search-for-ubuntu-via-localsearch-onnx-framework/79490)
- [monkeSearch (GitHub)](https://github.com/simplycode07/monkeSearch)
- [Windows Central — per-app camera and mic blocking](https://www.windowscentral.com/microsoft/windows-11/windows-11-will-soon-let-you-block-camera-and-mic-access-for-any-individual-desktop-app)
- [TLP FAQ — power-profiles-daemon](https://linrunner.de/tlp/faq/ppd.html)
- [LibreOffice bug 101441 (Hebrew shortcuts)](https://bugs.libreoffice.org/show_bug.cgi?id=101441)
- [Evetech — gamers moving to Linux after Windows 10](https://evezone.evetech.co.za/daily-drop/windows-10-hit-end-of-support-why-some-gamers-are-moving-to-linux-instead-of-windows-11)
- [Bitwarden community — passwords in clipboard history](https://community.bitwarden.com/t/linux-prevent-passwords-from-being-stored-in-clipboard-manager-history/94231)
- [KDE — Klipper: do not insert secret data into history](https://phabricator.kde.org/R120:637cd0bf62e419b8038cb9b1565089fbd341ee7a)

---

© 2026 Diamond Rubinny (d.Ai) · D.Ai OS · Apache-2.0

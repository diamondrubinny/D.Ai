# חבילות, עדכונים וגרסאות (Release) של D.Ai OS (v0.1)

> מטרה: כל רכיב של D.Ai מותקן כחבילת `.deb` רגילה, כך ש־dpkg יודע מה שייך למה. עדכונים לרכיבי D.Ai מגיעים ממאגר apt חתום, ורק כשהמשתמש מבקש. כל גרסה מתפרסמת ב־GitHub Releases עם ה־ISO, ‏SHA‑256 וחתימה.

## 1. החבילות

| חבילה | ארכיטקטורה | תוכן | תלויות עיקריות |
|-------|-----------|------|----------------|
| `dai-apps` | all | ‏Command, ‏Tune (כולל helper ו־polkit), ‏AI (daid, ‏dai-models), ‏Forge, ‏Code ו־Voice: ‏`/usr/lib/dai`, ‏`/usr/bin/dai-*`, קבצי ‎`.desktop`, מתכונים ושירותי systemd למשתמש | python3, python3-pyqt6, bubblewrap, pkexec, wl-clipboard, wtype, libnotify-bin, pipewire-bin |
| `dai-llama-runtime` | amd64 | ‏llama.cpp (גרסה נעוצה) ב־`/opt/dai/llama` | libgomp1, libstdc++6 |
| `dai-whisper-runtime` | amd64 | ‏whisper.cpp (גרסה נעוצה) ב־`/opt/dai/whisper` | libgomp1, libstdc++6 |
| `dai-panel-plugin` | amd64 | שדה הפקודה בתוך הפאנל (`libdaicommand.so`) | lxqt-panel |

- **בנייה:** `build/scripts/build-debs.sh OUT_DIR`, עם `dpkg-deb --root-owner-group` בלבד, בלי debhelper. כך הבנייה פשוטה ושחזורית (מכבדת את `SOURCE_DATE_EPOCH`).
- **גרסה:** `0.1.0-alpha+abc1234` הופכת ל־`0.1.0~alpha+abc1234`. התו `~` ממיין את גרסת האלפא לפני 0.1.0 הסופית.
- **קבצי הגדרות:** `/etc/dai/forge.json` מסומן כ־conffile, כך ששינויים של המנהל לא נדרסים בעדכון.
- **ה־ISO** מתקין את החבילות מתוך `config/packages.chroot`, ולא מעתיק קבצים ישירות. ההגדרות של שולחן העבודה (theme, ‏panel.conf, ‏nftables) נשארות חלק מה־image ולא נארזות בגרסה זו.

## 2. עדכונים

```
GitHub Release (tag v*)
  ├─ dai-os-user-….iso, dai-os-dev-….iso
  ├─ SHA256SUMS (+ SHA256SUMS.asc כשיש מפתח חתימה)
  └─ מאגר apt "שטוח": InRelease, Release, Release.gpg, Packages(.gz), dai-*.deb
          ▲
          │ URIs: https://github.com/diamondrubinny/D.Ai/releases/latest/   Suites: download/
          │ (apt קורא download/InRelease; GitHub מפנה בהפניית 302 לקובץ עצמו)
  /etc/apt/sources.list.d/dai.sources  (Signed-By: /usr/share/keyrings/dai-archive-keyring.asc)
  /etc/apt/preferences.d/dai-archive.pref  (dai-* → 500, כל השאר → -1)
```

| החלטה | הסיבה | החלופה |
|-------|-------|--------|
| מאגר שטוח בתוך ה־Release (‏`releases/latest/download`) | לא צריך שרת או GitHub Pages, וכל גרסה כוללת בדיוק את החבילות שלה | ‏GitHub Pages או שרת עם reprepro/aptly, אם יידרשו ערוצי beta ו־stable |
| חתימת GPG על המאגר, עם מפתח פרטי ששמור רק ב־GitHub Secret ‏`DAI_APT_SIGNING_KEY` | apt מסרב לעדכון לא חתום. המפתח לא נמצא בריפו | ‏Sigstore: ‏apt לא תומך בו כיום |
| **Pinning:** מהמאגר של D.Ai אפשר להתקין רק `dai-*`, ושאר החבילות במאגר מקבלות Pin-Priority ‏‎-1 | גם אם המאגר נפרץ, אי אפשר "להחליף" דרכו חבילות Debian כמו sudo או openssl | אין |
| עדכוני D.Ai **לא** אוטומטיים: ‏unattended-upgrades מתקין רק עדכוני אבטחה של Debian | המשתמש הוא שמחליט מתי לעדכן את D.Ai (זו הדרישה מ־Forge) | הפעלה ידנית ב־`/etc/apt/apt.conf.d` |
| עד שיש מפתח, ה־image **לא** כולל את מקור העדכונים | אסור להוסיף מקור apt לא חתום | — |

עדכון ידני: `sudo apt update && sudo apt upgrade`. רשימת הגרסאות: `apt policy dai-apps`.

## 3. פרסום גרסה

1. מגדילים את הגרסה, מתעדים ב־CHANGELOG ופותחים PR.
2. אחרי merge ל־`main`: ‏`git tag -s v0.1.0-alpha && git push origin v0.1.0-alpha`.
3. ה־workflow ‏`Build ISO` רץ על התג: בונה את החבילות ואת שתי המהדורות, ומריץ את בדיקות האתחול.
4. אם כל הבדיקות עברו, ה־job ‏`release` יוצר Release עם כל הקבצים. גרסה עם `-alpha`, ‏`-beta` או `-rc` מסומנת כ־pre-release.

> ⚠️ ‏`releases/latest` מצביע רק על גרסה שאינה pre-release. לכן עדכוני apt מגיעים רק מגרסאות רגילות, וגרסאות אלפא מותקנות מה־ISO.

## 4. הכנה חד־פעמית (באחריות בעל הריפו)

```bash
# On a trusted computer (not in CI):
gpg --quick-gen-key "D.Ai OS Archive <SIGNING-EMAIL>" ed25519 sign 2y
gpg --armor --export <KEY-ID>  > build/keys/dai-archive-keyring.asc   # public — commit this
gpg --armor --export-secret-keys <KEY-ID>                              # private — GitHub → Settings → Secrets → DAI_APT_SIGNING_KEY
```
- שומרים גיבוי של המפתח הפרטי במקום לא מקוון. אם המפתח אבד או נחשף: יוצרים מפתח חדש, מחליפים את הקובץ הציבורי ומפרסמים גרסה. מערכות קיימות יצטרכו להתקין את המפתח החדש ידנית.
- בלי המפתח, ה־release עדיין מתפרסם עם ISO ו־SHA256SUMS, אבל בלי מאגר apt פעיל.

## 5. בדיקות

| בדיקה | איפה |
|-------|------|
| החבילות נבנות; ‏`dpkg-deb --info/--contents`; אין `__pycache__`; הקבצים בבעלות root | CI ‏(lint) |
| מאגר עם מפתח זמני ושרת שמחזיר הפניית 302 (כמו GitHub): ‏`apt update` מאמת את החתימה, ו־`apt install dai-apps` עובד | CI, בתוך קונטיינר trixie |
| **Pinning:** חבילת `sudo` מזויפת בגרסה 99 במאגר **לא** מותקנת | CI, בתוך קונטיינר trixie |
| מאגר לא חתום, או חתום במפתח אחר, נדחה | CI, בתוך קונטיינר trixie |
| ב־VM: ‏`dpkg -S /usr/bin/dai-code` מחזיר `dai-apps`, ו־`dpkg --verify dai-apps` נקי | בדיקת אתחול |
| הורדה אמיתית מ־`releases/latest/download` (מבנה ה־URL הזהה כבר נבדק מקומית עם הפניית 302) | **דורש אימות** בגרסה הרגילה הראשונה |

## 6. סיכונים ומגבלות

- **שרשרת אספקה:** מי ששולט במפתח החתימה או ב־workflow יכול להפיץ קוד לכל המשתמשים. הבקרות: הגנה על הענף `main`, ‏Environment עם אישור ידני ל־job ה־release (מומלץ), ‏pinning, וחתימה על התגים.
- `releases/latest/download` תלוי בכך ש־GitHub שומר על מבנה ה־URL. אם זה משתנה, עוברים ל־Pages.
- אין עדיין snapshots לפני עדכון ("בטל עדכון") — מתוכנן.
- אין SBOM. מומלץ להוסיף (syft, ‏SPDX) בשלב הבא.

---

© 2026 Diamond Rubinny (d.Ai) · D.Ai OS · Apache-2.0

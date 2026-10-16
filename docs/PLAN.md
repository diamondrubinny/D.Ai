# D.Ai OS — אפיון ותוכנית עבודה (טיוטה v0.1)

> סטטוס: **אפיון אושר (v0.2)** — שלב 1 בביצוע.
> כל פריט המסומן ⚠️ דורש אימות מול התיעוד הרשמי לפני מימוש.

---

## 1. סיכום ההבנה

מערכת הפעלה חדשה, קוד פתוח, קלת משקל, מהירה ומאובטחת, הכוללת:
- **עוזר AI מובנה לכתיבת קוד** — ברמת מערכת ההפעלה (לא רק אפליקציה).
- **שליטה קולית** באמצעות Whisper (זיהוי דיבור מקומי, כולל עברית).
- **כל הפיצ'רים הבסיסיים** שמשתמש מצפה להם: שולחן עבודה, קבצים, דפדפן, רשת, Wi‑Fi, Bluetooth, שמע, הדפסה, עדכונים, חנות אפליקציות, הגדרות, נגישות, עברית/RTL.

### החלטת יסוד: לא לכתוב Kernel מאפס
כתיבת Kernel + דרייברים מאפס = שנים של עבודה, ללא תמיכה בחומרה אמיתית (Wi‑Fi, GPU, Bluetooth) ועם סיכון אבטחה גבוה.
**ההמלצה:** הפצת Linux ייעודית ("D.Ai OS") — Kernel של Linux + בסיס הפצה יציב + שכבת D.Ai ייחודית (שולחן עבודה, AI, קול, אבטחה, מתקין).
זה מה שעושות ChromeOS, Pop!_OS, SteamOS ו־Raspberry Pi OS.

---

## 2. החלטות מאושרות

| # | החלטה | פירוט |
|---|-------|-------|
| D1 | בסיס | **Debian 13 "trixie" minimal** |
| D2 | חומרה | **x86_64 (UEFI + BIOS)** ב־MVP; ARM64 אחרי Beta. מינימום 4GB RAM (בסיסי), 8GB (מודל AI קטן), **16GB מומלץ** |
| D3 | AI | **מקומי בלבד כברירת מחדל ובבניית ה־MVP** — אין שום ספק ענן מובנה. כל המידע נשאר במחשב ומוצפן (ראה §2.1) |
| D4 | מהדורות | **D.Ai OS** (משתמשי קצה) + **D.Ai OS Developer** (כלי פיתוח) — אותו בסיס, רשימות חבילות שונות |
| D5 | רישיון | **Apache‑2.0** + DCO (Signed-off-by) — פתוח לכל תורם, כולל שימוש מסחרי, עם הגנת פטנטים |
| D6 | טלמטריה | אין |

### 2.1 מודל "המידע נשאר במחשב ומוצפן"
1. **שכבה 1 — דיסק:** LUKS2 (Argon2id) כברירת מחדל במתקין; אופציה לפתיחה עם TPM2+PIN ⚠️.
2. **שכבה 2 — נתוני D.Ai:** SQLite עם הצפנה ברמת אפליקציה (XChaCha20‑Poly1305) למסרים; מפתח נגזר ונשמר ב־Secret Service (KWallet/gnome-keyring ⚠️) ונפתח רק בהתחברות המשתמש.
3. **שכבה 3 — רשת:** `daid`, llama.cpp ו־whisper.cpp רצים **ללא גישת רשת** (systemd `IPAddressDeny=any` / `PrivateNetwork=yes` + AppArmor). הורדת מודלים מתבצעת בתהליך נפרד `dai-models` עם רשימת SHA‑256 קבועה וחתומה.
4. **שכבה 4 — זיכרון:** אודיו לא נכתב לדיסק; swap מוצפן (חלק מ־LUKS) או zram.
5. ספק ענן (אם יתווסף בעתיד) — תוסף נפרד, כבוי, דורש התקנה והסכמה מפורשת. לא חלק מה־MVP.

### 2.2 המהדורות
| | D.Ai OS | D.Ai OS Developer |
|-|---------|-------------------|
| קהל | משתמשי קצה | מפתחים |
| AI | עוזר כללי, הכתבה קולית, עזרה במערכת | + כתיבת/תיקון קוד, MCP לעורכים, sandbox להרצה |
| כלים | Firefox, Office (Flatpak), מדיה | + git, build-essential, Python, Node.js, Podman, Neovim, gdb |
| גודל ISO משוער | ~2GB ⚠️ | ~3GB ⚠️ |

## 3. MVP — היקף

### בתוך ה־MVP
1. ISO הניתן לאתחול (Live + התקנה) ב־QEMU ועל חומרה אמיתית.
2. שולחן עבודה Wayland קל: פאנל, תפריט, חלונות, התראות, מסך נעילה.
3. אפליקציות בסיס: מנהל קבצים, טרמינל, עורך טקסט, דפדפן (Firefox ESR), צילום מסך, מציג תמונות/PDF, מחשבון.
4. מערכת: רשת/Wi‑Fi, Bluetooth, שמע (PipeWire), הדפסה (CUPS), הגדרות תצוגה/מקלדת/שפה, עברית + פריסת מקלדת עברית.
5. **D.Ai Assistant**: חלון צ'אט + CLI (`dai`) לכתיבה/הסבר/תיקון קוד, עם LLM מקומי.
6. **D.Ai Voice**: Push‑to‑talk → Whisper מקומי → טקסט/פקודה.
7. אבטחה: הצפנת דיסק מלאה, Firewall חוסם נכנס, עדכוני אבטחה אוטומטיים, sandbox לאפליקציות ולקוד שה־AI מריץ.
8. מתקין גרפי (Calamares).

### מחוץ ל־MVP (שלבים מאוחרים)
- עדכונים אטומיים A/B ו־root לקריאה בלבד.
- ARM64 / Raspberry Pi.
- סוכן AI אוטונומי שמבצע שינויים מערכתיים.
- חנות אפליקציות ייעודית (ב־MVP: Flatpak/Flathub דרך GNOME Software או KDE Discover ⚠️).

---

## 4. החלטות טכנולוגיות והחלופות

### 4.1 בסיס ההפצה
| אפשרות | יתרונות | חסרונות |
|--------|---------|---------|
| **Debian 13 minimal ✅ מומלץ** | shim חתום ל־Secure Boot מהקופסה, AppArmor פעיל כברירת מחדל, glibc (נדרש ל־CUDA/ROCm עבור Whisper/LLM), תמיכת חומרה רחבה, LTS ארוך | מעט כבד יותר מ־Alpine |
| Alpine Linux | קל מאוד (musl, OpenRC), קשיח כברירת מחדל | אין shim חתום (משתמש צריך לרשום מפתחות), musl שובר חלק מבינארי GPU, פחות תמיכת נגישות |
| NixOS | שחזוריות מלאה, rollbacks | עקומת למידה, קשה לצרף בינארים חיצוניים |
| Kernel מאפס | שליטה מלאה | שנים של עבודה, אין דרייברים — **לא מומלץ** |

### 4.2 שולחן עבודה
| אפשרות | הערות |
|--------|-------|
| **LXQt 2.x + labwc (Wayland) ✅ מומלץ** | קל, מסורתי (תפריט + פאנל), כולל מנהל קבצים/הגדרות; Qt תומך AT‑SPI ל־Orca; labwc משמש גם ב־Raspberry Pi OS ⚠️ |
| COSMIC (System76, Rust) | מודרני ומהיר; צעיר יחסית — לבדוק בגרות נגישות ⚠️ |
| Sway | Tiling, קל מאוד; לא ידידותי למשתמש רגיל |
| GNOME | הנגישות הטובה ביותר; כבד יחסית |

### 4.3 שכבת ה־AI
| רכיב | בחירה | חלופה | הערות |
|------|-------|-------|-------|
| Daemon מערכתי `daid` | **Rust** | Go / Node.js | בטיחות זיכרון, צריכת משאבים נמוכה |
| ממשק משתמש | **Tauri 2 + TypeScript + React** | Qt/QML, Electron | Tauri קל בהרבה מ־Electron |
| מנוע LLM מקומי | **llama.cpp** (MIT, GGUF) | Ollama | תמיכה ב־CPU, Vulkan, CUDA ⚠️ |
| מודל קוד מקומי | למשל Qwen2.5‑Coder 7B / מודל עדכני אחר | — | **לבדוק רישיון כל מודל** לפני הפצה ⚠️ |
| ענן | **לא ב־MVP** (D3) — תוסף עתידי, כבוי ודורש הסכמה | — | — |
| Whisper | **whisper.cpp** (MIT) | faster‑whisper (Python) | מקומי, תומך עברית; לבחור גודל מודל לפי חומרה ⚠️ |
| VAD | Silero VAD / VAD מובנה ב־whisper.cpp ⚠️ | — | לזיהוי תחילת/סוף דיבור |
| אינטגרציה לעורכים | **MCP server + LSP** | תוספים ייעודיים | VS Code/VSCodium, Neovim, Zed |

### 4.4 בנייה ו־CI
- **mkosi** או **live-build** (Debian) לבניית ה־ISO ⚠️ — המלצה: `live-build` ל־ISO חי, `mkosi` לתמונות בדיקה.
- GitHub Actions: בניית ISO, בדיקות אתחול ב־QEMU (headless), סריקת חולשות, SBOM.
- חתימת חבילות עם מפתח GPG המוחזק ב־Secret Manager בלבד.

---

## 5. ארכיטקטורת מערכת

```
┌────────────────────────────────────────────────────────────────┐
│ אפליקציות: Firefox · מנהל קבצים · טרמינל · עורך · Flatpak apps │
├────────────────────────────────────────────────────────────────┤
│ D.Ai Shell (Tauri)            │ D.Ai CLI  `dai`                 │
│  · Assistant (צ'אט/קוד)       │  · dai ask / fix / explain      │
│  · Voice overlay              │  · dai voice                    │
│  · Permission prompts         │                                 │
├──────────────── D-Bus (session bus, מאומת) ────────────────────┤
│ daid  (Rust, משתמש רגיל — לא root)                             │
│  · Local inference only (D3)        · Policy engine (הרשאות)      │
│  · Tool runner ב-sandbox          · Audit log                   │
│  · MCP server (לעורכי קוד)        · Context (קבצי פרויקט בלבד)  │
├──────────────┬─────────────────────┬───────────────────────────┤
│ llama.cpp    │ whisper.cpp + VAD   │ bubblewrap + Landlock +   │
│ server (local│ (local, 127.0.0.1 / │ seccomp — הרצת קוד של AI   │
│ socket)      │ unix socket)        │                           │
├──────────────┴─────────────────────┴───────────────────────────┤
│ Desktop: labwc + LXQt · PipeWire · NetworkManager · BlueZ · CUPS│
├────────────────────────────────────────────────────────────────┤
│ Debian 13 base · systemd · AppArmor · nftables · LUKS2         │
├────────────────────────────────────────────────────────────────┤
│ Linux kernel (LTS, config מוקשח) · Secure Boot (shim)          │
└────────────────────────────────────────────────────────────────┘
```

### עקרונות
- **AI לעולם לא רץ כ־root.** פעולות מערכתיות עוברות דרך polkit עם אישור משתמש.
- **כל פעולה של AI על קבצים/פקודות** מוצגת ל־diff/preview ודורשת אישור, אלא אם המשתמש הגדיר מדיניות אחרת לתיקייה ספציפית.
- **ה־LLM והקול מאזינים רק ב־unix socket** (לא פורט רשת חיצוני).
- **מיקרופון**: פעיל רק ב־push‑to‑talk, עם אינדיקטור חזותי קבוע. אין hotword "תמיד מאזין" ב־MVP.

---

## 6. User Stories

| ID | כמשתמש… | אני רוצה… | כדי… |
|----|---------|-----------|------|
| US1 | חדש | להתקין מ־USB עם הצפנת דיסק בכמה קליקים | להתחיל לעבוד בבטחה |
| US2 | מפתח | ללחוץ `Super+Space` ולשאול שאלת קוד | לקבל תשובה בלי לעזוב את העורך |
| US3 | מפתח | להגיד "תקן את הבאג בקובץ הזה" בקול | לעבוד בידיים חופשיות |
| US4 | מפתח | לראות diff לפני שה־AI משנה קבצים | לשמור שליטה |
| US5 | מפתח | להריץ קוד שה־AI כתב ב־sandbox | שלא יפגע במערכת |
| US6 | משתמש | להכתיב טקסט בעברית לכל אפליקציה | לכתוב מהר |
| US7 | משתמש | לבחור AI מקומי בלבד | שהקוד והקול שלי לא יצאו מהמחשב |
| US8 | משתמש | לחבר Wi‑Fi, Bluetooth, מדפסת | שימוש יומיומי |
| US9 | משתמש | לקבל עדכוני אבטחה אוטומטית | להישאר מוגן |
| US10 | משתמש עם מוגבלות | קורא מסך, ניגודיות גבוהה, ניווט מקלדת מלא | להשתמש במערכת |
| US11 | משתמש | לראות לוג של כל מה שה־AI עשה | שקיפות |
| US12 | משתמש | למחוק את כל היסטוריית ה־AI בלחיצה | פרטיות |

---

## 7. מסכים וזרימות

1. **Boot → Plymouth → מסך התחברות (greetd/SDDM ⚠️)**
2. **Live session → מתקין Calamares**: שפה → מקלדת → דיסק (+LUKS) → משתמש → התקנה.
3. **First‑run wizard (D.Ai)**: שפה/RTL → נגישות → פרטיות (הסבר: הכל מקומי ומוצפן) → הורדת מודלים (לפי RAM/GPU) → מיקרופון (בדיקה) → סיום.
4. **שולחן עבודה**: פאנל (תפריט, משימות, מגש מערכת, שעון, אינדיקטור מיקרופון/AI).
5. **D.Ai Assistant**: צ'אט, בחירת פרויקט/תיקייה, תצוגת diff, "החל"/"דחה", היסטוריה.
6. **Voice overlay**: לחיצה ארוכה על מקש → גל קול → תמלול חי → אישור/ביצוע.
7. **Permission prompt**: "D.Ai רוצה להריץ `npm test` בתיקייה X" — אשר פעם / תמיד בתיקייה זו / דחה.
8. **הגדרות D.Ai**: מודלים, מדיניות הרשאות, Audit log, מחיקת נתונים.
9. **הגדרות מערכת**: LXQt Configuration Center + הרחבות D.Ai.

---

## 8. מודל נתונים (מקומי, למשתמש)

אחסון: `~/.local/share/dai/` — SQLite, ההיסטוריה מוצפנת במפתח השמור ב־Secret Service.

```sql
CREATE TABLE conversations (
  id TEXT PRIMARY KEY,             -- UUIDv7
  title TEXT,
  project_path TEXT,
  provider TEXT NOT NULL,          -- 'local' | 'anthropic' | ...
  created_at INTEGER NOT NULL,
  updated_at INTEGER NOT NULL
);
CREATE TABLE messages (
  id TEXT PRIMARY KEY,
  conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
  role TEXT NOT NULL CHECK (role IN ('user','assistant','tool')),
  content_encrypted BLOB NOT NULL,
  source TEXT NOT NULL CHECK (source IN ('text','voice')),
  created_at INTEGER NOT NULL
);
CREATE TABLE permissions (
  id TEXT PRIMARY KEY,
  scope_path TEXT NOT NULL,        -- canonical absolute path
  action TEXT NOT NULL,            -- 'read' | 'write' | 'exec' | 'network'
  decision TEXT NOT NULL CHECK (decision IN ('allow','deny')),
  expires_at INTEGER
);
CREATE TABLE audit_log (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ts INTEGER NOT NULL,
  action TEXT NOT NULL,            -- 'file_write' | 'exec' | 'cloud_request' ...
  target TEXT NOT NULL,            -- path / command (ללא סודות)
  decision TEXT NOT NULL,
  provider TEXT
);
```
**אודיו לא נשמר** — מעובד בזיכרון ונמחק מיד לאחר התמלול.

---

## 9. ממשק `daid` (D-Bus: `net.rubinny.Dai1` ⚠️ שם לאישור)

| Method | תיאור | הרשאה |
|--------|-------|-------|
| `Ask(prompt, context_paths[]) → stream` | שאלה/בקשת קוד | משתמש המחובר בלבד (בדיקת UID של peer) |
| `ProposeEdit(path, instruction) → diff` | הצעת שינוי | read לנתיב |
| `ApplyEdit(diff_id)` | החלת שינוי | write + אישור UI |
| `RunCommand(cmd, cwd) → stream` | הרצה ב־sandbox | exec + אישור UI |
| `StartVoice() / StopVoice() → text` | תמלול | גישת מיקרופון דרך PipeWire portal |
| `ListAudit() / ClearHistory()` | שקיפות ומחיקה | משתמש |

ה־CLI וה־MCP server הם לקוחות של אותו API — אין מסלול עוקף להרשאות.

---

## 10. מבנה תיקיות (Monorepo)

```
D.Ai/
├── docs/                    # PLAN.md, ARCHITECTURE.md, THREAT_MODEL.md, PRIVACY.md
├── build/
│   ├── live-build/          # הגדרות בניית ISO (package lists, hooks, includes)
│   ├── kernel/              # config fragments מוקשחים
│   └── scripts/             # build-iso.sh, run-qemu.sh, sign.sh
├── daid/                    # Rust daemon (Cargo workspace)
│   ├── crates/core/         # policy, audit, storage
│   ├── crates/llm/          # llama.cpp client
│   ├── crates/voice/        # whisper.cpp + VAD
│   ├── crates/sandbox/      # bubblewrap/landlock/seccomp
│   └── crates/mcp/          # MCP server
├── dai-cli/                 # Rust CLI `dai`
├── shell/                   # Tauri 2 + TypeScript + React (Assistant, Voice overlay, Settings)
├── desktop/                 # labwc/LXQt themes, keybindings, defaults (RTL)
├── installer/               # Calamares branding & modules
├── packaging/debian/        # .deb packaging לכל רכיב
├── security/                # AppArmor profiles, nftables, sysctl, polkit rules
├── tests/                   # QEMU boot tests, e2e, accessibility
├── .github/workflows/       # CI
├── .env.example
├── LICENSE
└── README.md
```

---

## 11. Threat Model (מקוצר)

| נכס | איום | רמה | בקרה |
|-----|------|-----|------|
| קבצי משתמש | AI מוחק/משנה קבצים (הזיה או prompt injection מתוך קוד/README) | **גבוה** | diff + אישור, sandbox, אין write ללא הרשאה, Audit |
| מערכת | AI מריץ פקודה זדונית | **גבוה** | bubblewrap+Landlock+seccomp, ללא root, ללא רשת כברירת מחדל ב־sandbox |
| מיקרופון | האזנה סמויה | גבוה | Push‑to‑talk, אינדיקטור, portal, אין שמירת אודיו |
| מפתחות API | דליפה ללוגים/ענן | גבוה | Secret Service, מסוננים מלוגים, לא נשלחים לקליינט |
| קוד המשתמש | יציאה מהמחשב | בינוני | אין ספק ענן ב־MVP; רכיבי AI ללא גישת רשת (PrivateNetwork) |
| מודלים שהורדו | מודל/בינארי זדוני (supply chain) | בינוני | Checksums (SHA‑256) קבועים בקוד, HTTPS, רק GGUF (לא pickle) |
| `daid` IPC | אפליקציה אחרת שולטת ב־AI | בינוני | D‑Bus policy, בדיקת peer credentials, AppArmor ל־daid |
| מחשב שנגנב | גישה לדיסק | גבוה | LUKS2 (Argon2id), TPM2 אופציונלי ⚠️ |
| עדכונים | חבילה מזויפת | גבוה | apt חתום, HTTPS, מפתח חתימה ב־HSM/Secret Manager |
| רשת | חיבורים נכנסים | בינוני | nftables: deny inbound, allow established |

### הקשחת בסיס
- Secure Boot (shim + חתימת Kernel/מודולים ⚠️), LUKS2 כברירת מחדל במתקין.
- AppArmor enforce, פרופילים ל־daid, whisper, llama.
- sysctl: `kernel.kptr_restrict=2`, `kernel.dmesg_restrict=1`, `kernel.unprivileged_bpf_disabled=1`, `kernel.yama.ptrace_scope=1`, `fs.protected_*` ⚠️ (לבדוק השפעה על כלי פיתוח/דיבאג).
- `unattended-upgrades` לעדכוני אבטחה.
- Flatpak עם portals לאפליקציות צד שלישי.
- אין SSH server פעיל כברירת מחדל.
- CI: `cargo audit`, `npm audit`, Trivy/Grype על ה־ISO, SBOM (CycloneDX/SPDX).

---

## 12. פרטיות

| סוג מידע | מטרה | בסיס | אחסון | שמירה | צד שלישי |
|----------|------|------|-------|-------|----------|
| הקלטת קול | תמלול | פעולה יזומה של המשתמש | RAM בלבד | נמחקת מיד | אין (מקומי) |
| תמלולים/צ'אט | היסטוריה | בחירת המשתמש | SQLite מוצפן מקומי | עד מחיקה / ברירת מחדל 90 יום (להגדרה) | אין |
| Audit log | שקיפות/אבטחה | אינטרס לגיטימי של המשתמש | מקומי | 180 יום (להגדרה) | אין |

- **אין טלמטריה, אין crash reports אוטומטיים** (opt‑in בלבד בעתיד).
- אתר הפרויקט (אם ייבנה) — יחויב באנר עוגיות, מדיניות פרטיות והצהרת נגישות לפי ההנחיות. ⚠️ דורש בדיקה משפטית.
- רישוי: יש לבדוק תאימות רישיונות של כל רכיב ומודל (GPL/MIT/Apache, רישיונות מודלים, קושחות non‑free). ⚠️ דורש בדיקה משפטית.

---

## 13. נגישות

- Orca (קורא מסך) מותקן ומופעל בקיצור מקלדת כבר ב־Live ובמתקין ⚠️ (לבדוק תמיכת AT‑SPI ב־labwc/LXQt).
- ערכת נושא ניגודיות גבוהה, הגדלת טקסט, זום, הפחתת אנימציות.
- ניווט מקלדת מלא בכל רכיבי D.Ai (Tauri/React: HTML סמנטי, ARIA, focus נראה).
- Voice כאמצעי נגישות: הכתבה ופקודות קוליות לכל המערכת.
- RTL מלא בעברית, פונטים: Noto Sans Hebrew / Rubik / Heebo ⚠️ (בדיקת רישיונות).
- יעד: WCAG 2.1 AA לממשקי D.Ai; ת"י 5568 רלוונטי בעיקר לאתר/שירות — ⚠️ יועץ נגישות.

---

## 14. תוכנית עבודה לפי שלבים

| שלב | תוצר | קריטריון הצלחה |
|-----|------|----------------|
| **0** | אפיון מאושר + ARCHITECTURE/THREAT_MODEL | אישור שלך |
| **1** | ISO מינימלי (Debian + labwc + LXQt + טרמינל) נבנה ב־CI ועולה ב־QEMU | בדיקת boot אוטומטית עוברת |
| **2** | פיצ'רי בסיס: רשת, שמע, Bluetooth, הדפסה, עברית/RTL, Flatpak, אפליקציות בסיס | צ'קליסט פונקציונלי |
| **3** | `daid` + `dai` CLI + llama.cpp מקומי (צ'אט קוד, ללא שינוי קבצים) | `dai ask` עובד offline |
| **4** | Sandbox + Policy + diff/apply + Audit | בדיקות אבטחה ל־sandbox עוברות |
| **5** | Voice: whisper.cpp + PTT + overlay + הכתבה לכל אפליקציה | תמלול עברית/אנגלית תקין |
| **6** | D.Ai Shell (Tauri): Assistant, Settings, First‑run wizard | בדיקות נגישות + e2e |
| **7** | MCP server + אינטגרציה לעורכים | עבודה מ־VSCodium/Neovim |
| **8** | Secure Boot, LUKS ב־Calamares, AppArmor, nftables, sysctl | בדיקת הקשחה (Lynis ⚠️) |
| **9** | עדכונים: apt repo חתום, unattended‑upgrades | עדכון מגרסה לגרסה |
| **10** | Beta: בדיקות חומרה, ביצועים, נגישות, Pen‑test | Checklist פרודקשן |

---

## 15. סיכונים

| סיכון | השפעה | מיתון |
|-------|-------|-------|
| LLM מקומי איטי במחשבים חלשים | חוויה גרועה | בחירת מודל אוטומטית לפי חומרה; מודלים מכווצים (Q4); תמיכת GPU (Vulkan) |
| Prompt injection מקוד/קבצים | פעולות זדוניות | אישור אנושי, sandbox, אין רשת ב־sandbox |
| Wayland + נגישות/הכתבה גלובלית | הכתבה לא עובדת בכל אפליקציה | input-method protocol / virtual-keyboard ⚠️ — POC מוקדם |
| רישיונות מודלים וקושחות | חסימת הפצה | בדיקה משפטית, הורדת מודל בזמן ריצה ולא בתוך ה־ISO |
| גודל ISO | הורדה כבדה | מודלים לא כלולים ב־ISO |
| תחזוקת הפצה | עומס לאורך זמן | מינימום שינויים ל־Debian, רכיבי D.Ai כחבילות נפרדות |

---

## 16. שאלות פתוחות
כל שאלות ההבהרה נענו (ראה §2). שאלות חדשות יירשמו כאן.

## 17. מגבלת סביבת פיתוח
בסביבת הענן של Claude Code הגישה ל־`deb.debian.org` חסומה, לכן בניית ה־ISO ובדיקת האתחול רצות ב־GitHub Actions (`.github/workflows/build-iso.yml`).

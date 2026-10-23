# ספקי בינה מלאכותית חיצוניים (Bring Your Own Key)

מסמך תכנון ובנייה. © 2026 Diamond Rubinny (d.Ai) · D.Ai OS · Apache-2.0

## 1. הרעיון

Diamond, ה־AI של D.Ai, רץ על המחשב ובלי רשת, וזו ברירת המחדל שלא משתנה. אבל לבניית אפליקציות ותוכנות
(D.Ai Forge), לכתיבת קוד (D.Ai Code) ולפיתוח מערכת ההפעלה עצמה, מודל גדול של ספק חיצוני נותן תוצאות טובות
בהרבה. מי שרוצה, מחבר **מפתח API משלו** של כל ספק: Anthropic, OpenAI, Google, Mistral, Groq, DeepSeek, xAI,
OpenRouter, או כל שרת תואם OpenAI (גם Ollama / LM Studio על מחשב אחר ברשת). כל השימושים של Diamond (Forge,
Code, Tune, Heal, MOM, J, Ruby, Command) עוברים דרך אותו לקוח, אז ספק אחד משרת את כולם, לפי משימה.

## 2. העקרונות

1. **כבוי כברירת מחדל.** שום דבר לא יוצא מהמחשב עד שמחברים ספק, ואז רק מה שנשלח אליו.
2. **הסכמה מפורשת, פעם אחת לכל ספק:** `dai-models provider use NAME` מדפיס במילים ברורות שהטקסט של הבקשות
   (שאלות, קוד, תיאורי אפליקציות; לא קבצים, לא סיסמאות) נשלח לשרתי הספק, ודורש הקלדת "כן"/"yes". התאריך נשמר.
3. **המפתח נשאר אצלך:** `~/.config/dai/providers.json` ב־0600, או משתנה סביבה `DAI_PROVIDER_KEY_NAME`;
   המפתח לעולם לא מודפס (מסכה), לא נכתב ליומן, ולא נשלח לשום מקום חוץ מהספק עצמו, ב־HTTPS בלבד.
4. **לפי משימה:** ספק משרת `code` ו/או `general`; דיבור (Voice, Captions) נשאר תמיד מקומי.
5. **רואים מאיפה התשובה:** `dai-ai status` ו־D.Ai Command אומרים "נשלח ל־Anthropic" במקום "רץ במחשב הזה";
   `dai-ai where` מציג מי משרת כל משימה.
6. **נפילה חזרה:** אם הספק לא זמין (רשת, מפתח), חוזרים ל־Diamond המקומי ואומרים זאת; `--no-fallback` כבוי.
7. **אותה אבטחה בכל מקרה:** ה־AI לא מבצע כלום. ב־Tune הוא מחזיר JSON לסכמה, ב־Forge קוד שנבדק בארגז חול.
   ספק חיצוני לא מקבל יותר כוח מהמודל המקומי.

## 3. הפקודות

| פקודה | מה |
|---|---|
| `dai-models provider list` | הספקים המוכרים, מה מוגדר, מי פעיל, איזו משימה |
| `dai-models provider add NAME [--kind openai\|anthropic\|gemini] [--url URL] [--model MODEL]` | ספק מוכר (ברירות מחדל) או "custom" |
| `dai-models provider key NAME` | קורא את המפתח מהקלט (לא מהארגומנטים, לא מההיסטוריה של ה־shell) |
| `dai-models provider use NAME [--tasks code,general]` / `use local` | ההסכמה והבחירה; `local` מחזיר הכול למחשב |
| `dai-models provider test NAME` | בקשה קצרה ("השב במילה אחת: ok") ודיווח |
| `dai-models provider remove NAME` | מוחק הגדרה ומפתח |

## 4. ספקים (ברירות המחדל; **דורש אימות מול התיעוד הרשמי** של כל ספק, שמות מודלים משתנים)

| שם | סוג | כתובת | מודל ברירת מחדל |
|---|---|---|---|
| anthropic | anthropic | `https://api.anthropic.com/v1/messages` | `claude-sonnet-5-5` |
| openai | openai | `https://api.openai.com/v1` | `gpt-5` |
| google | gemini | `https://generativelanguage.googleapis.com/v1beta` | `gemini-2.5-flash` |
| mistral | openai | `https://api.mistral.ai/v1` | `mistral-large-latest` |
| groq | openai | `https://api.groq.com/openai/v1` | `llama-3.3-70b-versatile` |
| deepseek | openai | `https://api.deepseek.com/v1` | `deepseek-chat` |
| xai | openai | `https://api.x.ai/v1` | `grok-4` |
| openrouter | openai | `https://openrouter.ai/api/v1` | `anthropic/claude-sonnet-4.5` |
| custom | openai | `--url` (גם `http://` לרשת מקומית, עם אזהרה) | `--model` |

## 2b. זרימה (שלב 2)

תשובת טקסט מגיעה חלק־חלק כמו מהמודל המקומי: אותה בקשה עם `stream: true` (OpenAI ו־Anthropic) או
`:streamGenerateContent?alt=sse` (Gemini), והתשובה נקראת כ־server-sent events: שורות `data:` עם JSON; הטקסט
נלקח מ־`choices[0].delta.content`, מ־`content_block_delta` עם `text_delta`, או מ־`candidates[0].content.parts`.
מבנה האירועים **דורש אימות מול התיעוד הרשמי** של כל ספק; אירוע שלא מובן נזרק בשקט, אירוע `error` עוצר עם
הודעה. בקשה עם סכמת JSON (Tune, Forge) נשארת תשובה שלמה. גבול הגודל (200 KB) חל על הזרם כולו. נפילה חזרה
ל־Diamond המקומי קורית רק לפני שהגיע חלק ראשון: תשובה שכבר התחילה להופיע לא מוחלפת באחרת.

## 4b. החלפה מהירה: Settings ו־Tune

אחרי שההסכמה ניתנה פעם אחת ב־`dai-models provider use NAME`, אפשר לעבור בין "במחשב הזה" לספק בלי להקליד
שוב: שורת "מי עונה לשאלות של Diamond" ב־D.Ai Settings (פעולת Tune `diamond.provider`, עם undo ביומן),
או משפט: "answer with anthropic", "תענה דרך openrouter", "תענה במחשב הזה". ספק שלא הוסכם לא מופיע ברשימה
והפעולה מסרבת לו, כך שההסכמה עצמה נשארת רק במקום אחד.

## 4c. מדיניות ארגונית: בלי ספקים חיצוניים

בית ספר או משרד שלא רוצה שטקסט ייצא למישהו שם משפט אחד במדיניות (docs/EDU.md §2): `"no external AI providers"`
(‏"בלי ספקי AI חיצוניים"). זו פעולת מערכת `ai.providers_policy` שכותבת `/etc/dai/policy-ai.env`
(‏`DAI_AI_PROVIDERS=forbidden`, root, 0644). מרגע זה, לכל משתמש: הניתוב מחזיר "local" לכל משימה גם אם ספק
הוגדר והוסכם; `dai-models provider use` מסרב עם הסבר; `diamond.provider` ב־Tune וב־Settings מקבל רק "local";
מפתחות שכבר נשמרו נשארים בקובץ של המשתמש (0600) ולא בשימוש. `"allow external AI providers"` מסיר את הקובץ.
כמו שאר המדיניות: לא גבול אבטחה מוחלט (root יכול הכול), אלא ברירת מחדל ארגונית שקופה שמופיעה ב־`dai-tune policy`.

## 5. מה לא

אין חשבון D.Ai, אין proxy של הפרויקט, אין חיוב דרכנו: המפתח והחוזה הם בינך לבין הספק. אין שליחת קבצים או
תמונות (רק טקסט הבקשה).

## 6. בדיקות

יחידה: קובץ ההגדרות (0600, מסכת מפתח, משתנה סביבה); בניית הבקשה לכל סוג (openai / anthropic / gemini, כולל
סכמת JSON); מדיניות (קובץ המדיניות מנתב הכול למקומי, use מסרב, diamond.provider מסרב); זרימה (שלושת מבני האירועים, [DONE], אירוע error, גבול גודל, בלי נפילה חזרה אחרי חלק ראשון); ניתוב לפי
משימה והסכמה; נפילה חזרה; CLI (add/key/use/test/remove/list; `use` בלי "כן" לא מפעיל).
יחידה (Tune/Settings): `diamond.provider` מסרב לספק בלי הסכמה, מחליף active ושומר 0600; שורת הבחירה ב־Settings
עוברת את Raz עם שאר החלון; משפטי הפרסר. ‏VM: `ai: providers off by default` (סטטוס "local", הוספת ספק custom על כתובת שלא קיימת, הסכמה, test נכשל
בבירור, נפילה חזרה למקומי, remove).

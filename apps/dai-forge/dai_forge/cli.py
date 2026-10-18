# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Diamond Rubinny (d.Ai)
"""dai-forge: add capabilities, integrations and apps by writing what you need."""

from __future__ import annotations

import collections
import grp
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

from dai_tune.ai import model_installed
from dai_tune.cli import _color, cmd_undo, execute_plan
from dai_tune.context import Context, detect_lang
from dai_tune.planner import build_plan

from dai_i18n import pick, text

from . import __author__, __version__, apps, paths
from .ai import AIError, author_recipe, generate_app
from .workshop import TestResult, build
from .intent import Intent, classify
from .recipes import (
    MAX_FILE, Library, Recipe, RecipeError, install_requests, load_library, remove_requests, save_user_recipe, validate,
)

ADMIN_GROUPS = {"sudo", "admin", "wheel"}
SOURCE_LABELS = {
    "builtin": ("built-in", "מובנה"),
    "admin": ("administrator", "של המנהל"),
    "user": ("your recipe", "מתכון שלך"),
    "ai": ("written by the local AI", "נכתב ע\"י ה־AI המקומי"),
}


def _l(lang: str, en: str, he: str, **kwargs: object) -> str:
    return text(lang, en, he, **kwargs)


def is_admin() -> bool:
    if os.geteuid() == 0:
        return True
    names = set()
    for gid in os.getgroups():
        try:
            names.add(grp.getgrgid(gid).gr_name)
        except KeyError:
            continue
    return bool(names & ADMIN_GROUPS)


def policy() -> dict:
    try:
        data = json.loads(paths.POLICY_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _ask(lang: str, en: str, he: str, default: bool = False, **kwargs: object) -> bool:
    if not sys.stdin.isatty():
        return default
    answer = input(_l(lang, en, he, **kwargs)).strip().casefold()
    if not answer:
        return default
    return answer in ("y", "yes", "כ", "כן")


def _need_admin(lang: str) -> int:
    print(_color(_l(lang, "✗ Only an administrator (a member of the sudo group) can do this.",
                    "✗ רק מנהל המחשב (חבר בקבוצת sudo) יכול לבצע את זה."), "31"))
    return 1


# --------------------------------------------------------------------------
# Recipes
# --------------------------------------------------------------------------


def _source(recipe: Recipe, lang: str) -> str:
    return pick(lang, *SOURCE_LABELS.get(recipe.source, (recipe.source, recipe.source)))


def apply_recipe(recipe: Recipe, ctx: Context, removing: bool, dry_run: bool, assume_yes: bool) -> int:
    lang = ctx.lang
    requests = remove_requests(recipe) if removing else install_requests(recipe)
    if not requests:
        print(_l(lang, "Nothing to remove for this recipe.", "אין מה להסיר במתכון הזה."))
        return 0
    plan = build_plan(requests, ctx)
    if plan.scoped("system") and not is_admin():
        return _need_admin(lang)
    verb = _l(lang, "Remove", "הסרה") if removing else _l(lang, "Set up", "הקמה")
    heading = f"D.Ai Forge — {verb}: {recipe.title(lang)}  ({_source(recipe, lang)})"
    if recipe.about(lang) and not removing:
        print(recipe.about(lang))
    from_ai = recipe.source == "ai"
    if from_ai:
        print(_color(_l(lang, "AI-written recipe — review every step carefully:",
                        "מתכון שנכתב ע\"י AI — בדקו היטב כל צעד:"), "1;35"))
    return execute_plan(plan, ctx, dry_run=dry_run, assume_yes=assume_yes, from_ai=from_ai,
                        heading=heading, label=f"Forge: {verb} {recipe.title(lang)}")


def handle_unknown(text: str, ctx: Context, library: Library, dry_run: bool, assume_yes: bool) -> int:
    lang = ctx.lang
    if not model_installed():
        apps.record_wish(text, "no-model")
        print(_l(lang, "No recipe matches this request.", "אין מתכון שמתאים לבקשה."))
        print(_l(lang, "Install the local AI so it can write one: dai-models install qwen2.5-0.5b",
                 "התקינו את ה־AI המקומי כדי שיכתוב מתכון: dai-models install qwen2.5-0.5b"))
        print_examples(lang, library)
        return 2
    if not is_admin():
        return _need_admin(lang)
    print(_l(lang, "No recipe matches. Asking the local AI to write one…", "אין מתכון מתאים. מבקש מה־AI המקומי לכתוב אחד…"))
    try:
        recipe = author_recipe(text)
    except AIError as exc:
        apps.record_wish(text, "ai-failed")
        print(_color(f"✗ {exc}", "31"))
        return 1
    status = apply_recipe(recipe, ctx, removing=False, dry_run=dry_run, assume_yes=assume_yes)
    if status == 0 and not dry_run and recipe.id not in library.recipes:
        if _ask(lang, "Save this recipe so you can reuse and share it? [y/N] ",
                "לשמור את המתכון לשימוש חוזר ולשיתוף? [כ/ל] "):
            saved = save_user_recipe(Recipe(**{**recipe.__dict__, "source": "user"}))
            print(_l(lang, "Saved: {saved}", "נשמר: {saved}", saved=saved))
    return status


# --------------------------------------------------------------------------
# Apps
# --------------------------------------------------------------------------


def _may_build(lang: str) -> bool:
    return is_admin() or policy().get("apps_for_all_users") is True


def _progress(lang: str):
    def report(reply: str) -> None:
        if sys.stdout.isatty():
            print(f"\r  {_l(lang, 'writing code…', 'כותב קוד…')} {len(reply):,}", end="", flush=True)
    return report


def _show_result(app: apps.App, findings: list[apps.Finding], lang: str) -> None:
    lines = app.code_path.read_text(encoding="utf-8").count("\n")
    print()
    print(_color(f"✓ {app.title}  ({app.name}, v{app.version}, {lines} {_l(lang, 'lines', 'שורות')})", "1;32"))
    print(f"  {_l(lang, 'Code', 'קוד')}: {app.code_path}")
    if findings:
        print(_l(lang, "  Worth knowing about this code:", "  כדאי לדעת על הקוד:"))
        for finding in findings:
            print("   • " + finding.text(lang))


PERMISSION_TEXT = {
    "network": ("This app asks for INTERNET access. Allow? [y/N] ", "האפליקציה מבקשת גישה לאינטרנט. לאשר? [כ/ל] "),
    "documents": ("This app asks to read and write ~/Documents. Allow? [y/N] ",
                  "האפליקציה מבקשת לקרוא ולכתוב ב־~/Documents. לאשר? [כ/ל] "),
    "downloads": ("This app asks to read and change ~/Downloads. Allow? [y/N] ",
                  "האפליקציה מבקשת לקרוא ולשנות את ~/Downloads. לאשר? [כ/ל] "),
}


def _approve_pending(app: apps.App, lang: str) -> apps.App:
    granted = [p for p in app.pending_permissions if _ask(lang, *PERMISSION_TEXT[p])]
    if granted:
        app = apps.approve(app, granted)
    if app.pending_permissions:
        print(_l(lang, "  Not allowed: {pending_permissions}. Change later: dai-forge app permissions {name}",
                 "  לא אושר: {pending_permissions}. לשינוי: dai-forge app permissions {name}",
                 pending_permissions=', '.join(app.pending_permissions), name=app.name))
    return app


def _test_line(test: TestResult, repairs: int, lang: str) -> str:
    if repairs == 1:
        fixed = _l(lang, " (after 1 fix by the AI)", " (אחרי 1 תיקונים של ה־AI)")
    else:
        fixed = _l(lang, " (after {repairs} fixes by the AI)", " (אחרי {repairs} תיקונים של ה־AI)", repairs=repairs) if repairs else ""
    if test.status == "passed":
        return _color(_l(lang, "  ✓ Tested in the sandbox: it works{fixed}", "  ✓ נבדקה בארגז החול: עובדת{fixed}",
                         fixed=fixed), "32")
    if test.status == "failed":
        last = test.detail.splitlines()[-1][:200] if test.detail else ""
        return _color(_l(lang, "  ⚠ Still crashes when started{fixed}: {last}", "  ⚠ עדיין קורסת בהפעלה{fixed}: {last}",
                         fixed=fixed, last=last), "33")
    return _l(lang, "  · Not tested: {detail}", "  · לא נבדקה: {detail}", detail=test.detail)


def build_app(intent: Intent, ctx: Context, dry_run: bool) -> int:
    lang = ctx.lang
    if not _may_build(lang):
        return _need_admin(lang)
    automation = intent.kind == "automation"
    if automation and intent.schedule is None:
        print(_color(f"✗ {intent.problem or _l(lang, 'no schedule found', 'לא נמצא לוח זמנים')}", "31"))
        return 1
    if intent.kind == "edit":
        current = apps.load(intent.app_name)
        request, kind, existing = intent.instruction, current.kind, current.code_path.read_text(encoding="utf-8")
        print(_l(lang, "Updating {title} with the local AI…", "מעדכן את {title} עם ה־AI המקומי…",
                 title=current.title))
    else:
        current, request, kind, existing = None, intent.text, intent.app_kind, None
        kinds = {"gui": ("desktop app", "אפליקציה"), "cli": ("terminal tool", "כלי טרמינל"), "web": ("web app", "אפליקציית Web")}
        if automation:
            print(_l(lang, "Building an automation ({schedule}) with the local AI…",
                     "בונה אוטומציה ({schedule}) עם ה־AI המקומי…",
                     schedule=intent.schedule.describe(lang)))
        else:
            print(_l(lang, "Building a {kind} with the local AI (on this computer)…",
                     "בונה {kind} עם ה־AI המקומי (במחשב הזה)…",
                     kind=_l(lang, *kinds[kind])))
    if current is not None and current.is_automation:
        automation = True
    def status(stage: str, repair: int, test: TestResult) -> None:
        if stage == "repairing":
            print(_color(_l(lang, "\n  ✗ It crashed when started; the AI is fixing it ({repair}/2)…",
                            "\n  ✗ קרסה בהפעלה; ה־AI מתקן ({repair}/2)…", repair=repair), "33"))
            print("    " + test.detail.splitlines()[-1][:200] if test.detail else "")
        elif stage == "testing":
            print(_l(lang, "\n  Testing it in the sandbox…", "\n  בודק אותה בארגז החול…"))

    try:
        built = build(request, "automation" if automation else kind, existing, progress=_progress(lang), status=status)
    except AIError as exc:
        if current is None:
            apps.record_wish(intent.text, "ai-failed" if model_installed() else "no-model")
        print(_color(f"\n✗ {exc}", "31"))
        return 1
    result, test = built.result, built.test
    print(_test_line(test, built.repairs, lang))
    if dry_run:
        print("\n" + result["code"])
        print(_l(lang, "(dry run — nothing was saved)", "(הרצת ניסיון — לא נשמר דבר)"))
        return 0
    name = current.name if current else apps.unique_name(result["name"])
    title = current.title if current else result["title"]
    permissions = {p: bool(result.get(p)) for p in apps.PERMISSIONS}
    schedule = intent.schedule.to_json() if intent.schedule else (current.schedule if current else None)
    try:
        app, findings = apps.save(name, title, kind, result["code"], permissions, request,
                                  generator="ai", tested=test.status, schedule=schedule if automation else None)
    except apps.AppError as exc:
        print(_color(f"\n✗ {_l(lang, 'The AI code was rejected', 'הקוד של ה־AI נדחה')}: {exc}", "31"))
        return 1
    _show_result(app, findings, lang)
    app = _approve_pending(app, lang)
    if app.is_automation:
        return _activate_automation(app, lang)
    print(_l(lang, "  In the Start menu as “{title}”. Change it: + change {name}: …  ·  Undo: dai-forge app undo {name}",
             "  מופיעה בתפריט התחל בשם „{title}”. לשינוי: + שנה את {name}: …  ·  ביטול: dai-forge app undo {name}",
             title=app.title, name=app.name))
    if _ask(lang, "Run it now? [Y/n] ", "להריץ עכשיו? [כ/ל] ", default=True):
        return run_app(app.name, lang, detach=app.kind != "cli")
    return 0


def _activate_automation(app: apps.App, lang: str) -> int:
    from . import automation
    from .schedule import Schedule

    when = Schedule.from_json(app.schedule)
    describe = when.describe(lang) if when else "?"
    if app.pending_permissions:
        print(_l(lang, "  Not activated: it needs the permissions above.", "  לא הופעלה: היא צריכה את ההרשאות שלמעלה."))
        return 1
    if not _ask(lang, "Run it {describe}? [Y/n] ", "להריץ אותה {describe}? [כ/ל] ", default=True, describe=describe):
        print(_l(lang, "  Saved, not active. Later: dai-forge auto resume {name}",
                 "  נשמרה ולא הופעלה. אחר כך: dai-forge auto resume {name}", name=app.name))
        return 0
    try:
        automation.install(app)
    except apps.AppError as exc:
        print(_color(f"✗ {exc}", "31"))
        return 1
    print(_color(_l(lang, "✓ Active: {describe}. Stop: dai-forge auto pause {name}  ·  Log: dai-forge auto log {name}",
                    "✓ פעילה: {describe}. עצירה: dai-forge auto pause {name}  ·  יומן: dai-forge auto log {name}",
                    describe=describe, name=app.name), "32"))
    return 0


def cmd_auto(args: list[str], lang: str) -> int:
    """dai-forge auto list | run | pause | resume | log | remove <name>"""
    from . import automation
    from .schedule import Schedule

    sub, rest = (args[0] if args else "list"), args[1:]
    try:
        if sub == "list":
            rows = automation.listing()
            if not rows:
                print(_l(lang, "No automations yet. Try: dai-forge \"every morning tell me how much disk space is free\"",
                         "עדיין אין אוטומציות. נסו: dai-forge \"כל בוקר תגיד לי כמה מקום פנוי בדיסק\""))
            for app, state in rows:
                when = Schedule.from_json(app.schedule)
                print(f"  {app.name:<20} {state:<14} {when.describe(lang) if when else '?':<24} {app.title}")
            return 0
        if not rest:
            print(cmd_auto.__doc__)
            return 2
        name = apps.validate_name(rest[0])
        if sub == "run":
            app = apps.load(name)
            return automation.run_background(app, apps.run_argv(app))
        if sub == "pause":
            automation.pause(name)
            print(_l(lang, "✓ Paused. Resume: dai-forge auto resume {name}", "✓ הושהתה. חידוש: dai-forge auto resume {name}",
                     name=name))
            return 0
        if sub == "resume":
            automation.resume(name)
            print("✓")
            return 0
        if sub == "log":
            log = automation.log_path(name)
            print(log.read_text(encoding="utf-8") if log.exists() else _l(lang, "It has not run yet.", "היא עוד לא רצה."))
            return 0
        if sub == "remove":
            automation.uninstall(name)
            return cmd_app(["remove", name], lang)
    except apps.AppError as exc:
        print(_color(f"✗ {exc}", "31"))
        return 1
    print(cmd_auto.__doc__)
    return 2


def run_app(name: str, lang: str, detach: bool = False) -> int:
    try:
        app = apps.load(name)
        argv = apps.run_argv(app)
    except apps.AppError as exc:
        print(_color(f"✗ {exc}", "31"))
        return 1
    if argv[0] == "bwrap" and not shutil.which("bwrap"):
        print(_color(_l(lang, "✗ bubblewrap is missing; apps never run outside the sandbox.",
                        "✗ bubblewrap חסר; אפליקציות לא רצות מחוץ לארגז החול."), "31"))
        return 1
    if app.kind == "web":
        subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         start_new_session=True)
        return 0
    if detach:
        # Through "dai-forge app run" so a crash is still recorded for D.Ai Heal.
        launcher = ["dai-forge", "app", "run", app.name] if shutil.which("dai-forge") else argv
        subprocess.Popen(launcher, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         start_new_session=True)
        return 0
    return run_watched(app, argv)


def run_watched(app: apps.App, argv: list[str]) -> int:
    """Run in the sandbox; pass errors through and keep the last ones in case it crashes."""
    process = subprocess.Popen(argv, stderr=subprocess.PIPE, text=True, errors="replace")
    tail: collections.deque[str] = collections.deque(maxlen=80)
    assert process.stderr is not None
    for line in process.stderr:
        sys.stderr.write(line)
        tail.append(line)
    code = process.wait()
    process.stderr.close()
    if code != 0 and any("Traceback" in line for line in tail):
        apps.record_crash(app, "".join(tail))
    return code


def cmd_app(args: list[str], lang: str) -> int:
    sub = args[0] if args else "list"
    rest = args[1:]
    try:
        if sub == "list":
            items = apps.list_apps()
            if not items:
                print(_l(lang, "No apps yet. Try: dai-forge \"build an app for a shopping list\"",
                         "עדיין אין אפליקציות. נסו: dai-forge \"תבנה אפליקציה לרשימת קניות\""))
            for app in items:
                perms = ", ".join(p for p in apps.PERMISSIONS if app.approved.get(p)) or _l(lang, "no extra permissions", "בלי הרשאות נוספות")
                print(f"  {app.name:<20} v{app.version:<3} {app.kind:<4} {app.title}  [{perms}]")
            return 0
        if sub == "run" and rest:
            if "--background" in rest:
                from . import automation

                app = apps.load(rest[0])
                return automation.run_background(app, apps.run_argv(app))
            return run_app(rest[0], lang)
        if sub == "show" and rest:
            app = apps.load(rest[0])
            print(json.dumps(app.to_json(), ensure_ascii=False, indent=2))
            print(_l(lang, "Versions kept: {versions}", "גרסאות שמורות: {versions}",
                     versions=apps.versions(app)))
            return 0
        if sub == "undo" and rest:
            app = apps.undo(apps.load(rest[0]))
            print(_l(lang, "✓ {name} is back to version {version}", "✓ {name} חזרה לגרסה {version}",
                     name=app.name, version=app.version))
            return 0
        if sub == "permissions" and rest:
            app = apps.load(rest[0])
            if len(rest) == 3 and rest[1] == "revoke":
                apps.revoke(app, rest[2])
                print(_l(lang, "✓ Revoked {rest}", "✓ ההרשאה {rest} בוטלה", rest=rest[2]))
                return 0
            for permission in apps.PERMISSIONS:
                state = "✓" if app.approved.get(permission) else ("?" if app.permissions.get(permission) else "✗")
                print(f"  {state} {permission}")
            _approve_pending(app, lang)
            return 0
        if sub == "remove" and rest:
            app = apps.load(rest[0])
            if not _ask(lang, "Delete {title} and its data? [y/N] ", "למחוק את {title} ואת הנתונים שלה? [כ/ל] ",
                        title=app.title):
                print(_l(lang, "Cancelled.", "בוטל."))
                return 1
            if app.is_automation:
                from . import automation

                automation.uninstall(app.name)
            apps.remove(app)
            print(_l(lang, "✓ Removed", "✓ נמחקה"))
            return 0
        if sub == "add" and len(rest) >= 2:
            return cmd_app_add(rest, lang)
    except apps.AppError as exc:
        print(_color(f"✗ {exc}", "31"))
        return 1
    print("usage: dai-forge app list | run|show|undo|remove <name> | permissions <name> [revoke network|documents]")
    print("       dai-forge app add <name> <file> [--kind gui|cli|web] [--title TEXT] [--network] [--documents]")
    return 2


def cmd_app_add(rest: list[str], lang: str) -> int:
    """Add an app the user wrote themselves (same checks, same sandbox)."""
    name, source = rest[0], Path(rest[1])
    options = rest[2:]
    kind = "web" if source.suffix in (".html", ".htm") else "gui"
    title = name
    if "--kind" in options and options.index("--kind") + 1 < len(options):
        kind = options[options.index("--kind") + 1]
    if "--title" in options and options.index("--title") + 1 < len(options):
        title = options[options.index("--title") + 1]
    permissions = {p: f"--{p}" in options for p in apps.PERMISSIONS}
    schedule = None
    if "--schedule" in options and options.index("--schedule") + 1 < len(options):
        from .schedule import ScheduleError, parse

        try:
            parsed = parse(options[options.index("--schedule") + 1])
        except ScheduleError as exc:
            print(_color(f"✗ {exc}", "31"))
            return 1
        if parsed is None:
            print(_color(_l(lang, "✗ No schedule understood (e.g. \"every day at 18:00\")",
                            "✗ לוח הזמנים לא הובן (למשל \"כל יום ב־18:00\")"), "31"))
            return 1
        kind, schedule = "cli", parsed.to_json()
    if not _may_build(lang):
        return _need_admin(lang)
    code = source.read_text(encoding="utf-8")
    app, findings = apps.save(apps.validate_name(name), title, kind, code, permissions, f"added from {source}", "user",
                              schedule=schedule)
    _show_result(app, findings, lang)
    app = _approve_pending(app, lang)
    if app.is_automation:
        return _activate_automation(app, lang)
    return 0


# --------------------------------------------------------------------------
# Recipe management and help
# --------------------------------------------------------------------------


def cmd_recipe(args: list[str], lang: str) -> int:
    sub = args[0] if args else "list"
    rest = args[1:]
    library = load_library()
    if sub == "list":
        for recipe in sorted(library.recipes.values(), key=lambda r: r.id):
            print(f"  {recipe.id:<14} {recipe.title(lang)}  ({_source(recipe, lang)})")
        for problem in library.problems:
            print(_color("  ! " + problem, "33"))
        return 0
    if sub in ("show", "export") and rest:
        recipe = library.recipes.get(rest[0])
        if recipe is None:
            print(_color(f"✗ {_l(lang, 'no such recipe', 'אין מתכון כזה')}: {rest[0]}", "31"))
            return 1
        text = json.dumps(recipe.to_json(), ensure_ascii=False, indent=2) + "\n"
        if sub == "export" and len(rest) > 1:
            Path(rest[1]).write_text(text, encoding="utf-8")
            print(_l(lang, "✓ Exported to {rest}", "✓ יוצא אל {rest}", rest=rest[1]))
        else:
            print(text, end="")
        return 0
    if sub == "import" and rest:
        try:
            source = Path(rest[0])
            if source.stat().st_size > MAX_FILE:
                raise RecipeError(f"larger than {MAX_FILE // 1024} KB")
            recipe = validate(json.loads(source.read_text(encoding="utf-8")), "user")
        except (OSError, UnicodeDecodeError, json.JSONDecodeError, RecipeError) as exc:
            print(_color(f"✗ {exc}", "31"))
            return 1
        if recipe.id in library.recipes and library.recipes[recipe.id].source != "user":
            print(_color(_l(lang, "✗ '{id}' is a {source} recipe and cannot be replaced.",
                            "✗ '{id}' הוא מתכון {_source} ואי אפשר להחליף אותו.",
                            id=recipe.id, source=library.recipes[recipe.id].source, _source=_source(library.recipes[recipe.id], lang)), "31"))
            return 1
        saved = save_user_recipe(recipe)
        print(_l(lang, "✓ Imported {id} → {saved}", "✓ יובא {id} → {saved}",
                 id=recipe.id, saved=saved))
        return 0
    if sub == "remove" and rest:
        target = paths.user_recipes() / f"{rest[0]}.json"
        if not target.exists():
            print(_color(_l(lang, "✗ Only your own recipes can be removed.", "✗ אפשר למחוק רק מתכונים שלכם."), "31"))
            return 1
        target.unlink()
        print(_l(lang, "✓ Removed", "✓ נמחק"))
        return 0
    print("usage: dai-forge recipe list | show <id> | export <id> [file] | import <file> | remove <id>")
    return 2


def print_examples(lang: str, library: Library | None = None) -> None:
    print(_l(lang, "Examples:", "דוגמאות:"))
    examples = {
        "he": ["תתקין אנטי וירוס", "תוסיף סנכרון קבצים בין המחשבים שלי", "תתקין טלגרם", "הסר אנטי וירוס",
               "תבנה אפליקציה לרשימת קניות", "תבנה אתר של מחשבון משכנתא", "שנה את shopping: הוסף כפתור מחיקה"],
        "en": ["install antivirus", "add file sync between my computers", "install telegram", "remove antivirus",
               "build an app for a shopping list", "build a web page with a mortgage calculator",
               "change shopping: add a delete button"],
    }
    for example in examples.get(lang, examples["en"]):  # requests the rule parser understands
        print(f'  dai-forge "{example}"')
    if library:
        print(_l(lang, "Recipes:", "מתכונים:") + " " + ", ".join(sorted(library.recipes)))


def cmd_help(lang: str) -> int:
    print(_l(lang, "D.Ai Forge — add capabilities, integrations and apps by writing what you need.",
             "D.Ai Forge — מוסיפים יכולות, אינטגרציות ואפליקציות פשוט ע\"י כתיבה."))
    print_examples(lang, load_library())
    print()
    print("  dai-forge list | undo | recipe … | app …   --dry-run --yes")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv[1:])
    lang = detect_lang()
    ctx = Context(lang=lang)
    flags = {a for a in args if a.startswith("--") and a in ("--dry-run", "--yes", "--help", "--version")}
    words = [a for a in args if a not in flags]
    if "--version" in flags:
        print(f"dai-forge {__version__} — {__author__}")
        return 0
    if not words or words[0] in ("help", "עזרה") or "--help" in flags:
        return cmd_help(lang)
    command = words[0]
    try:
        if command == "app":
            return cmd_app(words[1:], lang)
        if command == "recipe":
            return cmd_recipe(words[1:], lang)
        if command in ("auto", "automation", "automations"):
            return cmd_auto(words[1:], lang)
        if command == "list":
            cmd_recipe(["list"], lang)
            print()
            return cmd_app(["list"], lang)
        if command in ("undo", "בטל"):
            return cmd_undo(words[1] if len(words) > 1 else "last", ctx)

        library = load_library()
        intent = classify(" ".join(words), library, (a.name for a in apps.list_apps()))
        if intent.kind in ("recipe", "remove") and intent.recipe is not None:
            return apply_recipe(intent.recipe, ctx, intent.kind == "remove", "--dry-run" in flags, "--yes" in flags)
        if intent.kind in ("app", "edit", "automation"):
            return build_app(intent, ctx, "--dry-run" in flags)
        if intent.kind == "empty":
            return cmd_help(lang)
        return handle_unknown(intent.text, ctx, library, "--dry-run" in flags, "--yes" in flags)
    except (EOFError, KeyboardInterrupt):
        print()
        return 1

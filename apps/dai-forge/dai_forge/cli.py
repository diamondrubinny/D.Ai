# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Diamond Rubinny (d.Ai)
"""dai-forge: add capabilities, integrations and apps by writing what you need."""

from __future__ import annotations

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

from . import __author__, __version__, apps, paths
from .ai import AIError, author_recipe, generate_app
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


def _l(lang: str, en: str, he: str) -> str:
    return he if lang == "he" else en


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


def _ask(lang: str, en: str, he: str, default: bool = False) -> bool:
    if not sys.stdin.isatty():
        return default
    answer = input(_l(lang, en, he)).strip().casefold()
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
    en, he = SOURCE_LABELS.get(recipe.source, (recipe.source, recipe.source))
    return he if lang == "he" else en


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
        print(_color(f"✗ {exc}", "31"))
        return 1
    status = apply_recipe(recipe, ctx, removing=False, dry_run=dry_run, assume_yes=assume_yes)
    if status == 0 and not dry_run and recipe.id not in library.recipes:
        if _ask(lang, "Save this recipe so you can reuse and share it? [y/N] ",
                "לשמור את המתכון לשימוש חוזר ולשיתוף? [כ/ל] "):
            saved = save_user_recipe(Recipe(**{**recipe.__dict__, "source": "user"}))
            print(_l(lang, f"Saved: {saved}", f"נשמר: {saved}"))
    return status


# --------------------------------------------------------------------------
# Apps
# --------------------------------------------------------------------------


def _may_build(lang: str) -> bool:
    return is_admin() or policy().get("apps_for_all_users") is True


def _progress(lang: str):
    def report(chars: int) -> None:
        if sys.stdout.isatty():
            print(f"\r  {_l(lang, 'writing code…', 'כותב קוד…')} {chars:,}", end="", flush=True)
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
}


def _approve_pending(app: apps.App, lang: str) -> apps.App:
    granted = [p for p in app.pending_permissions if _ask(lang, *PERMISSION_TEXT[p])]
    if granted:
        app = apps.approve(app, granted)
    if app.pending_permissions:
        print(_l(lang, f"  Not allowed: {', '.join(app.pending_permissions)}. Change later: dai-forge app permissions {app.name}",
                 f"  לא אושר: {', '.join(app.pending_permissions)}. לשינוי: dai-forge app permissions {app.name}"))
    return app


def build_app(intent: Intent, ctx: Context, dry_run: bool) -> int:
    lang = ctx.lang
    if not _may_build(lang):
        return _need_admin(lang)
    if intent.kind == "edit":
        current = apps.load(intent.app_name)
        request, kind, existing = intent.instruction, current.kind, current.code_path.read_text(encoding="utf-8")
        print(_l(lang, f"Updating {current.title} with the local AI…", f"מעדכן את {current.title} עם ה־AI המקומי…"))
    else:
        current, request, kind, existing = None, intent.text, intent.app_kind, None
        kinds = {"gui": ("desktop app", "אפליקציה"), "cli": ("terminal tool", "כלי טרמינל"), "web": ("web app", "אפליקציית Web")}
        print(_l(lang, f"Building a {kinds[kind][0]} with the local AI (on this computer)…",
                 f"בונה {kinds[kind][1]} עם ה־AI המקומי (במחשב הזה)…"))
    try:
        result = generate_app(request, kind, existing, progress=_progress(lang))
    except AIError as exc:
        print(_color(f"\n✗ {exc}", "31"))
        return 1
    if dry_run:
        print("\n" + result["code"])
        print(_l(lang, "(dry run — nothing was saved)", "(הרצת ניסיון — לא נשמר דבר)"))
        return 0
    name = current.name if current else apps.unique_name(result["name"])
    title = current.title if current else result["title"]
    permissions = {"network": result["network"], "documents": result["documents"]}
    try:
        app, findings = apps.save(name, title, kind, result["code"], permissions, request,
                                  generator="ai")
    except apps.AppError as exc:
        print(_color(f"\n✗ {_l(lang, 'The AI code was rejected', 'הקוד של ה־AI נדחה')}: {exc}", "31"))
        return 1
    _show_result(app, findings, lang)
    app = _approve_pending(app, lang)
    print(_l(lang, f"  In the Start menu as “{app.title}”. Change it: + change {app.name}: …  ·  Undo: dai-forge app undo {app.name}",
             f"  מופיעה בתפריט התחל בשם „{app.title}”. לשינוי: + שנה את {app.name}: …  ·  ביטול: dai-forge app undo {app.name}"))
    if _ask(lang, "Run it now? [Y/n] ", "להריץ עכשיו? [כ/ל] ", default=True):
        return run_app(app.name, lang, detach=app.kind != "cli")
    return 0


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
    if detach or app.kind == "web":
        subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         start_new_session=True)
        return 0
    os.execvp(argv[0], argv)
    return 1  # not reached


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
            return run_app(rest[0], lang)
        if sub == "show" and rest:
            app = apps.load(rest[0])
            print(json.dumps(app.to_json(), ensure_ascii=False, indent=2))
            print(_l(lang, f"Versions kept: {apps.versions(app)}", f"גרסאות שמורות: {apps.versions(app)}"))
            return 0
        if sub == "undo" and rest:
            app = apps.undo(apps.load(rest[0]))
            print(_l(lang, f"✓ {app.name} is back to version {app.version}", f"✓ {app.name} חזרה לגרסה {app.version}"))
            return 0
        if sub == "permissions" and rest:
            app = apps.load(rest[0])
            if len(rest) == 3 and rest[1] == "revoke":
                apps.revoke(app, rest[2])
                print(_l(lang, f"✓ Revoked {rest[2]}", f"✓ ההרשאה {rest[2]} בוטלה"))
                return 0
            for permission in apps.PERMISSIONS:
                state = "✓" if app.approved.get(permission) else ("?" if app.permissions.get(permission) else "✗")
                print(f"  {state} {permission}")
            _approve_pending(app, lang)
            return 0
        if sub == "remove" and rest:
            app = apps.load(rest[0])
            if not _ask(lang, f"Delete {app.title} and its data? [y/N] ", f"למחוק את {app.title} ואת הנתונים שלה? [כ/ל] "):
                print(_l(lang, "Cancelled.", "בוטל."))
                return 1
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
    permissions = {"network": "--network" in options, "documents": "--documents" in options}
    if not _may_build(lang):
        return _need_admin(lang)
    code = source.read_text(encoding="utf-8")
    app, findings = apps.save(apps.validate_name(name), title, kind, code, permissions, f"added from {source}", "user")
    _show_result(app, findings, lang)
    _approve_pending(app, lang)
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
            print(_l(lang, f"✓ Exported to {rest[1]}", f"✓ יוצא אל {rest[1]}"))
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
            print(_color(_l(lang, f"✗ '{recipe.id}' is a {library.recipes[recipe.id].source} recipe and cannot be replaced.",
                            f"✗ '{recipe.id}' הוא מתכון {_source(library.recipes[recipe.id], lang)} ואי אפשר להחליף אותו."), "31"))
            return 1
        saved = save_user_recipe(recipe)
        print(_l(lang, f"✓ Imported {recipe.id} → {saved}", f"✓ יובא {recipe.id} → {saved}"))
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
    for example in examples[lang]:
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
        if intent.kind in ("app", "edit"):
            return build_app(intent, ctx, "--dry-run" in flags)
        if intent.kind == "empty":
            return cmd_help(lang)
        return handle_unknown(intent.text, ctx, library, "--dry-run" in flags, "--yes" in flags)
    except (EOFError, KeyboardInterrupt):
        print()
        return 1

# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Diamond Rubinny (d.Ai)
"""Apps built with D.Ai Forge: storage, versions, checks and the sandbox.

Layout for an app called "shopping":

  ~/Apps/shopping/app.py | index.html     the code (the user's, editable)
  ~/Apps/shopping/dai-app.json            manifest: kind, permissions, version
  ~/Apps/shopping/.versions/<n>/          every previous version (undo)
  ~/.local/share/dai/apps/shopping/       the app's private home in the sandbox
  ~/.local/share/applications/dai-app-shopping.desktop

Apps run under bubblewrap: system files read-only, the code read-only, a
private home, no network unless the user approved it, no X11, no access to
the rest of the user's files. The static checks below are for transparency
(they are shown to the user); the sandbox is the security boundary.
"""

from __future__ import annotations

import ast
import json
import os
import re
import shutil
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from dai_i18n import pick

from . import paths

FORMAT = 1
NAME_RE = re.compile(r"^[a-z][a-z0-9-]{1,30}$")
KINDS = {"gui": "app.py", "cli": "app.py", "web": "index.html"}
MAX_CODE = 64 * 1024
MAX_VERSIONS = 20
PERMISSIONS = ("network", "documents", "downloads")

CSP = (
    '<meta http-equiv="Content-Security-Policy" content="default-src \'self\' \'unsafe-inline\' data: blob:; '
    "connect-src 'none'; form-action 'none'; base-uri 'none'\">"
)
CSP_MARK = "<!-- dai-forge: network blocked -->"


class AppError(ValueError):
    pass


@dataclass
class App:
    name: str
    title: str
    kind: str
    permissions: dict[str, bool] = field(default_factory=lambda: {p: False for p in PERMISSIONS})
    approved: dict[str, bool] = field(default_factory=lambda: {p: False for p in PERMISSIONS})
    version: int = 1
    created: str = ""
    updated: str = ""
    request: str = ""
    generator: str = "ai"
    tested: str = ""  # passed | failed | skipped (docs/EVOLVE.md: the Workshop runs it before you do)
    schedule: dict = field(default_factory=dict)  # automations: dai_forge.schedule.Schedule.to_json()

    @property
    def entry(self) -> str:
        return KINDS[self.kind]

    @property
    def directory(self) -> Path:
        return paths.apps_dir() / self.name

    @property
    def code_path(self) -> Path:
        return self.directory / self.entry

    @property
    def pending_permissions(self) -> list[str]:
        """Permissions the app asks for that the user has not approved."""
        return [p for p in PERMISSIONS if self.permissions.get(p) and not self.approved.get(p)]

    def to_json(self) -> dict[str, Any]:
        return {
            "format": FORMAT,
            "name": self.name,
            "title": self.title,
            "kind": self.kind,
            "entry": self.entry,
            "permissions": self.permissions,
            "approved": self.approved,
            "version": self.version,
            "created": self.created,
            "updated": self.updated,
            "request": self.request,
            "generator": self.generator,
            "tested": self.tested,
            **({"schedule": self.schedule} if self.schedule else {}),
        }

    @property
    def is_automation(self) -> bool:
        return bool(self.schedule)


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S%z")


def clean_title(title: str) -> str:
    """One printable line, safe for a .desktop file."""
    title = re.sub(r"[\x00-\x1f\x7f]", " ", title or "").strip()
    return re.sub(r"\s+", " ", title)[:60] or "App"


def validate_name(name: str) -> str:
    if not isinstance(name, str) or not NAME_RE.match(name):
        raise AppError(f"invalid app name {name!r}: use a-z, 0-9 and '-', 2-31 characters, starting with a letter")
    return name


def unique_name(base: str) -> str:
    base = re.sub(r"[^a-z0-9-]+", "-", (base or "app").casefold()).strip("-")
    if not base or not base[0].isalpha():
        base = "app-" + base
    base = base[:26].rstrip("-") or "app"
    name, n = base, 2
    while (paths.apps_dir() / name).exists():
        name, n = f"{base}-{n}", n + 1
    return validate_name(name)


# --------------------------------------------------------------------------
# Static checks (transparency, not the security boundary)
# --------------------------------------------------------------------------

SENSITIVE_MODULES = {
    "subprocess": ("runs other programs", "מריץ תוכנות אחרות"),
    "ctypes": ("calls native code directly", "קורא לקוד מכונה ישירות"),
    "socket": ("uses the network", "משתמש ברשת"),
    "urllib": ("uses the network", "משתמש ברשת"),
    "http": ("uses the network", "משתמש ברשת"),
    "requests": ("uses the network", "משתמש ברשת"),
    "ftplib": ("uses the network", "משתמש ברשת"),
    "smtplib": ("sends e-mail", "שולח דואר"),
    "pty": ("opens terminals", "פותח טרמינלים"),
    "pickle": ("loads pickled objects (unsafe with untrusted files)", "טוען אובייקטים מסוג pickle (לא בטוח מקבצים זרים)"),
    "marshal": ("loads compiled code", "טוען קוד מקומפל"),
    "importlib": ("imports code dynamically", "טוען קוד באופן דינמי"),
    "multiprocessing": ("starts processes", "מפעיל תהליכים"),
}
SENSITIVE_CALLS = {
    "eval": ("evaluates text as code", "מריץ טקסט כקוד"),
    "exec": ("executes text as code", "מריץ טקסט כקוד"),
    "compile": ("compiles code at run time", "מקמפל קוד בזמן ריצה"),
    "__import__": ("imports code dynamically", "טוען קוד באופן דינמי"),
    "system": ("runs shell commands", "מריץ פקודות shell"),
    "popen": ("runs shell commands", "מריץ פקודות shell"),
    "rmtree": ("deletes whole folders", "מוחק תיקיות שלמות"),
    "fork": ("starts processes", "מפעיל תהליכים"),
    "kill": ("signals other processes", "שולח אותות לתהליכים"),
}
NETWORK_MODULES = {"socket", "urllib", "http", "requests", "ftplib", "smtplib"}


@dataclass(frozen=True)
class Finding:
    what: str
    en: str
    he: str
    network: bool = False

    def text(self, lang: str) -> str:
        return f"{self.what}: {pick(lang, self.en, self.he)}"


BUILTIN_CALLS = {"eval", "exec", "compile", "__import__"}
OS_CALLS = {"system": "system", "popen": "popen", "fork": "fork", "kill": "kill"}


def _sensitive_call(func: ast.expr) -> str:
    """Name of a sensitive call: builtins like eval(), or os.*/shutil.* functions."""
    if isinstance(func, ast.Name):
        return func.id if func.id in BUILTIN_CALLS else ""
    if isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name):
        owner, attr = func.value.id, func.attr
        if owner == "os":
            if attr.startswith(("exec", "spawn")):
                return "system"
            return OS_CALLS.get(attr, "")
        if owner == "shutil" and attr == "rmtree":
            return "rmtree"
    return ""


def check_python(code: str) -> list[Finding]:
    try:
        tree = ast.parse(code)
    except SyntaxError as exc:
        raise AppError(f"the code does not parse (line {exc.lineno}: {exc.msg})") from exc
    found: dict[str, Finding] = {}
    for node in ast.walk(tree):
        modules: list[str] = []
        if isinstance(node, ast.Import):
            modules = [alias.name.split(".")[0] for alias in node.names]
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules = [node.module.split(".")[0]]
        for module in modules:
            if module in SENSITIVE_MODULES:
                en, he = SENSITIVE_MODULES[module]
                found[module] = Finding(module, en, he, module in NETWORK_MODULES)
        if isinstance(node, ast.Call):
            name = _sensitive_call(node.func)
            if name:
                en, he = SENSITIVE_CALLS[name]
                found[name] = Finding(name + "()", en, he)
    return sorted(found.values(), key=lambda f: f.what)


def check_web(code: str) -> list[Finding]:
    if not re.search(r"<html|<!doctype html", code, re.IGNORECASE):
        raise AppError("a web app must be a single HTML document")
    findings = []
    if re.search(r"""(?:src|href)\s*=\s*["']?\s*(?:https?:)?//""", code, re.IGNORECASE):
        findings.append(Finding("remote files", "loads files from the internet", "טוען קבצים מהאינטרנט", True))
    if re.search(r"\b(?:fetch|XMLHttpRequest|WebSocket|EventSource)\b", code):
        findings.append(Finding("network", "talks to servers", "מתקשר עם שרתים", True))
    if re.search(r"\beval\s*\(|new\s+Function\s*\(", code):
        findings.append(Finding("eval", "executes text as code", "מריץ טקסט כקוד"))
    return findings


def check_code(code: str, kind: str) -> list[Finding]:
    if kind not in KINDS:
        raise AppError(f"unknown app kind: {kind}")
    if not code.strip():
        raise AppError("the code is empty")
    if len(code.encode("utf-8")) > MAX_CODE:
        raise AppError(f"the code is larger than {MAX_CODE // 1024} KB")
    return check_web(code) if kind == "web" else check_python(code)


def apply_csp(html: str, network: bool) -> str:
    """Block network access of a web app unless the user approved it.

    Several CSP policies are all enforced, so a policy inside the page can
    only restrict further, never re-open the network.
    """
    html = html.replace(CSP_MARK + CSP, "")
    if network:
        return html
    tag = CSP_MARK + CSP
    head = re.search(r"<head[^>]*>", html, re.IGNORECASE)
    if head:
        return html[: head.end()] + tag + html[head.end():]
    doctype = re.search(r"<!doctype[^>]*>", html, re.IGNORECASE)
    at = doctype.end() if doctype else 0
    return html[:at] + "<head>" + tag + "</head>" + html[at:]


# --------------------------------------------------------------------------
# Storage and versions
# --------------------------------------------------------------------------


def load(name: str) -> App:
    validate_name(name)
    manifest = paths.apps_dir() / name / "dai-app.json"
    try:
        data = json.loads(manifest.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise AppError(f"no app called {name!r}") from exc
    if not isinstance(data, dict) or data.get("format") != FORMAT or data.get("kind") not in KINDS:
        raise AppError(f"{manifest}: not a D.Ai Forge app")

    def flags(value: Any) -> dict[str, bool]:
        value = value if isinstance(value, dict) else {}
        return {p: value.get(p) is True for p in PERMISSIONS}

    return App(
        name=name,
        title=clean_title(str(data.get("title", name))),
        kind=data["kind"],
        permissions=flags(data.get("permissions")),
        approved=flags(data.get("approved")),
        version=int(data.get("version", 1)) if str(data.get("version", 1)).isdigit() else 1,
        created=str(data.get("created", "")),
        updated=str(data.get("updated", "")),
        request=str(data.get("request", ""))[:500],
        generator=str(data.get("generator", "ai"))[:20],
        tested=data.get("tested") if data.get("tested") in ("passed", "failed", "skipped") else "",
        schedule=_schedule(data.get("schedule")),
    )


def _schedule(value: Any) -> dict:
    from .schedule import Schedule

    parsed = Schedule.from_json(value)
    return parsed.to_json() if parsed else {}


def list_apps() -> list[App]:
    root = paths.apps_dir()
    apps = []
    if root.is_dir():
        for manifest in sorted(root.glob("*/dai-app.json")):
            try:
                apps.append(load(manifest.parent.name))
            except AppError:
                continue
    return apps


def _write(path: Path, text: str, mode: int = 0o644) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.tmp")
    tmp.write_text(text, encoding="utf-8")
    os.chmod(tmp, mode)
    tmp.replace(path)


def save_manifest(app: App) -> None:
    _write(app.directory / "dai-app.json", json.dumps(app.to_json(), ensure_ascii=False, indent=2) + "\n")


def _versions_dir(app: App) -> Path:
    return app.directory / ".versions"


def _archive_current(app: App) -> None:
    if not app.code_path.exists():
        return
    target = _versions_dir(app) / str(app.version)
    target.mkdir(parents=True, exist_ok=True)
    shutil.copy2(app.code_path, target / app.entry)
    shutil.copy2(app.directory / "dai-app.json", target / "dai-app.json")
    versions = sorted((int(p.name) for p in _versions_dir(app).iterdir() if p.name.isdigit()))
    for old in versions[:-MAX_VERSIONS]:
        shutil.rmtree(_versions_dir(app) / str(old), ignore_errors=True)


def save(
    name: str,
    title: str,
    kind: str,
    code: str,
    permissions: dict[str, bool],
    request: str = "",
    generator: str = "ai",
    tested: str = "",
    schedule: dict | None = None,
) -> tuple[App, list[Finding]]:
    """Create a new app or a new version of an existing one.

    Approved permissions carry over only as far as they are still requested;
    anything new stays unapproved until the user agrees.
    """
    validate_name(name)
    findings = check_code(code, kind)
    wanted = {p: permissions.get(p) is True for p in PERMISSIONS}
    try:
        app = load(name)
        if app.kind != kind:
            raise AppError(f"{name} is a {app.kind} app; cannot turn it into {kind}")
        _archive_current(app)
        app.version += 1
        app.approved = {p: app.approved.get(p, False) and wanted[p] for p in PERMISSIONS}
    except AppError as exc:
        if (paths.apps_dir() / name).exists() and "no app called" not in str(exc):
            raise
        app = App(name=name, title=clean_title(title), kind=kind, created=_now(), generator=generator)
    app.title = clean_title(title) if title else app.title
    app.permissions = wanted
    app.updated = _now()
    app.request = request[:500]
    app.tested = tested
    if schedule is not None:
        if kind != "cli":
            raise AppError("only terminal-style scripts can run on a schedule")
        app.schedule = _schedule(schedule)
    if kind == "web":
        code = apply_csp(code, network=app.approved.get("network", False))
    _write(app.code_path, code)
    save_manifest(app)
    write_desktop_entry(app)
    paths.app_data_dir(name).mkdir(parents=True, exist_ok=True, mode=0o700)
    return app, findings


def approve(app: App, granted: list[str]) -> App:
    for permission in granted:
        if permission in PERMISSIONS and app.permissions.get(permission):
            app.approved[permission] = True
    if app.kind == "web":
        _write(app.code_path, apply_csp(app.code_path.read_text(encoding="utf-8"), app.approved["network"]))
    save_manifest(app)
    return app


def revoke(app: App, permission: str) -> App:
    if permission not in PERMISSIONS:
        raise AppError(f"unknown permission: {permission}")
    app.approved[permission] = False
    app.permissions[permission] = False
    if app.kind == "web":
        _write(app.code_path, apply_csp(app.code_path.read_text(encoding="utf-8"), False))
    save_manifest(app)
    return app


def versions(app: App) -> list[int]:
    directory = _versions_dir(app)
    return sorted(int(p.name) for p in directory.iterdir() if p.name.isdigit()) if directory.is_dir() else []


def undo(app: App) -> App:
    """Go back to the previous version (the current one is discarded)."""
    previous = versions(app)
    if not previous:
        raise AppError(f"{app.name} has no earlier version")
    source = _versions_dir(app) / str(previous[-1])
    shutil.copy2(source / app.entry, app.code_path)
    shutil.copy2(source / "dai-app.json", app.directory / "dai-app.json")
    restored = load(app.name)
    shutil.rmtree(source)
    write_desktop_entry(restored)
    return restored


def remove(app: App, keep_data: bool = False) -> None:
    desktop = desktop_file(app.name)
    if desktop.exists():
        desktop.unlink()
    shutil.rmtree(app.directory)
    if not keep_data:
        shutil.rmtree(paths.app_data_dir(app.name), ignore_errors=True)


# --------------------------------------------------------------------------
# Start menu entry
# --------------------------------------------------------------------------


def desktop_file(name: str) -> Path:
    return paths.desktop_dir() / f"dai-app-{name}.desktop"


# A window app shows the 🛡 icon in the taskbar: it runs as "dai-app-<name>", the name of its .desktop file.
ICONS = {"gui": "dai-app-sandboxed", "cli": "utilities-terminal", "web": "applications-internet"}
SANDBOX_START = Path(__file__).with_name("sandbox_start.py")


def write_desktop_entry(app: App) -> Path:
    if app.is_automation:  # runs on its schedule, not from the menu (dai-forge auto list)
        path = desktop_file(app.name)
        if path.exists():
            path.unlink()
        return path
    lines = [
        "[Desktop Entry]",
        "Type=Application",
        f"Name={app.title}",
        "Comment=Built with D.Ai Forge · runs in a sandbox",
        "Comment[he]=נבנה עם D.Ai Forge · רץ בארגז חול",
        f"Exec=dai-forge app run {app.name}",
        f"Icon={ICONS[app.kind]}",
        f"Terminal={'true' if app.kind == 'cli' else 'false'}",
        "Categories=Utility;",
        "X-DAi-Forge=true",
    ]
    if app.kind == "gui":
        lines.append(f"StartupWMClass=dai-app-{app.name}")
    path = desktop_file(app.name)
    _write(path, "\n".join(lines) + "\n")
    return path


# --------------------------------------------------------------------------
# Sandbox
# --------------------------------------------------------------------------


def sandbox_argv(app: App, env: dict[str, str] | None = None) -> list[str]:
    """bubblewrap command line for a gui or cli app (approved permissions only)."""
    env = dict(os.environ if env is None else env)
    home = str(Path.home())
    runtime = env.get("XDG_RUNTIME_DIR") or f"/run/user/{os.getuid()}"
    data = paths.app_data_dir(app.name)
    argv = [
        "bwrap",
        "--ro-bind", "/usr", "/usr",
        "--ro-bind", "/etc", "/etc",
        "--symlink", "usr/bin", "/bin",
        "--symlink", "usr/sbin", "/sbin",
        "--symlink", "usr/lib", "/lib",
        "--symlink", "usr/lib64", "/lib64",
        "--proc", "/proc",
        "--dev", "/dev",
        "--tmpfs", "/tmp",
        "--tmpfs", "/run",
        "--perms", "0700", "--dir", runtime,
        "--ro-bind", str(app.directory), "/app",
        "--bind", str(data), home,
        "--unshare-all",
        "--die-with-parent",
        "--new-session",
        "--cap-drop", "ALL",
        "--hostname", "dai-sandbox",
        "--clearenv",
        "--setenv", "HOME", home,
        "--setenv", "PATH", "/usr/bin:/bin",
        "--setenv", "LANG", env.get("LANG", "C.UTF-8"),
        "--setenv", "XDG_RUNTIME_DIR", runtime,
        "--setenv", "DAI_SANDBOX", "1",
        "--chdir", home,
    ]
    if app.approved.get("network"):
        argv[argv.index("--unshare-all") + 1:argv.index("--unshare-all") + 1] = ["--share-net"]
        argv += [
            "--ro-bind-try", "/run/NetworkManager/resolv.conf", "/run/NetworkManager/resolv.conf",
            "--ro-bind-try", "/run/systemd/resolve", "/run/systemd/resolve",
        ]
    for permission, folder in (("documents", "Documents"), ("downloads", "Downloads")):
        if app.approved.get(permission):
            path = str(Path(home) / folder)
            argv += ["--bind", path, path]
    if app.kind == "gui":
        display = env.get("WAYLAND_DISPLAY", "wayland-0")
        if "/" in display:
            raise AppError("unexpected WAYLAND_DISPLAY")
        socket_path = f"{runtime}/{display}"
        argv += [
            "--ro-bind", socket_path, socket_path,
            "--setenv", "WAYLAND_DISPLAY", display,
            "--setenv", "QT_QPA_PLATFORM", "wayland",
            "--setenv", "XDG_SESSION_TYPE", "wayland",
        ]
        for key in ("QT_SCALE_FACTOR", "LANGUAGE", "LC_ALL"):
            if env.get(key):
                argv += ["--setenv", key, env[key]]
    elif env.get("TERM"):
        argv += ["--setenv", "TERM", env["TERM"]]
    if app.kind == "gui" and str(SANDBOX_START).startswith("/usr/"):  # installed: /usr is in the sandbox, read-only
        argv += ["--", "/usr/bin/python3", "-I", str(SANDBOX_START), f"dai-app-{app.name}", f"/app/{app.entry}"]
    else:
        argv += ["--", "/usr/bin/python3", "-I", f"/app/{app.entry}"]
    return argv


def run_argv(app: App, env: dict[str, str] | None = None) -> list[str]:
    if app.pending_permissions:
        raise AppError(f"{app.name} asks for permissions you have not approved: {', '.join(app.pending_permissions)} "
                       f"(dai-forge app permissions {app.name})")
    if app.kind == "web":
        # The browser's own sandbox applies; the CSP blocks the network unless approved.
        return ["xdg-open", app.code_path.as_uri()]
    for permission, folder in (("documents", "Documents"), ("downloads", "Downloads")):
        if app.approved.get(permission):
            (Path.home() / folder).mkdir(exist_ok=True)
    paths.app_data_dir(app.name).mkdir(parents=True, exist_ok=True, mode=0o700)
    return sandbox_argv(app, env)


# --------------------------------------------------------------------------
# Crash reports for D.Ai Heal
# --------------------------------------------------------------------------

MAX_CRASH = 4000


def record_crash(app: App, stderr_tail: str) -> Path:
    """What D.Ai Heal needs to offer a repair: the app, its version and the error (stays on this computer)."""
    directory = paths.heal_dir()
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    path = directory / f"forge-{app.name}.json"
    count = 1
    try:
        count = int(json.loads(path.read_text(encoding="utf-8")).get("count", 0)) + 1
    except (OSError, ValueError, AttributeError):
        pass
    report = {"kind": "forge-app", "name": app.name, "when": time.time(), "detail": stderr_tail[-MAX_CRASH:],
              "count": count, "extra": {"title": app.title, "version": app.version, "app_kind": app.kind}}
    _write(path, json.dumps(report, ensure_ascii=False), mode=0o600)
    return path


def record_wish(text: str, reason: str) -> None:
    """A request Forge could not fulfil: D.Ai Evolve offers it again later (e.g. once a model is installed)."""
    try:
        from dai_evolve.store import record_wish as record
    except ImportError:
        return
    record(text, source="forge", reason=reason)

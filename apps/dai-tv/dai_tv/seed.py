# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Diamond Rubinny (d.Ai)
"""Kodi's add-on database and the channels add-on, prepared before Kodi starts (docs/TV.md stage 3a).

Kodi stores a binary add-on it finds for the first time as *disabled* unless it is in its own manifest
(xbmc/addons/AddonDatabase.cpp, CAddonDatabase::SyncInstalled: `enable = 0` for anything not system or
optional), and then asks. Debian's kodi-pvr-iptvsimple and kodi-inputstream-adaptive are such add-ons. A row
that already exists in `installed` is left as it is, so writing one with enabled=1 before the first start makes
the add-on simply there. The schema below is Kodi 21's (GetSchemaVersion 33, CreateTables, CreateAnalytics,
and the `version` table from dbwrappers/Database.cpp), copied verbatim so Kodi opens the file as its own.

The person's channels: IPTV Simple reads `instance-settings-N.xml` under its addon_data (xbmc/addons/Addon.cpp;
the instance name and enabled ids are in xbmc/addons/IAddon.h); `m3uPathType` 0 is a local file.
"""
from __future__ import annotations

import datetime
import sqlite3
import xml.etree.ElementTree as ET
from pathlib import Path

ADDONS_DB = "userdata/Database/Addons33.db"
SCHEMA_VERSION = 33
ENABLE = ("pvr.iptvsimple", "inputstream.adaptive")
CHANNELS_ADDON = "pvr.iptvsimple"
INSTANCE_FILE = f"userdata/addon_data/{CHANNELS_ADDON}/instance-settings-1.xml"
DISABLED_BY_USER = 1  # AddonDisabledReason::USER: the person's own choice, never overridden

TABLES = (
    "CREATE TABLE addons (id INTEGER PRIMARY KEY, metadata BLOB, addonID TEXT NOT NULL, version TEXT NOT NULL, "
    "name TEXT NOT NULL, summary TEXT NOT NULL, news TEXT NOT NULL, description TEXT NOT NULL)",
    "CREATE TABLE repo (id integer primary key, addonID text, checksum text, lastcheck text, version text, nextcheck TEXT)",
    "CREATE TABLE addonlinkrepo (idRepo integer, idAddon integer)",
    "CREATE TABLE update_rules (id integer primary key, addonID TEXT, updateRule INTEGER)",
    "CREATE TABLE package (id integer primary key, addonID text, filename text, hash text)",
    "CREATE TABLE installed (id INTEGER PRIMARY KEY, addonID TEXT UNIQUE, enabled BOOLEAN, installDate TEXT, "
    "lastUpdated TEXT, lastUsed TEXT, origin TEXT NOT NULL DEFAULT '', disabledReason INTEGER NOT NULL DEFAULT 0)",
    "CREATE INDEX idxAddons ON addons(addonID)",
    "CREATE UNIQUE INDEX ix_addonlinkrepo_1 ON addonlinkrepo ( idAddon, idRepo )",
    "CREATE UNIQUE INDEX ix_addonlinkrepo_2 ON addonlinkrepo ( idRepo, idAddon )",
    "CREATE UNIQUE INDEX idxUpdate_rules ON update_rules(addonID, updateRule)",
    "CREATE UNIQUE INDEX idxPackage ON package(filename)",
    "CREATE TABLE version (idVersion integer, iCompressCount integer)",
)


def seed(kodi_home: Path, addons: tuple[str, ...] = ENABLE, now: datetime.datetime | None = None) -> list[str]:
    """Make sure the add-ons are enabled in Kodi's database (the file made when missing). Returns the ids that
    were inserted or re-enabled; an add-on the person disabled themselves is left alone."""
    path = kodi_home / ADDONS_DB
    path.parent.mkdir(parents=True, exist_ok=True)
    stamp = (now or datetime.datetime.now()).strftime("%Y-%m-%d %H:%M:%S")
    changed: list[str] = []
    fresh = not path.exists()
    with sqlite3.connect(path) as db:
        if fresh:
            for statement in TABLES:
                db.execute(statement)
            db.execute("INSERT INTO version (idVersion, iCompressCount) VALUES (?, 0)", (SCHEMA_VERSION,))
        for addon in addons:
            row = db.execute("SELECT enabled, disabledReason FROM installed WHERE addonID = ?", (addon,)).fetchone()
            if row is None:
                db.execute("INSERT INTO installed (addonID, enabled, installDate) VALUES (?, 1, ?)", (addon, stamp))
                changed.append(addon)
            elif not row[0] and int(row[1] or 0) != DISABLED_BY_USER:
                db.execute("UPDATE installed SET enabled = 1 WHERE addonID = ?", (addon,))
                changed.append(addon)
    path.chmod(0o600)
    return changed


def enabled(kodi_home: Path, addon: str) -> bool | None:
    """What the database says (None when there is no row or no database)."""
    path = kodi_home / ADDONS_DB
    if not path.exists():
        return None
    with sqlite3.connect(path) as db:
        row = db.execute("SELECT enabled FROM installed WHERE addonID = ?", (addon,)).fetchone()
    return bool(row[0]) if row else None


def channels(kodi_home: Path, playlist: Path, name: str = "D.Ai channels", epg: str = "") -> Path:
    """IPTV Simple's first instance: the person's own local playlist (and an EPG address when given)."""
    root = ET.Element("settings", version="2")
    values = [("kodi_addon_instance_name", name), ("kodi_addon_instance_enabled", "true"),
              ("m3uPathType", "0"), ("m3uPath", str(playlist)), ("m3uCache", "false"), ("startNum", "1"),
              ("epgPathType", "1"), ("epgUrl", epg)]
    for key, value in values:
        ET.SubElement(root, "setting", id=key).text = value
    path = kodi_home / INSTANCE_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    ET.indent(root)
    path.write_text(ET.tostring(root, encoding="unicode") + "\n", encoding="utf-8")
    path.chmod(0o600)
    return path


def channels_off(kodi_home: Path) -> bool:
    path = kodi_home / INSTANCE_FILE
    existed = path.exists()
    path.unlink(missing_ok=True)
    return existed


def current_playlist(kodi_home: Path) -> str:
    try:
        root = ET.fromstring((kodi_home / INSTANCE_FILE).read_text(encoding="utf-8"))
    except (OSError, ET.ParseError):
        return ""
    return next((e.text or "" for e in root.iter("setting") if e.get("id") == "m3uPath"), "")

// SPDX-License-Identifier: Apache-2.0
// Copyright (c) 2026 Diamond Rubinny (d.Ai)
// Ruby's rules (docs/BROWSER.md stage 2), with no browser API in them so they can be tested on their own.
"use strict";

// Domains under which people register their own names: "example.co.il" is one site, not "co.il".
const SECOND_LEVEL = new Set([
  "co.il", "org.il", "ac.il", "gov.il", "net.il", "muni.il", "k12.il", "idf.il",
  "co.uk", "org.uk", "ac.uk", "gov.uk", "com.au", "net.au", "org.au", "co.nz", "co.jp", "co.za",
  "com.br", "com.ar", "com.mx", "com.tr", "com.cn", "com.hk", "com.sg", "co.in", "co.kr",
]);

const MAX_SNAPSHOTS = 12;
const SPACES = [
  { key: "work", color: "blue", icon: "briefcase" },
  { key: "home", color: "green", icon: "tree" },
  { key: "school", color: "orange", icon: "circle" },
];

/** "mail.google.com" -> "google.com"; "www.ynet.co.il" -> "ynet.co.il"; IPs and "localhost" stay as they are. */
function siteOf(hostname) {
  const host = String(hostname || "").toLowerCase().replace(/^\.+|\.+$/g, "");
  if (!host || /^[\d.]+$/.test(host) || host.includes(":") || !host.includes(".")) return host;
  const parts = host.split(".");
  const lastTwo = parts.slice(-2).join(".");
  return SECOND_LEVEL.has(lastTwo) && parts.length > 2 ? parts.slice(-3).join(".") : lastTwo;
}

/** The site of a URL, or "" for pages that are not web sites (about:, file:, extensions). */
function siteOfUrl(url) {
  try {
    const parsed = new URL(url);
    return parsed.protocol === "http:" || parsed.protocol === "https:" ? siteOf(parsed.hostname) : "";
  } catch (error) {
    return "";
  }
}

/** The cookies to delete: every cookie of a site that is not remembered and not open in a tab right now. */
function cookiesToForget(cookies, remembered, openSites) {
  const keep = new Set([...remembered, ...openSites].map(siteOf));
  return cookies.filter((cookie) => !keep.has(siteOf(cookie.domain)));
}

/** Sites whose stored data (local storage, IndexedDB) should go, from the hosts seen this session. */
function sitesToForget(seenSites, remembered, openSites) {
  const keep = new Set([...remembered, ...openSites].map(siteOf));
  return [...new Set(seenSites.map(siteOf))].filter((site) => site && !keep.has(site));
}

/** All the host names a site may have stored data under (browsingData filters by exact host name). */
function hostnamesFor(site, seenHosts) {
  return [...new Set([site, `www.${site}`, ...seenHosts.filter((host) => siteOf(host) === site)])];
}

/** A cookie's URL, needed to remove it. */
function cookieUrl(cookie) {
  const host = String(cookie.domain || "").replace(/^\./, "");
  return `${cookie.secure ? "https" : "http"}://${host}${cookie.path || "/"}`;
}

/** Keeps the newest snapshots; an identical one in a row is not stored twice. Private windows never come here. */
function addSnapshot(list, snapshot, max = MAX_SNAPSHOTS) {
  const urls = (s) => JSON.stringify(s.windows);
  const tabs = snapshot.windows.flat().length;
  if (!tabs || (list.length && urls(list[0]) === urls(snapshot))) return list;
  return [snapshot, ...list].slice(0, max);
}

/** Only real web pages are worth restoring. */
function restorable(url) {
  return /^https?:\/\//i.test(String(url || ""));
}

function toggleRemembered(list, site, on) {
  const set = new Set(list.map(siteOf));
  if (on) set.add(siteOf(site));
  else set.delete(siteOf(site));
  return [...set].filter(Boolean).sort();
}

if (typeof module !== "undefined") {
  module.exports = {
    SPACES, MAX_SNAPSHOTS, siteOf, siteOfUrl, cookiesToForget, sitesToForget, hostnamesFor, cookieUrl,
    addSnapshot, restorable, toggleRemembered,
  };
}

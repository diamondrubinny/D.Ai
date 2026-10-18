// SPDX-License-Identifier: Apache-2.0
// Copyright (c) 2026 Diamond Rubinny (d.Ai)
// Ruby's extension: the rules (core.js) and the background against a fake browser.
// Run: node --test apps/dai-ruby/extension-tests/ruby.test.js
"use strict";

const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const dir = path.join(__dirname, "..", "extension");
const core = require(path.join(dir, "core.js"));

test("a site is the name people registered", () => {
  assert.equal(core.siteOf("mail.google.com"), "google.com");
  assert.equal(core.siteOf("www.ynet.co.il"), "ynet.co.il");
  assert.equal(core.siteOf(".bank.co.il"), "bank.co.il");
  assert.equal(core.siteOf("co.il"), "co.il");
  assert.equal(core.siteOf("192.168.1.10"), "192.168.1.10");
  assert.equal(core.siteOf("localhost"), "localhost");
  assert.equal(core.siteOfUrl("https://accounts.google.com/x"), "google.com");
  assert.equal(core.siteOfUrl("about:preferences"), "");
  assert.equal(core.siteOfUrl("file:///home/dana/a.html"), "");
});

test("only what is not remembered and not open is forgotten", () => {
  const cookies = [{ domain: ".google.com" }, { domain: "tracker.example" }, { domain: "www.bank.co.il" },
    { domain: ".news.example" }];
  const gone = core.cookiesToForget(cookies, ["bank.co.il"], ["google.com"]).map((c) => c.domain);
  assert.deepEqual(gone, ["tracker.example", ".news.example"]);
  assert.deepEqual(core.sitesToForget(["a.tracker.example", "b.tracker.example", "bank.co.il"], ["bank.co.il"], []),
    ["tracker.example"]);
  assert.deepEqual(core.hostnamesFor("ynet.co.il", ["m.ynet.co.il", "x.com"]), ["ynet.co.il", "www.ynet.co.il", "m.ynet.co.il"]);
  assert.equal(core.cookieUrl({ domain: ".a.com", secure: true, path: "/x" }), "https://a.com/x");
});

test("snapshots keep the newest, never repeat, never keep empty ones", () => {
  let list = [];
  list = core.addSnapshot(list, { time: 1, windows: [["https://a.com"]] });
  list = core.addSnapshot(list, { time: 2, windows: [["https://a.com"]] });
  list = core.addSnapshot(list, { time: 3, windows: [] });
  assert.equal(list.length, 1);
  for (let i = 0; i < 20; i += 1) list = core.addSnapshot(list, { time: i, windows: [[`https://s${i}.com`]] });
  assert.equal(list.length, core.MAX_SNAPSHOTS);
  assert.equal(list[0].windows[0][0], "https://s19.com");
  assert.equal(core.restorable("javascript:alert(1)"), false);
  assert.deepEqual(core.toggleRemembered(["b.com"], "www.a.com", true), ["a.com", "b.com"]);
  assert.deepEqual(core.toggleRemembered(["a.com", "b.com"], "a.com", false), ["b.com"]);
});

function fakeBrowser() {
  const listeners = {};
  const on = (name) => ({ addListener: (fn) => { listeners[name] = fn; } });
  const state = {
    storage: { remembered: [], snapshots: [], cleaning: true },
    cookies: [], removed: [], cleared: [], tabs: [], created: [], identities: [],
  };
  const browser = {
    storage: { local: {
      get: async (defaults) => ({ ...defaults, ...state.storage }),
      set: async (values) => { Object.assign(state.storage, values); },
    } },
    cookies: {
      getAllCookieStores: async () => [{ id: "firefox-default" }],
      getAll: async () => state.cookies.filter((c) => !state.removed.includes(c)),
      remove: async (details) => {
        const cookie = state.cookies.find((c) => c.name === details.name && details.url.includes(c.domain.replace(/^\./, "")));
        if (cookie) state.removed.push(cookie);
      },
    },
    browsingData: { remove: async (filter) => { state.cleared.push(...filter.hostnames); } },
    tabs: {
      onUpdated: on("updated"), onRemoved: on("removed"),
      query: async () => state.tabs,
      create: async (details) => { state.created.push(details); },
    },
    windows: { getAll: async () => [], create: async () => null },
    commands: { onCommand: on("command") },
    alarms: { create: () => null, onAlarm: on("alarm") },
    runtime: { id: "ruby@dai-os.github.io", onMessage: on("message") },
    i18n: { getMessage: (key) => ({ space_work: "Work" }[key] || key) },
    contextualIdentities: {
      query: async ({ name }) => state.identities.filter((i) => i.name === name),
      create: async (details) => { const id = { ...details, cookieStoreId: "firefox-container-1" }; state.identities.push(id); return id; },
    },
  };
  return { browser, listeners, state };
}

async function loadBackground(fake) {
  const timers = [];
  const context = vm.createContext({
    browser: fake.browser, URL, console, Promise,
    setTimeout: (fn) => { timers.push(fn); return timers.length; },
    clearTimeout: () => null,
  });
  for (const file of ["core.js", "background.js"]) {
    vm.runInContext(fs.readFileSync(path.join(dir, file), "utf8"), context, { filename: file });
  }
  await new Promise((resolve) => setImmediate(resolve));
  return { timers, context };
}

const cookie = (domain, name = "id") => ({ domain, name, secure: true, path: "/", storeId: "firefox-default" });

test("start-up cleans what was left, but keeps remembered and open sites", async () => {
  const fake = fakeBrowser();
  fake.state.storage.remembered = ["bank.co.il"];
  fake.state.tabs = [{ id: 1, url: "https://mail.google.com/inbox", incognito: false }];
  fake.state.cookies = [cookie(".google.com"), cookie("www.bank.co.il"), cookie(".tracker.example")];
  await loadBackground(fake);
  await new Promise((resolve) => setImmediate(resolve));
  assert.deepEqual(fake.state.removed.map((c) => c.domain), [".tracker.example"]);
});

test("closing a site's last tab forgets it, unless it is remembered", async () => {
  const fake = fakeBrowser();
  const { timers } = await loadBackground(fake);
  fake.state.cookies = [cookie(".news.example"), cookie(".bank.co.il")];  // set while browsing
  fake.listeners.updated(5, { url: "https://www.news.example/a" }, { incognito: false });
  fake.listeners.updated(6, { url: "https://bank.co.il/" }, { incognito: false });
  await fake.listeners.message({ type: "remember", site: "bank.co.il", on: true }, { id: "ruby@dai-os.github.io" });
  fake.listeners.removed(5);
  fake.listeners.removed(6);
  for (const fire of timers.splice(0)) await fire();
  assert.deepEqual(fake.state.removed.map((c) => c.domain), [".news.example"]);
  assert.ok(fake.state.cleared.includes("www.news.example"));
  assert.ok(!fake.state.cleared.some((h) => h.includes("bank")));
});

test("private windows are never tracked; messages from others are ignored; spaces open containers", async () => {
  const fake = fakeBrowser();
  fake.state.cookies = [cookie(".secret.example")];
  const { timers } = await loadBackground(fake);
  fake.listeners.updated(9, { url: "https://secret.example/" }, { incognito: true });
  fake.listeners.removed(9);
  assert.equal(timers.length, 0);
  assert.equal(await fake.listeners.message({ type: "clean-all" }, { id: "evil@example" }), null);
  await fake.listeners.message({ type: "space", key: "work" }, { id: "ruby@dai-os.github.io" });
  await fake.listeners.message({ type: "space", key: "work" }, { id: "ruby@dai-os.github.io" });
  assert.equal(fake.state.identities.length, 1);  // created once, then reused
  assert.deepEqual(fake.state.created.map((t) => t.cookieStoreId), ["firefox-container-1", "firefox-container-1"]);
});

test("both languages have every message, with the same placeholders", () => {
  const en = JSON.parse(fs.readFileSync(path.join(dir, "_locales/en/messages.json"), "utf8"));
  const he = JSON.parse(fs.readFileSync(path.join(dir, "_locales/he/messages.json"), "utf8"));
  assert.deepEqual(Object.keys(en).sort(), Object.keys(he).sort());
  for (const key of Object.keys(en)) {
    assert.deepEqual(Object.keys(en[key].placeholders || {}), Object.keys(he[key].placeholders || {}), key);
  }
  const html = fs.readFileSync(path.join(dir, "popup/popup.html"), "utf8");
  for (const [, key] of html.matchAll(/data-i18n="([a-z_]+)"/g)) assert.ok(en[key], key);
  const manifest = JSON.parse(fs.readFileSync(path.join(dir, "manifest.json"), "utf8"));
  assert.equal(manifest.incognito, "not_allowed");
  assert.ok(manifest.permissions.includes("nativeMessaging"));  // stage 3: Diamond, and only through Ruby's own host
  const code = ["background.js", "core.js", "popup/popup.js"].map((f) => fs.readFileSync(path.join(dir, f), "utf8")).join("\n");
  assert.deepEqual([...code.matchAll(/sendNativeMessage\(([^,]+),/g)].map((m) => m[1].trim()), ["DIAMOND_HOST"]);
  assert.ok(!/innerHTML|insertAdjacentHTML|outerHTML/.test(code));  // answers and pages are shown as text only
});

test("the page's visible text, never its forms or hidden parts", () => {
  const text = (value) => ({ nodeType: 3, nodeValue: value });
  const el = (tagName, childNodes, attrs = {}) => ({ nodeType: 1, tagName, childNodes, hidden: !!attrs.hidden,
    getAttribute: (name) => (name in attrs ? attrs[name] : null) });
  const page = el("BODY", [
    el("H1", [text("Bank")]),
    el("P", [text("Your   balance")]),
    el("FORM", [el("LABEL", [text("Password")]), el("INPUT", [])]),
    el("DIV", [text("a private note")], { contenteditable: "true" }),
    el("DIV", [text("menu")], { "aria-hidden": "true" }),
    el("DIV", [text("old")], { hidden: true }),
    el("SCRIPT", [text("steal()")]),
    el("P", [text("Thanks")]),
  ]);
  assert.equal(core.visibleText(page, 1000), "Bank\nYour balance\nThanks");
  assert.equal(core.visibleText(el("P", [text("x".repeat(50))]), 10).length, 10);
  // It runs alone in the page: nothing from core.js may be needed.
  const alone = new Function(`return (${core.visibleText.toString()})`)();
  assert.equal(alone(page, 1000), "Bank\nYour balance\nThanks");
});

test("Diamond only when asked, only for the open web page, through Ruby's host", async () => {
  const fake = fakeBrowser();
  const sent = [];
  fake.browser.tabs.executeScript = async (id, details) => { sent.push(["script", id, details.code.length > 0]); return ["Hello page"]; };
  fake.browser.runtime.sendNativeMessage = async (host, message) => { sent.push(["native", host, message]); return { ok: true, text: "Hi" }; };
  fake.state.tabs = [{ id: 3, url: "https://news.example/a", incognito: false }];
  await loadBackground(fake);
  const ruby = { id: "ruby@dai-os.github.io" };
  assert.deepEqual(await fake.listeners.message({ type: "diamond", action: "summarize", lang: "he" }, ruby),
                   { ok: true, text: "Hi" });
  const plain = (value) => JSON.parse(JSON.stringify(value));  // objects made inside the vm come from another realm
  assert.deepEqual(plain(sent.at(-1)), ["native", "io.github.dai_os.ruby_diamond",
                                        { action: "summarize", text: "Hello page", lang: "he" }]);
  assert.deepEqual(plain(await fake.listeners.message({ type: "diamond", action: "rm -rf" }, ruby)),
                   { ok: false, error: "invalid" });
  assert.equal(await fake.listeners.message({ type: "diamond", action: "summarize" }, { id: "evil@example" }), null);
  fake.state.tabs = [{ id: 4, url: "about:preferences", incognito: false }];
  assert.deepEqual(plain(await fake.listeners.message({ type: "diamond", action: "explain" }, ruby)),
                   { ok: false, error: "not_a_page" });
  fake.state.tabs = [{ id: 5, url: "https://bank.example", incognito: false }];
  fake.browser.runtime.sendNativeMessage = async () => { throw new Error("No such native application"); };
  assert.deepEqual(plain(await fake.listeners.message({ type: "diamond", action: "explain" }, ruby)),
                   { ok: false, error: "unavailable" });
});

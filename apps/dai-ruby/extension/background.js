// SPDX-License-Identifier: Apache-2.0
// Copyright (c) 2026 Diamond Rubinny (d.Ai)
// Ruby's background (docs/BROWSER.md stage 2):
// - automatic cleaning: a site's cookies and stored data go when its last tab closes, and everything not
//   remembered goes when Ruby starts (in case it was closed before the cleaning finished);
// - "Remember this site" keeps a site signed in;
// - spaces (work, home, school) as containers, one key each;
// - a snapshot of the open tabs every 5 minutes, kept on this computer only.
// Nothing is sent anywhere; nothing runs in private windows except Firefox's own cleaning.
"use strict";

const CLOSE_DELAY_MS = 15000;      // a quick reload or a link in a new tab does not lose the sign-in
const seenHosts = new Set();       // web hosts this session, for local storage and IndexedDB cleaning
const tabSites = new Map();        // tab id -> site
const pending = new Map();         // site -> timer of a planned cleaning

async function settings() {
  const stored = await browser.storage.local.get({ remembered: [], snapshots: [], cleaning: true });
  return stored;
}

function openSites() {
  return [...new Set(tabSites.values())].filter(Boolean);
}

async function allCookies() {
  const stores = await browser.cookies.getAllCookieStores();
  const lists = await Promise.all(stores.map((store) =>
    browser.cookies.getAll({ storeId: store.id, firstPartyDomain: null, partitionKey: {} }).catch(() => [])));
  return lists.flat();
}

async function removeCookies(cookies) {
  await Promise.all(cookies.map((cookie) => browser.cookies.remove({
    url: cookieUrl(cookie), name: cookie.name, storeId: cookie.storeId,
    firstPartyDomain: cookie.firstPartyDomain, partitionKey: cookie.partitionKey,
  }).catch(() => null)));
  return cookies.length;
}

async function forgetSites(sites) {
  if (!sites.length) return 0;
  const hosts = sites.flatMap((site) => hostnamesFor(site, [...seenHosts]));
  await browser.browsingData.remove({ hostnames: hosts }, { localStorage: true, indexedDB: true, serviceWorkers: true })
    .catch(() => null);
  const gone = new Set(sites);
  return removeCookies((await allCookies()).filter((cookie) => gone.has(siteOf(cookie.domain))));
}

/** Everything that is not remembered and not open: at start-up, and on request. */
async function cleanAll() {
  const { remembered, cleaning } = await settings();
  if (!cleaning) return 0;
  const cookies = cookiesToForget(await allCookies(), remembered, openSites());
  const stale = sitesToForget([...seenHosts, ...cookies.map((c) => c.domain)], remembered, openSites());
  await browser.browsingData.remove({ hostnames: stale.flatMap((s) => hostnamesFor(s, [...seenHosts])) },
    { localStorage: true, indexedDB: true }).catch(() => null);
  return removeCookies(cookies);
}

function planCleaning(site) {
  if (!site) return;
  clearTimeout(pending.get(site));
  pending.set(site, setTimeout(async () => {
    pending.delete(site);
    const { remembered, cleaning } = await settings();
    if (!cleaning || remembered.includes(site) || openSites().includes(site)) return;
    await forgetSites([site]);
  }, CLOSE_DELAY_MS));
}

function track(tabId, url, incognito) {
  if (incognito) return;
  const site = siteOfUrl(url);
  const before = tabSites.get(tabId);
  if (site) {
    tabSites.set(tabId, site);
    try { seenHosts.add(new URL(url).hostname); } catch (error) { /* not a web page */ }
  } else {
    tabSites.delete(tabId);
  }
  if (before && before !== site) planCleaning(before);   // left the site in this tab
}

browser.tabs.onUpdated.addListener((tabId, change, tab) => {
  if (change.url) track(tabId, change.url, tab.incognito);
});
browser.tabs.onRemoved.addListener((tabId) => {
  const site = tabSites.get(tabId);
  tabSites.delete(tabId);
  planCleaning(site);
});

// Spaces: a container per space, created the first time it is used.
async function openSpace(key) {
  const space = SPACES.find((s) => s.key === key);
  if (!space || !browser.contextualIdentities) return;
  const name = browser.i18n.getMessage(`space_${key}`);
  const found = await browser.contextualIdentities.query({ name });
  const identity = found[0] || await browser.contextualIdentities.create({ name, color: space.color, icon: space.icon });
  await browser.tabs.create({ cookieStoreId: identity.cookieStoreId });
}

browser.commands.onCommand.addListener((command) => {
  if (command.startsWith("space-")) openSpace(command.slice(6));
});

// Session snapshots, every 5 minutes, normal windows only.
async function takeSnapshot() {
  const windows = await browser.windows.getAll({ populate: true, windowTypes: ["normal"] });
  const snapshot = {
    time: Date.now(),
    windows: windows.filter((w) => !w.incognito)
      .map((w) => w.tabs.map((t) => t.url).filter(restorable)).filter((tabs) => tabs.length),
  };
  const { snapshots } = await settings();
  await browser.storage.local.set({ snapshots: addSnapshot(snapshots, snapshot) });
}

async function restore(index) {
  const { snapshots } = await settings();
  const snapshot = snapshots[index];
  if (!snapshot) return false;
  for (const urls of snapshot.windows) {
    await browser.windows.create({ url: urls.filter(restorable) });
  }
  return true;
}

browser.alarms.create("snapshot", { periodInMinutes: 5 });
browser.alarms.onAlarm.addListener((alarm) => { if (alarm.name === "snapshot") takeSnapshot(); });

// The popup asks; only these messages are answered.
// Diamond, only when asked (docs/BROWSER.md §11): the visible text of the current tab, never its forms, goes to
// the local AI through the native host, which only Ruby may start. Private windows never get here.
const DIAMOND_HOST = "io.github.dai_os.ruby_diamond";

async function askDiamond(action, lang) {
  if (!DIAMOND_ACTIONS.includes(action)) return { ok: false, error: "invalid" };
  const [tab] = await browser.tabs.query({ active: true, currentWindow: true });
  if (!tab || tab.incognito || !siteOfUrl(tab.url || "")) return { ok: false, error: "not_a_page" };
  const [text] = await browser.tabs.executeScript(tab.id, {
    code: `(${visibleText.toString()})(document.body, ${MAX_PAGE_TEXT});`,
  });
  if (!text) return { ok: false, error: "empty" };
  try {
    return await browser.runtime.sendNativeMessage(DIAMOND_HOST, { action, text: String(text), lang });
  } catch (error) {
    return { ok: false, error: "unavailable" };
  }
}

browser.runtime.onMessage.addListener(async (message, sender) => {
  if (sender.id !== browser.runtime.id) return null;
  const { remembered, snapshots, cleaning } = await settings();
  switch (message && message.type) {
    case "state": {
      const site = siteOf(message.site);
      const cookies = site ? (await allCookies()).filter((c) => siteOf(c.domain) === site).length : 0;
      return { site, remembered: remembered.includes(site), cookies, cleaning,
               snapshots: snapshots.map((s) => ({ time: s.time, tabs: s.windows.flat().length })) };
    }
    case "remember":
      await browser.storage.local.set({ remembered: toggleRemembered(remembered, message.site, !!message.on) });
      return true;
    case "forget":
      return forgetSites([siteOf(message.site)]);
    case "cleaning":
      await browser.storage.local.set({ cleaning: !!message.on });
      return true;
    case "clean-all":
      return cleanAll();
    case "space":
      await openSpace(String(message.key));
      return true;
    case "restore":
      return restore(Number(message.index));
    case "diamond":
      return askDiamond(String(message.action), String(message.lang || "en"));
    default:
      return null;
  }
});

// Start-up: learn the open tabs, then clean what is left from last time.
(async () => {
  const tabs = await browser.tabs.query({});
  tabs.forEach((tab) => track(tab.id, tab.url, tab.incognito));
  await cleanAll();
})();

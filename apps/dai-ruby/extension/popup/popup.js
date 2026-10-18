// SPDX-License-Identifier: Apache-2.0
// Copyright (c) 2026 Diamond Rubinny (d.Ai)
// Ruby's shield: the current site (remember / forget), automatic cleaning, spaces and earlier tabs.
"use strict";

const say = (key, ...values) => browser.i18n.getMessage(key, values.map(String));
const $ = (id) => document.getElementById(id);
let site = "";

function status(text) {
  $("status").textContent = text;
}

async function ask(message) {
  return browser.runtime.sendMessage(message);
}

async function load() {
  const lang = browser.i18n.getUILanguage();
  document.documentElement.lang = lang;
  document.documentElement.dir = browser.i18n.getMessage("@@bidi_dir");
  document.querySelectorAll("[data-i18n]").forEach((node) => { node.textContent = say(node.dataset.i18n); });

  const [tab] = await browser.tabs.query({ active: true, currentWindow: true });
  let host = "";
  try {
    const url = new URL(tab.url);
    host = url.protocol.startsWith("http") ? url.hostname : "";
  } catch (error) { /* not a web page */ }
  const state = await ask({ type: "state", site: host });
  site = state.site;
  $("site").textContent = site || say("no_site");
  $("remember").checked = state.remembered;
  $("remember").disabled = !site;
  $("forget").disabled = !site;
  $("cookies").textContent = site ? say("cookies", state.cookies) : "";
  $("cleaning").checked = state.cleaning;

  const list = $("sessions");
  list.textContent = "";
  if (!state.snapshots.length) {
    const empty = document.createElement("li");
    empty.className = "muted";
    empty.textContent = say("no_sessions");
    list.append(empty);
  }
  state.snapshots.forEach((snapshot, index) => {
    const row = document.createElement("li");
    const label = document.createElement("span");
    const when = new Date(snapshot.time).toLocaleString(lang, { dateStyle: "short", timeStyle: "short" });
    label.textContent = say("session_row", when, snapshot.tabs);
    const button = document.createElement("button");
    button.type = "button";
    button.textContent = say("restore");
    button.setAttribute("aria-label", `${say("restore")}: ${label.textContent}`);
    button.addEventListener("click", () => ask({ type: "restore", index }));
    row.append(label, button);
    list.append(row);
  });
}

$("remember").addEventListener("change", async (event) => {
  await ask({ type: "remember", site, on: event.target.checked });
});
$("forget").addEventListener("click", async () => {
  const count = await ask({ type: "forget", site });
  status(say("forgotten", count));
  await load();
});
$("cleaning").addEventListener("change", (event) => ask({ type: "cleaning", on: event.target.checked }));
$("clean-all").addEventListener("click", async () => status(say("cleaned", await ask({ type: "clean-all" }))));
document.querySelectorAll("[data-space]").forEach((button) => {
  button.addEventListener("click", () => ask({ type: "space", key: button.dataset.space }));
});

load();

/* Starts an isolated Python server. DOM integration, not a visual/layout test.
 * Set HEXBOUND_TEST_URL to use an existing disposable test server instead.
 */
const { JSDOM } = require("jsdom");
const { readFileSync, mkdtempSync, rmSync } = require("node:fs");
const { tmpdir } = require("node:os");
const { spawn } = require("node:child_process");
const { resolve } = require("node:path");
const assert = require("node:assert/strict");
const base = process.env.HEXBOUND_TEST_URL || "http://127.0.0.1:8124";
const temporary = mkdtempSync(resolve(tmpdir(), "hexbound-ui-"));
const server = process.env.HEXBOUND_TEST_URL
  ? null
  : spawn(
      process.env.PYTHON || "python",
      ["-m", "uvicorn", "backend.app:app", "--port", "8124"],
      {
        cwd: resolve(__dirname, ".."),
        env: {
          ...process.env,
          HEXBOUND_DB: resolve(temporary, "test.sqlite3"),
          LLM_API_KEY: "",
          LLM_MODEL: "",
        },
        stdio: "ignore",
      },
    );
const source = readFileSync(resolve(__dirname, "../frontend/app.js"), "utf8");
const windows = [],
  sockets = [];
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
async function waitFor(fn, label) {
  for (let i = 0; i < 100; i++) {
    if (fn()) return;
    await sleep(30);
  }
  throw new Error(`Timeout: ${label}`);
}
async function page() {
  const dom = new JSDOM('<div id="app"></div><div id="toast" hidden></div>', {
    url: base,
    runScripts: "outside-only",
    pretendToBeVisual: true,
  });
  const w = dom.window;
  windows.push(w);
  w.fetch = (url, options) => fetch(new URL(url, base), options);
  w.WebSocket = class extends WebSocket {
    constructor(url) {
      super(url);
      sockets.push(this);
    }
  };
  // Non-secure LAN origins do not expose randomUUID; exercise that path.
  Object.defineProperty(w.crypto, "randomUUID", { value: undefined });
  w.eval(source);
  await waitFor(() => w.document.querySelector("#create"), "home");
  return w;
}
const click = (w, selector) => {
  const e = w.document.querySelector(selector);
  assert(e, selector);
  assert(!e.disabled, selector + " disabled");
  e.click();
};
const fill = (w, name, value) => {
  w.document.querySelector(`[name="${name}"]`).value = value;
};
const submit = (w) =>
  w.document
    .querySelector("#entry-form")
    .dispatchEvent(new w.Event("submit", { bubbles: true, cancelable: true }));
async function main() {
  let ready = false;
  for (let i = 0; i < 100; i++) {
    try {
      ready = (await fetch(base + "/api/health")).ok;
    } catch {}
    if (ready) break;
    await sleep(50);
  }
  assert(ready, "test server started");
  const host = await page();
  click(host, "#create");
  fill(host, "player_name", "灯塔旅人");
  submit(host);
  await waitFor(
    () => host.document.querySelector("#start:not(:disabled)"),
    "created and websocket authenticated",
  );
  const identity = JSON.parse(host.sessionStorage.getItem("hexbound-session"));
  assert(identity.token && identity.invite_code);
  const guests = [];
  for (let i = 1; i <= 5; i++) {
    const guest = await page();
    guests.push(guest);
    click(guest, "#join");
    fill(guest, "invite_code", identity.invite_code);
    fill(guest, "player_name", `同伴${i}`);
    submit(guest);
    await waitFor(
      () =>
        guest.document.querySelector(".table-shell") &&
        guest.document
          .querySelector(".header-status")
          ?.textContent.includes("已连接"),
      "guest connected",
    );
  }
  await waitFor(
    () => host.document.querySelectorAll(".party-member").length === 6,
    "six synchronized seats",
  );
  const seventh = await page();
  click(seventh, "#join");
  fill(seventh, "invite_code", identity.invite_code);
  fill(seventh, "player_name", "第七人");
  submit(seventh);
  await waitFor(
    () =>
      seventh.document
        .querySelector("#entry-error")
        ?.textContent.includes("六席已满"),
    "seventh rejected",
  );
  click(host, "#start");
  await waitFor(
    () =>
      host.document.querySelector('[data-action="investigate"]:not(:disabled)'),
    "adventure started",
  );
  await waitFor(
    () =>
      guests.every((w) =>
        w.document.querySelector('[data-action="investigate"]'),
      ),
    "start broadcast",
  );
  click(host, '[data-action="investigate"]');
  await waitFor(
    () => host.document.querySelector(".roll-ticket"),
    "rule receipt rendered",
  );
  await waitFor(
    () => guests.every((w) => w.document.querySelector(".roll-ticket")),
    "dice synchronized",
  );
  assert(host.document.querySelector('[data-action="advance"]'));
  const guest = guests[0];
  guest.document.querySelector("#compose-mode").value = "chat";
  guest.document
    .querySelector("#compose-mode")
    .dispatchEvent(new guest.Event("change"));
  guest.document.querySelector("#intent").value =
    "<img src=x onerror=alert(1)> 一起前行";
  guest.document
    .querySelector("#intent-form")
    .dispatchEvent(
      new guest.Event("submit", { bubbles: true, cancelable: true }),
    );
  await waitFor(
    () =>
      host.document
        .querySelector("#journal-log")
        .textContent.includes("<img src=x"),
    "chat broadcast",
  );
  assert.equal(
    host.document.querySelectorAll("#journal-log img").length,
    0,
    "player input escaped",
  );
  click(host, "#room-menu");
  click(host, "#pause");
  await waitFor(
    () => host.document.body.textContent.includes("冒险已暂停"),
    "pause",
  );
  click(host, "#room-menu");
  click(host, "#resume");
  await waitFor(
    () => host.document.querySelector('[data-action="advance"]:not(:disabled)'),
    "resume",
  );
  assert(host.localStorage.length > 0, "recovery identities persisted");
  console.log(
    "PASS: DOM create/join, six live WebSocket seats, capacity, start, dice, escaped chat, pause/resume, insecure-origin UUID, persisted identity.",
  );
}
main()
  .catch((e) => {
    console.error(e);
    process.exitCode = 1;
  })
  .finally(() => {
    sockets.forEach((s) => {
      s.onclose = null;
      s.onmessage = null;
      s.onerror = null;
      s.onopen = null;
      s.close();
    });
    windows.forEach((w) => w.close());
    if (server) {
      server.once("exit", () =>
        rmSync(temporary, { recursive: true, force: true }),
      );
      server.kill();
    } else rmSync(temporary, { recursive: true, force: true });
  });

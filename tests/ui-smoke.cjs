/* Starts an isolated Python server. DOM integration, not a visual/layout test.
 * Set HEXBOUND_TEST_URL to use an existing disposable test server instead.
 */
const { JSDOM } = require("jsdom");
const accountMode = process.argv.includes("--accounts");
const NodeWebSocket = require("ws");
let accountCounter = 0;
const cookies = new Map();
const pauseResponses = new Map();
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
          HEXBOUND_ALLOW_GUESTS: accountMode ? "0" : "1",
          HEXBOUND_LEGACY_ADMIN_TOKEN: "0",
          HEXBOUND_ALLOW_REGISTRATION: "1",
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
async function page(existingCookie) {
  let cookie = existingCookie || "";
  if (accountMode && !cookie) {
    const response = await fetch(base + "/api/auth/register", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        username: "adventurer" + accountCounter++,
        password: "A-durable-test-passphrase",
        display_name: "同行者",
      }),
    });
    assert.equal(response.status, 201, await response.clone().text());
    cookie = response.headers.get("set-cookie").split(";")[0];
  }
  const dom = new JSDOM('<div id="app"></div><div id="toast" hidden></div>', {
    url: base,
    runScripts: "outside-only",
    pretendToBeVisual: true,
  });
  const w = dom.window;
  windows.push(w);
  cookies.set(w, cookie);
  w.fetch = async (url, options = {}) => {
    // Hold the HTTP pause response until the test observes its earlier WS update.
    // This deterministically exercises the real-time/HTTP completion race.
    const gate =
      options.body && JSON.parse(options.body).type === "pause"
        ? new Promise((resolve) => pauseResponses.set(w, resolve))
        : null;
    const response = await fetch(new URL(url, base), {
      ...options,
      headers: { ...options.headers, ...(cookie ? { Cookie: cookie } : {}) },
    });
    if (gate) await gate;
    return response;
  };
  w.WebSocket = class extends NodeWebSocket {
    constructor(url) {
      super(url, {
        headers: cookie ? { Cookie: cookie, Origin: base } : { Origin: base },
      });
      sockets.push(this);
    }
  };
  // Non-secure LAN origins do not expose randomUUID; exercise that path.
  Object.defineProperty(w.crypto, "randomUUID", { value: undefined });
  w.eval(readFileSync(resolve(__dirname, "../frontend/live-log.js"), "utf8"));
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
  assert.equal(host.document.querySelector('[data-mode]'), null, 'one product mode');
  assert.equal(host.document.querySelector('[name=interaction_mode]'), null, 'no interaction policy selector');
  fill(host, "player_name", "灯塔旅人");
  fill(host, "starting_level", "1");
  submit(host);
  await waitFor(
    () => host.document.querySelector("#start:not(:disabled)"),
    "created and websocket authenticated",
  );
  const identity = JSON.parse(host.sessionStorage.getItem("hexbound-session"));
  assert(identity.invite_code);
  assert(accountMode ? !identity.token : identity.token);
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
  await waitFor(
    () => host.document.querySelector("#room-menu:not(:disabled)"),
    "menu ready before pause",
  );
  click(host, "#room-menu");
  click(host, "#pause");
  await waitFor(
    () => host.document.body.textContent.includes("冒险已暂停"),
    "pause",
  );
  assert(
    host.document.querySelector("#room-menu").disabled,
    "Room mutations remain unavailable until the pause request completes",
  );
  assert.equal(host.document.querySelector('#compose-mode'), null, 'chat cannot submit an action');
  assert(!host.document.querySelector('#intent-form button').disabled, 'chat stays open during action HTTP wait');
  host.document.querySelector('#intent').value = '暂停等待时仍能商量';
  host.document.querySelector('#intent-form').dispatchEvent(new host.Event('submit', {bubbles:true,cancelable:true}));
  await waitFor(() => guest.document.querySelector('#journal-log').textContent.includes('暂停等待时仍能商量'), 'chat during pending action and pause');
  await waitFor(() => !host.document.querySelector('#intent-form button').disabled, 'chat request completes independently');
  assert(host.document.querySelector('#room-menu').disabled, 'chat completion cannot unlock an outstanding action');
  pauseResponses.get(host)();
  await waitFor(
    () => host.document.querySelector("#room-menu:not(:disabled)"),
    "pause HTTP completion",
  );
  click(host, "#room-menu");
  click(host, "#resume");
  await waitFor(
    () => host.document.querySelector('[data-action="advance"]:not(:disabled)'),
    "resume",
  );
  if (accountMode) {
    assert.equal(
      host.localStorage.getItem("hexbound-seats"),
      null,
      "account seats need no local bearer storage",
    );
    const restored = await page(cookies.get(host));
    await waitFor(
      () => restored.document.querySelector("[data-restore]"),
      "server-side rooms across devices",
    );
    click(restored, "[data-restore]");
    await waitFor(
      () =>
        restored.document
          .querySelector(".header-status")
          ?.textContent.includes("已连接"),
      "account room restored without local storage",
    );
    const identity2 = JSON.parse(
      restored.sessionStorage.getItem("hexbound-session"),
    );
    assert.equal(identity2.member_id, identity.member_id);
  } else assert(host.localStorage.length > 0, "recovery identities persisted");
  console.log(
    (accountMode ? "ACCOUNT MODE: " : "GUEST MODE: ") +
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
        rmSync(temporary, { recursive: true, force: true, maxRetries: 10, retryDelay: 100 }),
      );
      server.kill();
    } else rmSync(temporary, { recursive: true, force: true, maxRetries: 10, retryDelay: 100 });
  });

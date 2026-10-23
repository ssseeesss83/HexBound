/* Cookie-backed account-center integration. Run: node tests/account-smoke.cjs
 * Requires jsdom plus the Python application dependencies. Uses a temporary DB.
 */
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const os = require("node:os");
const net = require("node:net");
const { spawn } = require("node:child_process");
const { JSDOM } = require("jsdom");

const project = path.resolve(__dirname, "..");
const temporary = fs.mkdtempSync(path.join(os.tmpdir(), "hexbound-account-"));
const initialPassword = "A journey begins 2026!";
const changedPassword = "A journey continues 2026!";
const temporaryPassword = "Temporary journey 2026!";
const finalPassword = "My own journey password 2026!";
const adminPassword = "Administrator journey 2026!";
let server,
  dom,
  serverErrors = "";
const delay = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

async function eventually(predicate, message, timeout = 8000) {
  const start = Date.now();
  while (Date.now() - start < timeout) {
    if (await predicate()) return;
    await delay(35);
  }
  throw new Error(message);
}

async function unusedPort() {
  const reservation = net.createServer();
  await new Promise((resolve) => reservation.listen(0, "127.0.0.1", resolve));
  const port = reservation.address().port;
  await new Promise((resolve) => reservation.close(resolve));
  return port;
}

async function run() {
  const port = await unusedPort(),
    origin = `http://127.0.0.1:${port}`;
  server = spawn(
    process.env.PYTHON || "python",
    [
      "-m",
      "uvicorn",
      "backend.app:app",
      "--host",
      "127.0.0.1",
      "--port",
      String(port),
    ],
    {
      cwd: project,
      env: {
        ...process.env,
        HEXBOUND_DB: path.join(temporary, "account.sqlite"),
        HEXBOUND_BOOTSTRAP_ADMIN_USERNAME: "test-admin",
        HEXBOUND_BOOTSTRAP_ADMIN_PASSWORD: adminPassword,
        HEXBOUND_ALLOW_REGISTRATION: "true",
        HEXBOUND_COOKIE_SECURE: "false",
        HEXBOUND_ADMIN_TOKEN: "",
        HEXBOUND_ENABLE_LEGACY_STUDIO_TOKEN: "false",
        LLM_API_KEY: "",
        LLM_MODEL: "",
      },
      stdio: ["ignore", "ignore", "pipe"],
    },
  );
  server.on("error", (error) => {
    serverErrors += error.message;
  });
  server.stderr.on("data", (data) => {
    serverErrors += data.toString();
  });
  await eventually(
    async () => {
      try {
        return (await fetch(`${origin}/api/health`)).ok;
      } catch {
        return false;
      }
    },
    "Account test server did not start",
    15000,
  );

  dom = new JSDOM(
    '<div id="account"></div><div id="account-toast" hidden></div>',
    { url: `${origin}/account.html`, runScripts: "outside-only" },
  );
  const w = dom.window;
  const q = (selector) => w.document.querySelector(selector);
  const click = (selector) => {
    const node = q(selector);
    assert.ok(node, `Missing control ${selector}`);
    assert.ok(!node.disabled, `Disabled control ${selector}`);
    node.click();
  };
  const fill = (name, value, form = "#auth-form") => {
    const input = q(`${form} [name="${name}"]`);
    assert.ok(input, `Missing input ${form}/${name}`);
    input.value = value;
  };
  const submit = (selector) =>
    q(selector).dispatchEvent(
      new w.Event("submit", { bubbles: true, cancelable: true }),
    );
  // Native fetch has no browser cookie jar. Mirror actual HttpOnly cookie handling
  // at the transport layer; document.cookie still cannot read the session cookie.
  w.fetch = async (url, options = {}) => {
    const absolute = new URL(url, origin).href;
    const headers = new Headers(options.headers || {});
    const cookies = dom.cookieJar.getCookieStringSync(absolute);
    if (cookies) headers.set("Cookie", cookies);
    if (options.method && options.method !== "GET")
      headers.set("Origin", origin);
    const response = await fetch(absolute, { ...options, headers });
    for (const cookie of response.headers.getSetCookie())
      dom.cookieJar.setCookieSync(cookie, absolute);
    return response;
  };
  w.confirm = () => true;
  w.eval(fs.readFileSync(path.join(project, "frontend/account.js"), "utf8"));
  await eventually(() => q("#register-tab"), "Account entrance did not render");

  const me = async () => (await w.fetch("/api/auth/me")).json();
  async function login(username, password) {
    await eventually(() => q("#auth-form"), "Expected login form");
    click("#login-tab");
    fill("username", username);
    fill("password", password);
    submit("#auth-form");
    await eventually(() => q("#change-password"), "Login did not succeed");
  }
  async function logout(all = false) {
    click(all ? "#logout-all" : "#logout");
    await eventually(() => q("#auth-form"), "Logout did not return to login");
  }
  async function changePassword(current, next) {
    click("#change-password");
    fill("current_password", current, "#password-form");
    fill("new_password", next, "#password-form");
    fill("confirm_password", next, "#password-form");
    submit("#password-form");
    await eventually(
      () => !q("#password-form") && q("#change-password"),
      "Password change failed",
    );
  }

  click("#register-tab");
  fill("username", "test-player");
  fill("display_name", "测试旅人");
  fill("password", initialPassword);
  fill("confirm_password", initialPassword);
  submit("#auth-form");
  await eventually(
    () => q("#change-password"),
    "Registration did not create a logged-in player",
  );
  const player = (await me()).user;
  assert.equal(player.role, "player");
  assert.ok(
    !w.document.cookie.includes("hexbound_session"),
    "HttpOnly cookie must not be available to JavaScript",
  );
  assert.equal(
    (await w.fetch("/api/studio/items")).status,
    403,
    "Player must not edit studio content",
  );
  assert.equal(
    (
      await w.fetch("/api/auth/logout-all", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: "{}",
      })
    ).status,
    403,
    "Cookie-authenticated mutations require CSRF",
  );

  const oldCookie = dom.cookieJar.getCookieStringSync(origin);
  await changePassword(initialPassword, changedPassword);
  assert.equal(
    (await fetch(`${origin}/api/auth/me`, { headers: { Cookie: oldCookie } }))
      .status,
    401,
    "Password change must revoke old sessions",
  );
  w.sessionStorage.setItem("hexbound-session", '{"legacy":"room"}');
  w.localStorage.setItem("hexbound-seats", '[{"legacy":"claim-later"}]');
  await logout(true);
  assert.equal(w.sessionStorage.getItem("hexbound-session"), null);
  assert.ok(
    w.localStorage.getItem("hexbound-seats"),
    "Logout must preserve anonymous seats for later claim",
  );

  await login("test-admin", adminPassword);
  // If a deployment forces the initial administrator to rotate credentials,
  // satisfy that policy before exercising account administration.
  let effectiveAdminPassword = adminPassword;
  if ((await me()).user.must_change_password) {
    effectiveAdminPassword = `${adminPassword} changed`;
    await changePassword(adminPassword, effectiveAdminPassword);
  }
  await eventually(
    () =>
      q(`[data-manage="${player.id}"]`) &&
      !q(`[data-manage="${player.id}"]`).disabled,
    "Administrator user list did not load",
  );
  assert.equal(
    (await w.fetch("/api/studio/items")).status,
    200,
    "Administrator cookie must authorize studio",
  );
  fill("q", "test-player", "#user-filter");
  submit("#user-filter");
  await eventually(
    () =>
      q("#admin-body")?.getAttribute("aria-busy") === "false" &&
      w.document.querySelectorAll("[data-manage]").length === 1,
    "User search did not filter the list",
  );
  assert.ok(
    q("#previous-page").disabled && q("#next-page").disabled,
    "Single-page query must disable pagination",
  );
  fill("q", "", "#user-filter");
  submit("#user-filter");
  await eventually(
    () =>
      q("#admin-body")?.getAttribute("aria-busy") === "false" &&
      w.document.querySelectorAll("[data-manage]").length === 2,
    "User search did not reset",
  );
  const firstPage = await (
    await w.fetch("/api/admin/users?page=1&page_size=1")
  ).json();
  const secondPage = await (
    await w.fetch("/api/admin/users?page=2&page_size=1")
  ).json();
  assert.equal(firstPage.total, 2);
  assert.notEqual(
    firstPage.items[0].id,
    secondPage.items[0].id,
    "Server pagination must return different rows",
  );
  const admin = (await me()).user;
  click(`[data-manage="${admin.id}"]`);
  fill("role", "player", "#manage-form");
  submit("#manage-form");
  await eventually(
    () => q("#manage-error")?.textContent,
    "Last administrator protection was not shown",
  );
  assert.equal((await me()).user.role, "admin");
  click("[data-close]");
  click(`[data-manage="${player.id}"]`);
  fill("role", "creator", "#manage-form");
  submit("#manage-form");
  await eventually(() => !q("#manage-form"), "Role change failed");
  await logout();
  await login("test-player", changedPassword);
  assert.equal((await me()).user.role, "creator");
  assert.equal(
    (await w.fetch("/api/studio/items")).status,
    200,
    "Creator cookie must authorize studio",
  );
  await logout();

  await login("test-admin", effectiveAdminPassword);
  await eventually(
    () =>
      q(`[data-manage="${player.id}"]`) &&
      !q(`[data-manage="${player.id}"]`).disabled,
    "Administrator list did not return",
  );
  click(`[data-manage="${player.id}"]`);
  q("#manage-form [name=disabled]").checked = true;
  submit("#manage-form");
  await eventually(() => !q("#manage-form"), "Account disabling failed");
  const disabledLogin = await fetch(`${origin}/api/auth/login`, {
    method: "POST",
    headers: { "Content-Type": "application/json", Origin: origin },
    body: JSON.stringify({
      username: "test-player",
      password: changedPassword,
    }),
  });
  assert.ok(
    [401, 403].includes(disabledLogin.status),
    "Disabled accounts must not log in",
  );
  await eventually(
    () =>
      q(`[data-manage="${player.id}"]`) &&
      !q(`[data-manage="${player.id}"]`).disabled,
    "List missing disabled account",
  );
  click(`[data-manage="${player.id}"]`);
  q("#manage-form [name=disabled]").checked = false;
  submit("#manage-form");
  await eventually(() => !q("#manage-form"), "Account enabling failed");
  await eventually(
    () =>
      q(`[data-manage="${player.id}"]`) &&
      !q(`[data-manage="${player.id}"]`).disabled,
    "List missing re-enabled account",
  );
  click(`[data-manage="${player.id}"]`);
  fill("new_password", temporaryPassword, "#reset-form");
  fill("confirm_password", temporaryPassword, "#reset-form");
  submit("#reset-form");
  await eventually(
    () => !q("#reset-form"),
    "Administrator password reset failed",
  );
  click("[data-admin-tab=audit]");
  await eventually(() => q(".audit-item"), "Audit records did not render");
  assert.ok(
    !q("#admin-body").textContent.includes(temporaryPassword),
    "Audit must not expose reset passwords",
  );
  await logout();

  await login("test-player", temporaryPassword);
  assert.ok(
    (await me()).user.must_change_password,
    "Reset password must require rotation",
  );
  assert.ok(
    q("#forced-password"),
    "Required password rotation must be visible",
  );
  assert.equal(
    (await w.fetch("/api/studio/items")).status,
    403,
    "Forced password rotation blocks studio access",
  );
  await changePassword(temporaryPassword, finalPassword);
  assert.equal((await me()).user.must_change_password, false);
  assert.equal((await w.fetch("/api/studio/items")).status, 200);
  const persisted = [
    ...Object.keys(w.localStorage).map((key) => w.localStorage.getItem(key)),
    ...Object.keys(w.sessionStorage).map((key) =>
      w.sessionStorage.getItem(key),
    ),
  ].join(" ");
  for (const secret of [
    initialPassword,
    changedPassword,
    temporaryPassword,
    finalPassword,
    adminPassword,
  ])
    assert.ok(
      !persisted.includes(secret),
      "Passwords must never enter browser storage",
    );
  console.log(
    "Account DOM integration passed: register/login, HttpOnly/CSRF, password rotation, logout-all, role enforcement, admin enable/disable/reset, audit, creator/admin studio cookies.",
  );
}

run()
  .catch((error) => {
    console.error(error);
    if (serverErrors) console.error(serverErrors);
    process.exitCode = 1;
  })
  .finally(async () => {
    dom?.window.close();
    if (server && server.exitCode === null) {
      server.kill("SIGTERM");
      await Promise.race([
        new Promise((resolve) => server.once("exit", resolve)),
        delay(2000),
      ]);
      if (server.exitCode === null) server.kill("SIGKILL");
    }
    fs.rmSync(temporary, { recursive: true, force: true });
  });

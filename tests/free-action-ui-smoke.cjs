/* Real cookie-authenticated API + DOM + WebSocket integration; no external LLM. */
const assert = require("node:assert/strict");
const fs = require("node:fs"),
  path = require("node:path"),
  os = require("node:os"),
  net = require("node:net");
const { spawn } = require("node:child_process");
const { JSDOM } = require("jsdom");
const WS = require("ws");
const root = path.resolve(__dirname, ".."),
  tmp = fs.mkdtempSync(path.join(os.tmpdir(), "hexbound-free-action-"));
let server,
  dom,
  origin,
  cookie = "",
  csrf = "",
  logs = "";
const sockets = [];
const delay = (ms) => new Promise((r) => setTimeout(r, ms));
async function until(fn, label) {
  for (let i = 0; i < 250; i++) {
    if (await fn()) return;
    await delay(30);
  }
  throw Error(
    label +
      "\n" +
      (dom?.window.document.querySelector("#toast")?.textContent || ""),
  );
}
async function api(url, body, method = body ? "POST" : "GET") {
  const r = await fetch(origin + url, {
    method,
    headers: {
      "Content-Type": "application/json",
      Cookie: cookie,
      Origin: origin,
      "X-CSRF-Token": csrf,
    },
    body: body ? JSON.stringify(body) : undefined,
  });
  const data = await r.json();
  assert(r.ok, JSON.stringify(data));
  if (r.headers.get("set-cookie"))
    cookie = r.headers.get("set-cookie").split(";")[0];
  if (data.csrf_token) csrf = data.csrf_token;
  return data;
}
async function main() {
  const listener = net.createServer();
  await new Promise((r) => listener.listen(0, "127.0.0.1", r));
  const port = listener.address().port;
  await new Promise((r) => listener.close(r));
  origin = `http://127.0.0.1:${port}`;
  server = spawn(
    process.env.PYTHON || "python",
    ["-m", "uvicorn", "backend.app:app", "--port", String(port)],
    {
      cwd: root,
      env: {
        ...process.env,
        HEXBOUND_DB: path.join(tmp, "test.sqlite"),
        HEXBOUND_ALLOW_GUESTS: "0",
        HEXBOUND_BOOTSTRAP_ADMIN_USERNAME: "combatadmin",
        HEXBOUND_BOOTSTRAP_ADMIN_PASSWORD: "Combat-test-password-123",
        LLM_API_KEY: "",
        LLM_MODEL: "",
      },
      stdio: ["ignore", "ignore", "pipe"],
    },
  );
  server.stderr.on("data", (d) => (logs += d));
  await until(async () => {
    try {
      return (await fetch(origin + "/api/health")).ok;
    } catch {
      return false;
    }
  }, "server");
  await api("/api/auth/login", {
    username: "combatadmin",
    password: "Combat-test-password-123",
  });
  for (const data of [
    {
      id: "ui-monster",
      kind: "monster",
      name: "试炼幻影",
      hp: 50,
      ac: 10,
      attack_bonus: 0,
      damage_dice: "1d4",
      damage_bonus: -5,
      initiative_bonus: -5,
      xp: 300,
    },
    {
      id: "ui-scenario",
      kind: "scenario",
      name: "战斗界面试炼",
      entry_node_id: "foyer",
      skill_ids: [],
      monster_ids: ["ui-monster"],
      nodes: [
        {
          id: "foyer",
          title: "试炼入口",
          text: "木箱与石门映入眼帘。",
          objective: "进入试炼场",
          objects: [
            { id: "crate", name: "木箱", tags: ["movable", "cover"], hp: 10 },
          ],
          monster_ids: [],
          ending: false,
          actions: [{ id: "enter", label: "进入试炼", next_node_id: "entry" }],
        },
        {
          id: "entry",
          title: "试炼场",
          text: "一道幻影挡住去路。",
          objective: "击败幻影",
          monster_ids: ["ui-monster"],
          ending: false,
          actions: [{ id: "finish", label: "离开试炼", next_node_id: "end" }],
        },
        {
          id: "end",
          title: "终点",
          text: "试炼完成。",
          objective: "完成",
          ending: true,
          actions: [],
          monster_ids: [],
        },
      ],
    },
  ]) {
    const { kind, ...fields } = data;
    const item = await api("/api/studio/items", { kind, data: fields });
    await api(`/api/studio/items/${item.id}/publish`, {
      expected_revision: item.revision,
    });
  }
  const hero = await api("/api/my/characters", {
    class_id: "wizard",
    name: "测试法师",
    choices: {
      cantrips: ["fire-bolt", "light", "mage-hand"],
      spellbook: [
        "magic-missile",
        "shield",
        "mage-armor",
        "sleep",
        "burning-hands",
        "charm-person",
      ],
      prepared_spells: ["magic-missile", "shield", "mage-armor"],
    },
  });
  dom = new JSDOM('<div id="app"></div><div id="toast" hidden></div>', {
    url: origin,
    runScripts: "outside-only",
    pretendToBeVisual: true,
  });
  const w = dom.window,
    d = w.document,
    q = (s) => d.querySelector(s);
  w.fetch = (url, options = {}) =>
    fetch(new URL(url, origin), {
      ...options,
      headers: { ...options.headers, Cookie: cookie, Origin: origin },
    });
  w.WebSocket = class extends WS {
    constructor(url) {
      super(url, { headers: { Cookie: cookie, Origin: origin } });
      sockets.push(this);
    }
  };
  w.eval(fs.readFileSync(path.join(root, "frontend/app.js"), "utf8"));
  const click = (s) => {
    assert(q(s), s);
    assert(!q(s).disabled, s + " disabled");
    q(s).click();
  };
  const submit = (s) =>
    q(s).dispatchEvent(
      new w.Event("submit", { bubbles: true, cancelable: true }),
    );
  await until(() => q("#create"), "home");
  click("#create");
  q("[name=hero_id]").value = hero.id;
  q("[name=scenario_id]").value = "ui-scenario";
  q("[name=player_name]").value = "试炼法师";
  submit("#entry-form");
  await until(() => q("#start:not(:disabled)"), "room");
  click("#start");
  await until(
    () => q('[data-action-entry="free"]'),
    "exploration dual entries",
  );
  await until(
    () => q("#free-action-form button:not(:disabled)"),
    "start request complete",
  );
  assert(q('[data-action-entry="skills"]'));
  click('[data-action-entry="free"]');
  assert(q(".composer .actions").classList.contains("action-entry-hidden"));
  assert(
    q("[data-free-object=crate]")?.textContent.includes("木箱"),
    "authored interactive object displayed",
  );
  click("[data-free-object=crate]");
  assert(
    q("#free-action-intent").value.includes("木箱"),
    "object name inserts into intent",
  );
  q("#free-action-intent").value = "我仔细观察石门上的线索";
  q("#free-action-intent").dispatchEvent(new w.Event("input"));
  submit("#free-action-form");
  assert(
    q(".free-action-status").textContent.includes("正在"),
    "pending ruling shown",
  );
  await until(
    () => q("[data-director-resolve]:not(:disabled)"),
    "exploration proposal",
  );
  assert(q(".dm-proposal").textContent.includes("确认前不会掷骰"));
  click("[data-director-cancel]");
  await until(() => !q(".dm-proposal"), "cancel no execution");
  click('[data-action-entry="skills"]');
  assert(!q(".composer .actions").classList.contains("action-entry-hidden"));
  await until(() => q('[data-action="node:enter"]:not(:disabled)'), "cancel HTTP completion");
  click('[data-action="node:enter"]');
  await until(
    () => q(".encounter-shell") && q("#free-action-form button:not(:disabled)"),
    "encounter",
  );
  click('[data-action-entry="free"]');
  q("#free-action-intent").value = "我用力推倒眼前的敌人";
  q("#free-action-intent").dispatchEvent(new w.Event("input"));
  submit("#free-action-form");
  await until(
    () => q("[data-director-resolve]:not(:disabled)"),
    "combat proposal",
  );
  assert(q(".proposal-facts"), "compiled plan preview");
  assert(
    q(".proposal-facts").textContent.includes("动作"),
    "explicit action cost",
  );
  const session = JSON.parse(w.sessionStorage.getItem("hexbound-session"));
  const before = await api(`/api/rooms/${session.room_id}`);
  assert(!before.combat.action_used, "proposal does not consume action");
  await api(`/api/rooms/${session.room_id}/commands`, {
    command_id: require("node:crypto").randomUUID(),
    expected_version: before.version,
    type: "pause",
    payload: {},
  });
  await until(
    () => q("[data-director-revise]"),
    "stale proposal offers resubmission",
  );
  assert(q("[data-director-resolve]").disabled, "stale confirmation disabled");
  const paused = await api(`/api/rooms/${session.room_id}`);
  await api(`/api/rooms/${session.room_id}/commands`, {
    command_id: require("node:crypto").randomUUID(),
    expected_version: paused.version,
    type: "resume",
    payload: {},
  });
  await until(
    () => q("[data-director-resolve]:not(:disabled)"),
    "matching state resumes valid plan",
  );
  click("[data-director-resolve]");
  await until(
    () => !q("[data-director-resolve]"),
    "confirmed proposal removed",
  );
  await until(() => q("#free-action-form button:not(:disabled)"), "confirmation HTTP completion");
  const after = await api(`/api/rooms/${session.room_id}`);
  assert(after.combat.action_used, "free action consumes rule resource");
  click('[data-action-entry="skills"]');
  assert(
    q(".combat-actions") &&
      !q(".combat-actions").classList.contains("action-entry-hidden"),
  );
  console.log(
    "PASS: exploration/combat dual entry, pending ruling, preserved intent, cancel without effects, typed cost/check/effect preview, explicit confirmation consumes rule action.",
  );
}

main()
  .catch((e) => {
    console.error(e);
    console.error(logs.slice(-2000));
    process.exitCode = 1;
  })
  .finally(async () => {
    for (const s of sockets) {
      s.onclose = null;
      s.onmessage = null;
      s.onerror = null;
      s.onopen = null;
      s.close();
    }
    dom?.window.close();
    if (server) {
      const exited = new Promise((r) => server.once("exit", r));
      server.kill();
      await exited;
    }
    fs.rmSync(tmp, { recursive: true, force: true });
  });

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
  tmp = fs.mkdtempSync(path.join(os.tmpdir(), "hexbound-combat-"));
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
      hp: 1,
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
      entry_node_id: "entry",
      skill_ids: [],
      monster_ids: ["ui-monster"],
      nodes: [
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
  w.eval(fs.readFileSync(path.join(root, "frontend/live-log.js"), "utf8"));
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
  q("[name=starting_level]").value = "1";
  q("[name=hero_id]").value = hero.id;
  q("[name=scenario_id]").value = "ui-scenario";
  q("[name=player_name]").value = "试炼法师";
  submit("#entry-form");
  await until(() => q("#start:not(:disabled)"), "room");
  click("#start");
  await until(() => q(".encounter-shell"), "battle screen");
  assert(q(".initiative-track"));
  assert(q(".turn-resources"));
  assert.equal(d.querySelectorAll(".combatant-card").length, 1);
  await until(
    () => q('[data-action="cast:magic-missile"]:not(:disabled)'),
    "spell legal",
  );
  assert(
    q('[data-action="cast:shield"]').disabled,
    "unsupported spell disabled",
  );
  click('[data-action="cast:magic-missile"]');
  assert(q("[name=slot]"), "slot selection");
  assert(q("[name=target]"), "legal targets");
  submit("#cast-form");
  await until(() => q("#return-exploration"), "settlement");
  click("#return-exploration");
  await until(() => q("[data-sheet]"), "exploration");
  click("[data-sheet]");
  await until(() => q("[data-sheet-tab=skills]"), "sheet");
  click("[data-sheet-tab=skills]");
  assert.equal(
    d.querySelectorAll(".sheet-list-row").length,
    24,
    "18 skills and 6 saves",
  );
  click("[data-sheet-tab=spells]");
  await until(() => q("#manage-spells"), "spell sheet");
  click("#manage-spells");
  assert.equal(
    q("#spell-manage-form [name=known_spells]"),
    null,
    "no free known spell retraining",
  );
  submit("#spell-manage-form");
  await until(() => !q("#spell-manage-form"), "prepared saved");
  click("[data-sheet-tab=growth]");
  await until(() => q("[name=subclass_id]"), "growth options");
  q("[name=subclass_id]").value = "evocation";
  for (const id of ["alarm", "detect-magic"]) {
    const box = q(`[name=spellbook][value="${id}"]`);
    assert(box, id);
    box.checked = true;
  }
  await until(
    () => q("#level-up-form button[type=submit]:not(:disabled)"),
    "xp upgrade enabled",
  );
  submit("#level-up-form");
  await until(
    () => q(".character-sheet-top")?.textContent.includes("Lv.2"),
    "level2 applied",
  );
  click("[data-sheet-tab=growth]");
  click("#rest-short");
  submit("#rest-form");
  await until(() => !q("#rest-form"), "short rest complete");
  const session = JSON.parse(w.sessionStorage.getItem("hexbound-session"));
  const sheet = await api(
    `/api/rooms/${session.room_id}/characters/${session.member_id}`,
  );
  assert.equal(sheet.character.level, 2);
  assert.equal(sheet.character.subclass_id, "evocation");
  assert(sheet.character.spellbook.includes("alarm"));
  assert.equal(
    sheet.character.spell_slots["1"].current,
    sheet.character.spell_slots["1"].max - 1,
    "slot consumed and no free restoration by short rest",
  );
  console.log(
    "PASS: real cookie/WS combat screen, initiative/resources, supported/unsupported spells, target/slot confirmation, settlement, 18 skills/6 saves, prepared-only management, XP upgrade/subclass/spellbook, short rest.",
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

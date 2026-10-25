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
  tmp = fs.mkdtempSync(path.join(os.tmpdir(), "hexbound-builder-"));
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
  dom = new JSDOM('<div id="app"></div><div id="toast" hidden></div>', {
    url: origin,
    runScripts: "outside-only",
    pretendToBeVisual: true,
  });
  const w = dom.window,
    d = w.document,
    q = (s) => d.querySelector(s);
  let holdCharacterRead=false, releaseCharacterRead, holdSocketAuth=false, releaseSocketAuth;
  w.fetch = async (url, options = {}) => {
    const response=await fetch(new URL(url,origin),{...options,headers:{...options.headers,Cookie:cookie,Origin:origin}});
    if(holdCharacterRead&&String(url).includes('/characters/')&&!options.method){holdCharacterRead=false;await new Promise(resolve=>releaseCharacterRead=resolve);}
    return response;
  };
  w.WebSocket = class extends WS {
    constructor(url) {
      super(url, { headers: { Cookie: cookie, Origin: origin } });
      sockets.push(this);
    }
    send(data){if(holdSocketAuth){holdSocketAuth=false;releaseSocketAuth=()=>super.send(data);return;}return super.send(data);}
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
  await until(()=>q('#character-vault'),'home');
  click('#character-vault');await until(()=>q('#new-character-builder'),'vault');click('#new-character-builder');await until(()=>q('#builder-identity'),'builder');
  q('[name=name]').value='墨潮';q('[name=class_id]').value='fighter';q('[name=target_level]').value='3';q('[name=ability_str]').value='20';q('[name=appearance]').value='银色短发';q('[name=personality]').value='冷静而坚定';q('[name=background]').value='雾港的退役守卫';q('[name=talents]').value='熟悉潮汐的节律';
  q('#builder-ai-prompt').value='保留职业属性，补充性格细节';click('#builder-ai');await until(()=>q('#builder-identity'),'AI draft');assert(q('.builder-notes').textContent.includes('草稿'));
  assert.equal((await api('/api/my/characters')).items.length,0,'AI never saves character');
  q('[name=class_id]').value='fighter';q('[name=target_level]').value='3';q('[name=ability_str]').value='20';q('[name=name]').value='墨潮';
  submit('#builder-identity');await until(()=>q('#builder-choice'),'initial choices');assert(q('[name=skills]'),'explicit initial proficiency');
  const selectSkills=()=>{for(const box of d.querySelectorAll('[name=skills]'))box.checked=['athletics','perception'].includes(box.value);};selectSkills();submit('#builder-choice');
  await until(()=>q('#builder-choice')?.textContent.includes('升至 2 级'),'level2 review');submit('#builder-choice');
  await until(()=>q('[name=subclass_id]'),'level3 subclass choice');q('[name=subclass_id]').value='champion';submit('#builder-choice');await until(()=>q('#builder-save'),'final review');
  assert(q('.builder-review').textContent.includes('Lv.3'));assert.equal((await api('/api/my/characters')).items.length,0,'preview never saves');click('#builder-save');await until(()=>q('#new-character-builder'),'saved vault');
  let hero=(await api('/api/my/characters')).items[0];assert.equal(hero.character.level,3);assert.equal(hero.character.abilities.str,20);assert.equal(hero.character.subclass_id,'champion');assert(hero.character.profile.appearance,'custom appearance');
  click('[data-edit-hero]');await until(()=>q('#builder-identity'),'edit unused hero');assert.equal(q('[name=name]').value,'墨潮');q('[name=personality]').value='谨慎但绝不抛弃同伴';submit('#builder-identity');await until(()=>q('#builder-choice'),'re-review initial');selectSkills();submit('#builder-choice');await until(()=>q('#builder-choice')?.textContent.includes('升至 2 级'),'edit level2');submit('#builder-choice');await until(()=>q('[name=subclass_id]'),'edit level3');q('[name=subclass_id]').value='champion';submit('#builder-choice');await until(()=>q('#builder-save'),'edit final');click('#builder-save');await until(()=>q('#new-character-builder'),'edit saved');hero=(await api('/api/my/characters')).items[0];assert.equal(hero.character.profile.personality,'谨慎但绝不抛弃同伴');
  click('[data-close]');click('#create');assert.equal(q('[name=starting_level]').value,'3','default starting level3');q('[name=player_name]').value='墨潮';q('[name=hero_id]').value=hero.id;submit('#entry-form');await until(()=>q('#start:not(:disabled)'),'existing ready hero');
  const session=JSON.parse(w.sessionStorage.getItem('hexbound-session'));const room=await api(`/api/rooms/${session.room_id}`);assert.equal(room.starting_level,3);assert(room.party[0].build_ready);click('#start');await until(()=>q('[data-action="story-route:next-chapter-1"]:not(:disabled)'),'start built hero');
  click('#room-menu');click('#return-home');await until(()=>q('#create'),'return home');click('#create');q('[name=player_name]').value='新建模板';submit('#entry-form');await until(()=>q('#configure-character')&&q('#room-menu:not(:disabled)'),'pending template');assert(q('#start').disabled,'unfinished level3 template blocks start');click('#configure-character');await until(()=>q('#builder-identity'),'lobby builder');q('[name=class_id]').value='fighter';q('[name=name]').value='海雾';submit('#builder-identity');await until(()=>q('#builder-choice'),'lobby initial');selectSkills();submit('#builder-choice');await until(()=>q('#builder-choice')?.textContent.includes('升至 2 级'),'lobby level2');submit('#builder-choice');await until(()=>q('[name=subclass_id]'),'lobby level3');q('[name=subclass_id]').value='champion';submit('#builder-choice');await until(()=>q('#builder-save'),'lobby review');click('#builder-save');await until(()=>q('#start:not(:disabled)')&&!q('#character-builder'),'template ready');click('#configure-character');await until(()=>q('#builder-identity'),'reopen configured template');assert.equal(q('[name=name]').value,'海雾','lobby reload original build');click('#builder-close');
  const low=await api('/api/my/characters',{class_id:'fighter',name:'低等级旅人',choices:{}});click('#room-menu');click('#return-home');await until(()=>q('#create'),'home low hero');click('#create');q('[name=hero_id]').value=low.id;q('[name=player_name]').value='低等级旅人';holdSocketAuth=true;submit('#entry-form');await until(()=>q('#prepare-character')&&q('#room-menu:not(:disabled)'),'existing low hero pending');assert(q('#start').disabled);holdCharacterRead=true;click('#prepare-character');await until(()=>releaseCharacterRead,'character response held');assert.equal(q('#level-up-form'),null,'no provisional growth form before full sheet arrives');releaseCharacterRead();await until(()=>q('#level-up-form')&&releaseSocketAuth,'full sheet before websocket auth');assert(q('#level-up-form button[type=submit]').disabled,'cannot confirm growth before websocket authentication');assert(q('[data-sheet-connection]').textContent.includes('连接'),'connection wait explained');releaseSocketAuth();await until(()=>q('#level-up-form button:not(:disabled)'),'eligible lobby advancement');submit('#level-up-form');await until(()=>q('.character-sheet-top')?.textContent.includes('Lv.2'),'prepared level2');await until(()=>q('[name=subclass_id]'),'prepared subclass');q('[name=subclass_id]').value='champion';submit('#level-up-form');await until(()=>q('.character-sheet-top')?.textContent.includes('Lv.3'),'prepared level3');click('[data-close]');await until(()=>q('#start:not(:disabled)'),'prepared ready');
  click('#room-menu');click('#return-home');await until(()=>q('#character-vault'),'home wizard');click('#character-vault');await until(()=>q('#new-character-builder'),'vault wizard');click('#new-character-builder');await until(()=>q('#builder-identity'),'wizard identity');q('[name=name]').value='星灯';q('[name=class_id]').value='wizard';q('[name=target_level]').value='1';q('[name=ability_int]').value='18';submit('#builder-identity');await until(()=>q('#builder-choice'),'wizard choices');for(const box of d.querySelectorAll('[name=skills]'))box.checked=['arcana','history'].includes(box.value);for(const box of d.querySelectorAll('[name=cantrips]'))box.checked=['fire-bolt','light','mage-hand'].includes(box.value);for(const box of d.querySelectorAll('[name=spellbook]')){box.checked=['magic-missile','shield','mage-armor','sleep','burning-hands','charm-person'].includes(box.value);box.dispatchEvent(new w.Event('change'));}assert(q('[name=prepared_spells][value=alarm]').disabled,'cannot prepare absent spellbook entry');q('[name=prepared_spells][value=magic-missile]').checked=true;q('[name=prepared_spells][value=shield]').checked=true;submit('#builder-choice');await until(()=>q('#builder-save'),'wizard preview');click('#builder-save');await until(()=>q('#new-character-builder'),'wizard saved');const wizard=(await api('/api/my/characters')).items.find(item=>item.character.name==='星灯');assert.equal(wizard.character.spellbook.length,6);assert.equal(wizard.character.cantrips.length,3);assert.equal(wizard.character.prepared_spells.length,2);assert.equal(wizard.character.abilities.int,18);
  console.log('PASS: custom attributes/profile, AI reviewed draft without save, explicit initial skills and level2/3/subclass, persisted build/edit, default starting level3, existing ready hero entry/start, pending template gate/configure/reopen, existing low hero explicit prepare-level-up, wizard legal spellbook/cantrip/preparation and computed attributes.');
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

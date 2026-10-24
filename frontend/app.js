const app = document.querySelector("#app");
const $ = (s, root = document) => root.querySelector(s);
const esc = (value) =>
  String(value ?? "").replace(
    /[&<>"']/g,
    (c) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[
        c
      ],
  );
const newCommandId = () =>
  typeof crypto.randomUUID === "function"
    ? crypto.randomUUID()
    : Array.from(crypto.getRandomValues(new Uint8Array(16)), (x) =>
        x.toString(16).padStart(2, "0"),
      ).join("");
const localSeats = () => {
  try {
    const saved = JSON.parse(localStorage.getItem("hexbound-seats") || "[]");
    return Array.isArray(saved)
      ? saved.filter((s) => s && s.room_id && s.member_id && s.token)
      : [];
  } catch {
    return [];
  }
};
const savedSeats = () => {
  const owned = accountRooms || [];
  return [
    ...owned,
    ...localSeats().filter(
      (s) =>
        !owned.some(
          (r) => r.room_id === s.room_id && r.member_id === s.member_id,
        ),
    ),
  ];
};
function saveSeat() {
  if (!session || !room) return;
  if (account && !session.token) {
    accountRooms = [
      {
        ...session,
        room_name: room.name,
        player_name: me()?.name || account.display_name,
        status: room.status,
      },
      ...accountRooms.filter((s) => s.room_id !== session.room_id),
    ];
    return;
  }
  const seats = localSeats().filter(
    (s) =>
      !(s.room_id === session.room_id && s.member_id === session.member_id),
  );
  seats.unshift({
    ...session,
    room_name: room.name,
    player_name: me()?.name || "冒险者",
  });
  try {
    localStorage.setItem("hexbound-seats", JSON.stringify(seats.slice(0, 20)));
  } catch {
    toast("浏览器无法保存身份，请保留当前标签页。");
  }
}
const statusNames = {
  lobby: "等候启程",
  playing: "冒险进行中",
  paused: "冒险已暂停",
  finished: "本章已落幕",
};
const abilities = {
  str: "力量",
  dex: "敏捷",
  con: "体质",
  int: "智力",
  wis: "感知",
  cha: "魅力",
};
let account = null,
  csrfToken = "",
  accountRooms = [];
let catalog = {},
  session = null,
  room = null,
  socket = null,
  connected = false,
  retry = 0,
  reconnectTimer,
  busy = false,
  draft = "",
  chatRequest = null,
  mobileTab = "story",
  selectedTarget = "",
  toastTimer;
let combatView = "battle",
  combatLogView = "combat",
  combatCategory = "all",
  combatQuery = "";
let encounterRoomId = null,
  previousCombatActive = false,
  showSettlement = false;
let sheetState = null,
  sheetTab = "overview",
  characterChoices = null,
  vaultCharacters = [];
try {
  session = JSON.parse(sessionStorage.getItem("hexbound-session") || "null");
} catch {
  sessionStorage.removeItem("hexbound-session");
}
const brand = `<div class="brand"><span class="symbol">⬡</span><div>HEXBOUND <small>六席之间</small></div></div>`;
const dieArt = `<svg viewBox="0 0 450 450" fill="none" aria-hidden="true"><circle cx="225" cy="225" r="190" stroke="#354246" stroke-dasharray="2 8"/><circle cx="225" cy="225" r="156" stroke="#354246"/><path d="M225 25v28M225 397v28M25 225h28M397 225h28" stroke="#d4b77c"/><path d="M225 79 352 152 352 299 225 372 98 299 98 152Z" stroke="#d4b77c" stroke-width="1.5"/><path d="m225 79 70 180-140 0 70-180Zm-127 73 57 107-57 40m254-147-57 107 57 40M155 259l70 113 70-113M98 152h254M98 299l127-220 127 220H98Z" stroke="#d4b77c" stroke-opacity=".42"/><text x="225" y="226" fill="#efe9dc" text-anchor="middle" font-family="Georgia,serif" font-size="62">20</text><circle cx="225" cy="35" r="4" fill="#a5d9b8"/><circle cx="390" cy="130" r="4" fill="#d4b77c"/><circle cx="390" cy="320" r="4" fill="#354246"/><circle cx="225" cy="415" r="4" fill="#354246"/><circle cx="60" cy="320" r="4" fill="#354246"/><circle cx="60" cy="130" r="4" fill="#d4b77c"/></svg>`;
const mapArt = `<svg class="scene-art" viewBox="0 0 240 150" fill="none" aria-label="雾港航海图装饰"><defs><pattern id="grid" width="24" height="24" patternUnits="userSpaceOnUse"><path d="M24 0H0V24" stroke="#354246" stroke-width=".5"/></pattern></defs><path fill="url(#grid)" d="M0 0h240v150H0z"/><path d="m0 114 28-6 16-28 22 7 13-39 24-14 18 9 20-20 14 13 13 38 25 17 17-4 30 21" stroke="#6c8980" stroke-width="1.5"/><path d="M20 126Q69 107 103 98T207 119" stroke="#d4b77c" stroke-dasharray="3 6"/><circle cx="103" cy="98" r="5" stroke="#d4b77c"/><circle cx="103" cy="98" r="2" fill="#d4b77c"/><path d="m201 20 0 23m-10-11h20m-10-13-4 16 4-3 4 3-4-16Z" stroke="#d4b77c" stroke-width=".7"/><text x="201" y="15" fill="#d4b77c" font-size="6" text-anchor="middle">N</text><text x="14" y="19" fill="#81968f" font-size="6" letter-spacing="2">THE UNCHARTED</text></svg>`;

function toast(message) {
  const el = $("#toast");
  el.textContent = message;
  el.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => (el.hidden = true), 5000);
}
async function api(path, options = {}) {
  const response = await fetch(path, {
    ...options,
    headers: {
      "Content-Type": "application/json",
      ...(csrfToken ? { "X-CSRF-Token": csrfToken } : {}),
      ...(session?.token ? { Authorization: `Bearer ${session.token}` } : {}),
      ...options.headers,
    },
  });
  let data, parsed = false;
  try {
    data = await response.json();
    parsed = true;
  } catch {
    data = {};
  }
  if (!response.ok) {
    const error = new Error(
      typeof data.detail === "string"
        ? data.detail
        : `请求未完成 (${response.status})`,
    );
    error.status = response.status;
    error.retrySameCommand = data.retry_same_command === true;
    error.responseIncomplete = !parsed;
    throw error;
  }
  return data;
}
function home() {
  app.innerHTML = `<main class="home"><header class="home-header">${brand}<span class="chip"><span class="dot"></span>1–6 位冒险者 · 一个共同的世界</span></header><section class="hero"><div><div class="eyebrow">A table. Six souls. Infinite stories.</div><h1>故事没有边界。<br>命运，<em>交给骰子。</em></h1><p class="hero-copy">与同伴走进未被书写的世界。让 AI 编织故事，让真实的规则决定结果。下一页，由你们共同落笔。</p><div class="hero-actions"><button class="primary" id="create">创建冒险 <span aria-hidden="true">↗</span></button><button id="join">凭邀请码入席</button></div><div class="hero-note">${catalog.llm?.configured ? `AI 主持已就绪 · ${esc(catalog.llm.model || "自定义模型")}` : "无需密钥即可体验本地主持 · 配置 LLM 后开启 AI 叙事"}</div></div><div class="artifact">${dieArt}<div class="artifact-caption">EVERY ROLL LEAVES A MARK</div></div></section>${
    savedSeats().length
      ? `<section class="saved-seats"><div class="eyebrow">Your unfinished chapters / 继续冒险</div><div class="saved-grid">${savedSeats()
          .map(
            (s, i) =>
              `<button data-restore="${i}"><strong>${esc(s.room_name || "未完的冒险")}</strong><small>${esc(s.player_name)} · ${account && s.token ? "认领旧席位" : "恢复席位"} ↗</small></button>`,
          )
          .join("")}</div></section>`
      : ""
  }<section class="feature-grid"><div class="feature"><div class="eyebrow">01 / Your story</div><h3>沿着剧本，或走出地图</h3><p>剧本组织主线，AI DM 根据你的行动主持冒险。</p></div><div class="feature"><div class="eyebrow">02 / True consequence</div><h3>每次掷骰，都有据可查</h3><p>脚本执行检定与战斗。模型讲述结果，不替你决定命运。</p></div><div class="feature"><div class="eyebrow">03 / Together</div><h3>六个席位，一段共同记忆</h3><p>实时同行、自动保存。暂时离席，也不会失去故事。</p></div></section><footer class="footer"><span>HEXBOUND / 六席之间 · 原创文字冒险</span><button class="ghost small" id="rules">查看本版规则范围 ↗</button></footer></main>`;
  $(".home-header").insertAdjacentHTML(
    "beforeend",
    `<a class="small" href="/account.html">${account ? esc(account.display_name) + " · 账号中心" : "登录 / 注册"}</a>`,
  );
  $("#create").onclick = () => entryDialog("create");
  $("#join").onclick = () => entryDialog("join");
  $("#rules").onclick = rulesDialog;
  if (account) {
    $(".hero-actions").insertAdjacentHTML(
      "beforeend",
      '<button id="character-vault">我的角色 ↗</button>',
    );
    $("#character-vault").onclick = openCharacterVault;
  }
  $(".hero-actions").insertAdjacentHTML(
    "afterend",
    '<p class="studio-link"><a href="/studio.html">进入内容工坊 · 技能卡 / 怪兽卡 / 剧情本 ↗</a></p>',
  );
  app
    .querySelectorAll("[data-restore]")
    .forEach(
      (b) =>
        (b.onclick = () =>
          restoreSeat(savedSeats()[Number(b.dataset.restore)])),
    );
}
function openDialog(content, setup) {
  const previous = document.activeElement;
  const overlay = document.createElement("div");
  overlay.className = "modal-backdrop";
  overlay.innerHTML = `<section class="modal" role="dialog" aria-modal="true" aria-labelledby="dialog-title">${content}</section>`;
  document.body.append(overlay);
  const close = () => {
    overlay.remove();
    previous?.focus();
  };
  overlay.addEventListener("click", (e) => {
    if (e.target === overlay || e.target.closest("[data-close]")) close();
  });
  overlay.addEventListener("keydown", (e) => {
    if (e.key === "Escape") close();
    if (e.key === "Tab") {
      const list = [
        ...overlay.querySelectorAll(
          'button:not(:disabled),input,select,textarea,[tabindex="0"]',
        ),
      ];
      const first = list[0],
        last = list.at(-1);
      if (e.shiftKey && document.activeElement === first) {
        e.preventDefault();
        last?.focus();
      } else if (!e.shiftKey && document.activeElement === last) {
        e.preventDefault();
        first?.focus();
      }
    }
  });
  const ready = setup?.(overlay, close);
  overlay.querySelector("input,button")?.focus();
  return ready;
}
function rulesDialog() {
  const rules = Array.isArray(catalog.rules)
    ? catalog.rules
    : [
        ...(catalog.rules?.supported || []),
        ...(catalog.rules?.limitations || []),
      ];
  openDialog(
    `<div class="row between"><h2 id="dialog-title">规则的边界</h2><button class="ghost" data-close aria-label="关闭">×</button></div><p class="helper" style="margin-top:18px">本版为 5e 核心规则的可玩子集。所有骰点、伤害与状态变化由服务端脚本执行。</p><ul class="rules-list">${rules.map((r) => `<li>${esc(typeof r === "string" ? r : r.name || r.description)}</li>`).join("") || "<li>属性检定、先攻、攻击与伤害</li><li>未实现动作不会由模型代替执行</li>"}</ul><p class="helper">自由文字用于角色扮演；实际数值判定请使用场景提供的行动按钮。密钥及模型地址由部署者在服务端配置。</p>`,
  );
}
function entryDialog(kind) {
  if (
    (!account && !catalog.auth?.allow_guests) ||
    account?.must_change_password
  ) {
    const next = new URL(location.href);
    next.searchParams.set("entry", kind);
    location.href =
      "/account.html?next=" + encodeURIComponent(next.pathname + next.search);
    return;
  }
  const create = kind === "create";
  openDialog(
    `<div class="row between"><div><div class="eyebrow">${create ? "Begin a chapter" : "Take your seat"}</div><h2 id="dialog-title" style="margin-top:8px">${create ? "让冒险从这里开始" : "你的同伴正在等你"}</h2></div><button class="ghost" data-close aria-label="关闭">×</button></div><form class="form" id="entry-form">${create ? '<label>冒险名称<input name="name" maxlength="60" value="雾港来信" required></label><label>起始等级<input name="starting_level" type="number" min="1" max="20" value="3" required></label><p class="helper">默认 3 级。新角色入席后逐级构筑；已有角色低于此等级需补全，高于此等级不能加入。</p>' : '<label>房间邀请码<input name="invite_code" maxlength="32" placeholder="输入同伴发来的邀请码" autocomplete="off" required></label>'}<div class="columns"><label>冒险者名字<input name="player_name" maxlength="30" placeholder="你的名字" required></label><label>选择角色<select name="character_id">${(catalog.characters || []).map((c) => `<option value="${esc(c.id)}">${esc(c.name || c.label)} · ${esc(c.class_name || c.role || c.class || "")}</option>`).join("")}</select></label></div><p class="helper" id="character-description"></p>${
      create ? '<p class="helper">剧本 + AI DM：主线由剧本组织，自由行动先裁定再确认。</p>' : ""
    }<div class="error" id="entry-error" role="alert"></div><button class="primary" type="submit">${create ? "创建六席冒险桌" : "加入冒险"} ↗</button><p class="helper">角色身份保存在此浏览器。刷新自动恢复，首页可继续冒险；新标签页可加入另一角色。</p></form>`,
    (overlay, close) => {
      const form = $("#entry-form", overlay),
        characterSelect = $("[name=character_id]", form);
      if (create) {
        $("#entry-error", form).insertAdjacentHTML(
          "beforebegin",
          `<label>选择剧情本<select name="scenario_id"><option value="">经典冒险 · 雾港最后一盏灯</option>${(catalog.publishedScenarios || []).map((s) => `<option value="${esc(s.id)}">${esc(s.name)} · 发布 v${esc(s.published_revision)}</option>`).join("")}</select></label><p class="helper">已发布剧本锁定版本；修改内容请在工坊创建草稿。</p>`,
        );
      }
      if (account && vaultCharacters.length) {
        $("#character-description", form).insertAdjacentHTML(
          "afterend",
          `<label>人物来源：已有角色或新模板<select name="hero_id"><option value="">新建所选职业模板（入席后定制）</option>${vaultCharacters.map((hero) => `<option value="${esc(hero.id)}" ${!hero.available ? "disabled" : ""}>${esc(hero.character.name)} · ${esc(hero.character.class_name || hero.character.class_id)} Lv.${hero.character.level}${!hero.available ? " · 正在另一场冒险中" : ""}</option>`).join("")}</select></label>`,
        );
        const heroSelect = $("[name=hero_id]", form);
        heroSelect.onchange = () => {
          const hero = vaultCharacters.find((h) => h.id === heroSelect.value);
          characterSelect.disabled = !!hero;
          if (hero) $("[name=player_name]", form).value = hero.character.name;
        };
      }
      const requestedScenario = new URLSearchParams(location.search).get(
        "scenario",
      );
      if (
        create &&
        requestedScenario &&
        (catalog.publishedScenarios || []).some(
          (s) => s.id === requestedScenario,
        )
      )
        $("[name=scenario_id]", form).value = requestedScenario;
      if(create){const scenarioSelect=$('[name=scenario_id]',form);const useScenarioLevel=()=>{const scenario=(catalog.publishedScenarios||[]).find(item=>item.id===scenarioSelect.value);$('[name=starting_level]',form).value=scenario?.starting_level||3;};scenarioSelect.onchange=useScenarioLevel;if(requestedScenario)useScenarioLevel();}
      const showCharacter = () => {
        const c = (catalog.characters || []).find(
          (c) => c.id === characterSelect.value,
        );
        $("#character-description", form).textContent =
          c?.description ||
          (c
            ? `${c.role || ""} · 生命 ${c.max_hp} · 护甲 ${c.ac} · ${c.weapon?.name || ""}`
            : "");
      };
      characterSelect.onchange = showCharacter;
      showCharacter();
      form.onsubmit = async (e) => {
        e.preventDefault();
        const submit = $("[type=submit]", form);
        submit.disabled = true;
        $("#entry-error", form).textContent = "";
        try {
          const body = Object.fromEntries(new FormData(form));
          if (create) {
            body.mode = "preset";
            body.starting_level = Number(body.starting_level || 3);
            if (!body.scenario_id) delete body.scenario_id;
          } else body.invite_code = body.invite_code.trim();
          if (!body.hero_id) delete body.hero_id;
          if (body.hero_id && !body.character_id)
            body.character_id = characterSelect.value;
          const data = await api(create ? "/api/rooms" : "/api/rooms/join", {
            method: "POST",
            body: JSON.stringify(body),
          });
          session = {
            room_id: data.room.id,
            member_id: data.member_id,
            token: data.token,
            invite_code: data.invite_code,
          };
          sessionStorage.setItem("hexbound-session", JSON.stringify(session));
          room = data.room;
          saveSeat();
          close();
          renderRoom();
          connect();
        } catch (error) {
          $("#entry-error", form).textContent = error.message;
          submit.disabled = false;
        }
      };
    },
  );
}
function me() {
  return room?.party?.find((p) => p.id === session?.member_id);
}
function returnHome() {
  window.HexBoundLiveLog?.clear(); activeJournalKey=null;
  saveSeat();
  clearTimeout(reconnectTimer);
  const oldSocket = socket;
  socket = null;
  oldSocket?.close();
  session = null;
  room = null;
  connected = false;
  busy = false;
  chatRequest = null;
  draft = "";
  mobileTab = "story";
  sessionStorage.removeItem("hexbound-session");
  if (account) {
    Promise.all([api("/api/my/rooms"),api("/api/my/characters")])
      .then(([data,heroes]) => {
        accountRooms = data.items || [];
        vaultCharacters = heroes.items || [];
        home();
      })
      .catch((error) => {
        home();
        toast(error.message);
      });
  } else home();
}
async function restoreSeat(seat) {
  if (!seat) return;
  session = {
    room_id: seat.room_id,
    member_id: seat.member_id,
    token: seat.token,
    invite_code: seat.invite_code,
  };
  try {
    if (account) {
      const data = await api(
        `/api/rooms/${session.room_id}/${seat.token ? "claim" : "resume"}`,
        {
          method: "POST",
          body: JSON.stringify(seat.token ? { token: seat.token } : {}),
        },
      );
      room = data.room;
      session = {
        room_id: room.id,
        member_id: data.member_id,
        token: data.token,
        invite_code: data.invite_code,
      };
      if (seat.token)
        localStorage.setItem(
          "hexbound-seats",
          JSON.stringify(
            localSeats().filter(
              (s) =>
                !(s.room_id === seat.room_id && s.member_id === seat.member_id),
            ),
          ),
        );
    } else {
      if (!catalog.auth?.allow_guests) {
        location.href = "/account.html";
        return;
      }
      room = await api(`/api/rooms/${session.room_id}`);
    }
    sessionStorage.setItem("hexbound-session", JSON.stringify(session));
    saveSeat();
    renderRoom();
    connect();
  } catch (error) {
    session = null;
    room = null;
    toast(error.message);
    home();
  }
}
function hp(p) {
  const ratio = Math.max(
    0,
    Math.min(100, (100 * (p.hp || 0)) / (p.max_hp || 1)),
  );
  return `<div class="health ${ratio < 30 ? "low" : ""}"><i style="width:${ratio}%"></i></div><div class="hp-label"><span>HP ${esc(p.hp)} / ${esc(p.max_hp)}</span><span>AC ${esc(p.ac)}</span></div>`;
}
function partyHtml() {
  return (
    (room.party || [])
      .map(
        (p) =>
          `<div class="party-member sheet-trigger ${p.id === session.member_id ? "mine" : ""}" data-sheet="${esc(p.id)}" role="button" tabindex="0" aria-label="查看${esc(p.name)}的人物卡"><div class="avatar">${esc((p.name || "?")[0])}</div><div class="member-info"><div class="member-name">${esc(p.name)} ${p.id === session.member_id ? "<small>· 你</small>" : ""}${p.id === room.host_id ? ' <span class="mode-badge">♔</span>' : ""}</div><div class="member-class">${esc(p.class_name || p.character_id)} · ${p.online ? "在线" : "离线"}${room.combat?.turn_actor_id === p.id ? " · 当前回合" : ""}</div>${hp(p)}</div></div>`,
      )
      .join("") +
    Array.from(
      { length: Math.max(0, 6 - (room.party || []).length) },
      (_, i) =>
        `<div class="empty-seat"><div class="avatar">＋</div>等待旅人入席 <span>${String((room.party || []).length + i + 1).padStart(2, "0")}</span></div>`,
    ).join("")
  );
}
function rollHtml(roll) {
  const total = roll.total ?? roll.attack?.total ?? roll.damage?.total;
  const success = roll.success ?? roll.hit;
  const kinds = {
    attack: "攻击检定",
    check: "属性检定",
    initiative: "先攻",
    death_save: "死亡豁免",
    healing: "治疗",
  };
  const modifier = Number(roll.modifier || 0);
  const formula =
    roll.selected != null
      ? `${roll.selected} ${modifier < 0 ? "−" : "+"} ${Math.abs(modifier)} = ${total}`
      : `骰面 ${(roll.dice || []).join(" + ")}${roll.modifier != null ? ` + ${roll.modifier}` : ""} = ${total ?? "—"}`;
  return `<details class="roll-ticket"><summary><span>⬡ ${esc(roll.label || (roll.ability && `${abilities[roll.ability] || roll.ability}检定`) || kinds[roll.kind] || "规则凭据")} ${roll.ac != null ? `· AC ${esc(roll.ac)}` : roll.dc != null ? `· DC ${esc(roll.dc)}` : ""}${success != null ? ` · ${success ? "成功" : "未成功"}` : ""}</span><strong class="die-number">${total != null ? esc(total) : "查看"}</strong></summary><div class="roll-explanation"><p>${esc(formula)}</p><p>${roll.advantage ? "优势：取较高骰面。" : roll.disadvantage ? "劣势：取较低骰面。" : ""}${roll.critical ? "自然 20 · 暴击，伤害骰加倍。" : ""}</p>${roll.damage != null ? `<p>伤害骰 [${esc((roll.damage_dice || []).join(", "))}] · 实际伤害 ${esc(roll.damage)}</p>` : ""}<details><summary>原始规则凭据</summary><pre>${esc(JSON.stringify(roll, null, 2))}</pre></details></div></details>`;
}
function eventHtml(event) {
  const kind = event.kind || "narrative";
  if (kind === "system" && !event.roll)
    return `<div class="event system">${esc(event.text)}</div>`;
  const dm = ["dm", "narrative", "scene"].includes(kind);
  return `<article class="event ${kind === "chat" ? "chat" : ""}"><div class="event-meta"><span class="${dm ? "dm-label" : ""}">${dm ? `✦ ${event.source === "llm" ? "AI 主持人" : event.source === "fallback" ? "本地主持 · 模型回退" : "本地主持"}` : esc(event.actor_name || "规则引擎")}</span><span>·</span><span>${esc(event.adjudication_pending ? "待确认裁定" : kind === "chat" ? "桌边交谈" : event.roll ? "权威判定" : dm ? "冒险日志" : "角色行动")}</span><span style="margin-left:auto">${String(event.seq || event.id || "").padStart(3, "0")}</span></div><p>${esc(event.text)}</p>${event.roll ? rollHtml(event.roll) : ""}${event.suggested_action_id && (room.available_actions || []).some((a) => a.id === event.suggested_action_id && (!a.host_only || room.host_id === session.member_id)) ? `<button class="small" data-action="${esc(event.suggested_action_id)}" ${busy || !connected || room.status !== "playing" ? "disabled" : ""}>建议行动：${esc((room.available_actions || []).find((a) => a.id === event.suggested_action_id)?.label)} ↗</button>` : ""}</article>`;
}
let activeJournalKey = null;
let activeTextScope = null;
function renderRoom() {
  if (!room) return;
  const scope = JSON.stringify([room.id, session.member_id, room.scene_instance_id, room.membership_epoch, room.text_scope]);
  if (activeTextScope !== scope) {
    window.HexBoundLiveLog?.clear();
    activeJournalKey = null;
    activeTextScope = scope;
    draft = '';
    chatRequest = null;
    $('#intent')?.remove();
    document.querySelectorAll('.modal-backdrop').forEach((node) => node.remove());
    sheetState = null;
    characterChoices = null;
    builderState = null;
    selectedTarget = '';
    freeActionDraft = '';
    skillIntentId = '';
    freeActionPending = false;
    failedProposals.clear();
    previousCombatActive = false;
    showSettlement = false;
    encounterRoomId = null;
  }
  if(activeJournalKey) window.HexBoundLiveLog?.capture(activeJournalKey);
  trackEncounter();
  if ((room.combat?.active && combatView === "battle") || showSettlement) {
    renderBattleRoom();
    return;
  }
  const oldLog = $("#journal-log"),
    oldScroll = oldLog?.scrollTop || 0,
    atBottom =
      !oldLog ||
      oldLog.scrollHeight - oldLog.scrollTop - oldLog.clientHeight < 90;
  const oldInput = $("#intent");
  if (oldInput) draft = oldInput.value;
  const focused = document.activeElement?.id === "intent",
    selection = oldInput?.selectionStart;
  const mine = me(),
    host = room.host_id === session.member_id,
    active = room.status === "playing",
    combat = room.combat?.active === false ? null : room.combat,
    enemies = combat?.enemies || [],
    myTurn = !combat || combat.turn_actor_id === session.member_id;
  if (!enemies.some((e) => e.id === selectedTarget && e.hp > 0))
    selectedTarget = enemies.find((e) => e.hp > 0)?.id || "";
  const current = [...(room.party || []), ...enemies].find(
    (p) => p.id === combat?.turn_actor_id,
  );
  const scene = room.scene || {},
    events = room.events || [],
    canAct = active && connected && !busy && myTurn;
  app.innerHTML = `<div class="table-shell"><header class="table-header">${brand}<div class="room-title"><strong>${esc(room.name)}</strong><small>剧本 + AI DM / ${esc(statusNames[room.status] || room.status)}</small></div><div class="row"><span class="chip header-status"><span class="dot" style="background:${connected ? "var(--jade)" : "var(--brass)"}"></span>${connected ? "已连接" : "正在重连"}</span><button class="small" id="invite">邀请同伴 ↗</button><button class="small scene-toggle" id="scene-toggle">场景</button><button class="ghost" id="room-menu" aria-label="房间设置" ${busy ? "disabled" : ""}>•••</button></div></header>${!connected ? '<div class="notice">正在连接冒险桌，写入操作将在连接恢复后可用。</div>' : room.status === "paused" ? '<div class="notice">冒险已暂停。聊天仍然开放，等待房主继续。</div>' : ""}<main class="table-main"><aside class="sidebar party-sidebar ${mobileTab === "party" ? "mobile-visible" : ""}"><div class="section-title"><h2>同行者 / THE PARTY</h2><span class="mode-badge">${room.party.length} / 6</span></div>${partyHtml()}<div class="sidebar-bottom"><button class="small" id="copy-code">邀请码 ${esc(room.invite_code || session.invite_code)} ⧉</button><p>每个席位都有自己的命运。<br>你们将共同书写这段故事。</p></div></aside><section class="journal"><div class="journal-heading"><div><div class="eyebrow">${room.status === "lobby" ? "Before the journey" : "The adventure journal"}</div><h1>${esc(scene.title || room.name)}</h1></div><span class="chip">${esc(statusNames[room.status])}</span></div>${combat ? `<div class="combat-bar"><strong>第 ${esc(combat.round)} 轮</strong><span>${myTurn ? "轮到你行动" : `等待 ${esc(current?.name || "下一位角色")}`}</span><span style="margin-left:auto">${enemies.filter((e) => e.hp > 0).length} 名敌人</span></div>` : ""}<div class="journal-log" id="journal-log" role="log" aria-label="冒险记录">${room.status === "lobby" ? `<div class="welcome-scene"><div class="eyebrow">The first page is yours</div><h2>空白的一页，等你们落笔。</h2><p>邀请同伴入席，或独自开启旅程。<br>${host ? "准备好后，开始属于你们的冒险。" : "等待房主开始冒险。"}</p>${host ? '<button class="primary" id="start">启程 ↗</button>' : ""}</div>` : ""}${events.map(eventHtml).join("")}${!events.length && room.status !== "lobby" ? `<article class="event"><p>${esc(scene.text || "冒险日志正在载入…")}</p></article>` : ""}</div><div class="composer">${room.dm_pending ? '<p class="helper" role="status" style="margin-bottom:10px">✦ 主持人正在组织故事…</p>' : ""}<div class="actions">${(
    room.available_actions || []
  )
    .filter((a) => !a.host_only || host)
    .map(
      (a) =>
        `<button data-action="${esc(a.id)}" title="${esc(a.description || "")}" ${actionDisabledReason(a) ? `disabled title="${esc(actionDisabledReason(a))}"` : ""}>${esc(a.label)}${a.uses_remaining != null ? ` · 剩余 ${esc(a.uses_remaining)} 次` : ""} ↗</button>`,
    )
    .join(
      "",
    )}${combat && !(room.available_actions || []).some((a) => a.id === "end_turn") ? `<button id="end-turn" ${!canAct ? "disabled" : ""}>结束回合 →</button>` : ""}</div>${chatComposerHtml()}<div class="compose-hint"><span>行动请使用独立行动区 · Ctrl/⌘ + Enter 发送聊天</span><span>自动存档 · v${esc(room.version)}</span></div></div></section><aside class="sidebar scene-sidebar ${mobileTab === "scene" ? "mobile-visible" : ""}"><div class="section-title"><h2>此刻 / THE SCENE</h2><span>◇</span></div>${mapArt}<div class="eyebrow">Current location</div><h3>${esc(scene.title || "冒险尚未开始")}</h3><p>${esc(scene.text || "在这里，你将看到场景、目标和角色状态。")}</p>${scene.objective ? `<div class="objective"><div class="eyebrow">当前目标</div><p>${esc(scene.objective)}</p></div>` : ""}${enemies.length ? `<div class="objective"><div class="eyebrow">选择战斗目标</div>${enemies.map((e) => `<div class="enemy ${selectedTarget === e.id ? "selected" : ""}"><div class="row between"><strong>${esc(e.name)}</strong><span>${e.hp > 0 ? "敌对" : "已倒下"}</span></div>${hp(e)}${e.hp > 0 ? `<button class="small" data-target="${esc(e.id)}">${selectedTarget === e.id ? "✓ 当前目标" : "选择目标"}</button>` : ""}</div>`).join("")}</div>` : ""}${
    mine
      ? `<div class="objective"><div class="eyebrow">你的角色属性</div><div class="stat-grid">${Object.entries(
          mine.abilities || {},
        )
          .map(
            ([k, v]) =>
              `<div class="stat"><strong>${esc(v)}</strong><small>${esc(abilities[k] || k)}</small></div>`,
          )
          .join("")}</div></div>`
      : ""
  }<div class="objective"><div class="eyebrow">主持模式</div><p>${catalog.llm?.configured ? esc(catalog.llm.model || "自定义 LLM") : "本地演示主持 · 未配置 LLM"}</p></div></aside></main><nav class="mobile-nav" aria-label="冒险桌导航">${[
    ["story", "冒险日志"],
    ["party", "同行者"],
    ["scene", "场景 / 目标"],
  ]
    .map(
      ([id, label]) =>
        `<button data-tab="${id}" class="${mobileTab === id ? "active" : ""}">${label}</button>`,
    )
    .join("")}</nav></div>`;
  let log = $("#journal-log");
  if(window.HexBoundLiveLog){activeJournalKey=room.id+':story';window.HexBoundLiveLog.mount({key:activeJournalKey,placeholder:log,events,renderEvent:eventHtml,prefixHtml:$('.welcome-scene',log)?.outerHTML||'',emptyHtml:room.status==='lobby'?'':`<article class="event"><p>${esc(scene.text||'冒险日志正在载入…')}</p></article>`});log=$('#journal-log');}
  else if (atBottom) log.scrollTop = log.scrollHeight;
  else log.scrollTop = oldScroll;
  if (focused) {
    $("#intent").focus();
    $("#intent").setSelectionRange(selection, selection);
  }
  $("#invite").onclick = invite;
  bindSheetTriggers();
  if (combat) {
    $(".journal-heading").insertAdjacentHTML(
      "beforeend",
      '<button id="return-battle" class="small">返回战斗场景 ↗</button>',
    );
    $("#return-battle").onclick = () => {
      combatView = "battle";
      renderRoom();
    };
  }
  $(".sidebar-bottom").insertAdjacentHTML(
    "beforeend",
    '<button id="my-sheet" class="small" style="margin-top:14px">完整人物卡 ↗</button>',
  );
  $("#my-sheet").onclick = () => openCharacterSheet(session.member_id);
  refreshSheetVitals();
  installDmProposals();
  $("#copy-code").onclick = invite;
  $("#room-menu").onclick = roomMenu;
  $(".sidebar-bottom").insertAdjacentHTML(
    "beforeend",
    '<p><a href="/account.html">账号与安全 ↗</a></p>',
  );
  installLobbyBuilder();
  if ($("#start")) $("#start").disabled = !connected || busy || room.party.some(member=>member.build_ready===false);
  $("#start")?.addEventListener("click", () => command("start"));
  $("#end-turn")?.addEventListener("click", () => command("end_turn"));
  $("[id=scene-toggle]")?.addEventListener("click", () => {
    mobileTab = mobileTab === "scene" ? "story" : "scene";
    renderRoom();
  });
  app.querySelectorAll("[data-tab]").forEach(
    (b) =>
      (b.onclick = () => {
        mobileTab = b.dataset.tab;
        renderRoom();
      }),
  );
  bindActionTriggers();
  app.querySelectorAll("[data-target]").forEach(
    (b) =>
      (b.onclick = () => {
        selectedTarget = b.dataset.target;
        renderRoom();
      }),
  );
  bindChatComposer();
}
function healDialog() {
  openDialog(
    `<div class="row between"><h2 id="dialog-title">把药水交给谁？</h2><button data-close class="ghost">×</button></div><p class="helper" style="margin-top:18px">消耗你的一瓶治疗药水。战斗中消耗本回合动作。</p><div class="form">${room.party
      .filter((p) => !p.dead)
      .map(
        (p) =>
          `<button data-heal="${esc(p.id)}">${esc(p.name)} · HP ${esc(p.hp)} / ${esc(p.max_hp)}${p.id === session.member_id ? " · 自己" : ""}</button>`,
      )
      .join("")}</div>`,
    (overlay, close) => {
      overlay.querySelectorAll("[data-heal]").forEach(
        (b) =>
          (b.onclick = () => {
            close();
            command("capability_propose", { action_id: "heal", target_id: b.dataset.heal });
          }),
      );
    },
  );
}
async function invite() {
  const code = room.invite_code || session.invite_code;
  try {
    await navigator.clipboard.writeText(code);
    toast(`邀请码 ${code} 已复制`);
  } catch {
    openDialog(
      `<div class="row between"><h2 id="dialog-title">邀请同伴</h2><button data-close class="ghost">×</button></div><p class="helper" style="margin:20px 0">将下面的邀请码发送给同伴，他们可以从首页选择加入房间。</p><input aria-label="邀请码" readonly value="${esc(code)}">`,
    );
  }
}
function skillTargetDialog(action) {
  const allies = room.party.filter(
    (p) =>
      !p.dead &&
      (action.targets
        ? action.targets.some((target) => target.id === p.id)
        : action.effect !== "heal" || p.hp < p.max_hp),
  );
  openDialog(
    `<div class="row between"><h2 id="dialog-title">${esc(action.label)} · 选择目标</h2><button data-close class="ghost">×</button></div><div class="form">${allies.map((p) => `<button data-skill-target="${esc(p.id)}">${esc(p.name)} · HP ${esc(p.hp)} / ${esc(p.max_hp)}</button>`).join("") || '<p class="helper">没有合法目标。</p>'}</div>`,
    (overlay, close) => {
      overlay.querySelectorAll("[data-skill-target]").forEach(
        (b) =>
          (b.onclick = () => {
            close();
            command("capability_propose", {
              action_id: action.id,
              target_id: b.dataset.skillTarget,
            });
          }),
      );
    },
  );
}
function roomMenu() {
  if (busy) {
    toast("上一项操作仍在处理中，请稍候。");
    return;
  }
  const host = room.host_id === session.member_id;
  openDialog(
    `<div class="row between"><h2 id="dialog-title">冒险桌设置</h2><button class="ghost" data-close>×</button></div><div class="form"><p class="helper">${esc(room.name)} · 剧本 + AI DM<br>进度自动保存在服务器，刷新会恢复当前角色。</p>${host && room.status === "playing" ? '<button id="pause">暂停冒险</button>' : ""}${host && room.status === "paused" ? '<button id="resume">继续冒险</button>' : ""}${host && ["playing", "paused"].includes(room.status) ? '<button id="party-groups">分队与合队</button>' : ""}<button id="export-log">导出冒险日志</button><button id="view-rules">查看规则范围</button><button id="return-home" ${busy ? "disabled" : ""}>返回首页 · 保留我的席位</button><p class="helper">${account ? "席位已绑定账号，换设备登录后也可从首页继续冒险。" : "这是兼容模式的匿名席位。请保留浏览器数据，或登录账号认领席位。"}</p></div>`,
    (overlay, close) => {
      $("#pause", overlay)?.addEventListener("click", () => {
        close();
        command("pause");
      });
      $("#resume", overlay)?.addEventListener("click", () => {
        close();
        command("resume");
      });
      $("#party-groups", overlay)?.addEventListener("click", () => {
        close();
        openPartyGroups();
      });
      $("#view-rules", overlay).onclick = () => {
        close();
        rulesDialog();
      };
      $("#return-home", overlay).onclick = () => {
        close();
        returnHome();
      };
      $("#export-log", overlay).onclick = async () => {
        const button = $("#export-log", overlay);
        button.disabled = true;
        button.textContent = "正在汇集全部记录…";
        try {
          const all = [];
          let cursor = null;
          const exportScope = activeTextScope;
          while (true) {
            const page = await api(
              `/api/rooms/${session.room_id}/events${cursor ? '?cursor=' + encodeURIComponent(cursor) : ''}`,
            );
            if (activeTextScope !== exportScope) throw new Error('当前交流范围已变化，请重新导出。');
            all.push(...page.events);
            cursor = page.cursor;
            if (!page.has_more || !page.events.length) break;
          }
          const lines = [
            `# ${room.name}`,
            "",
            ...all.flatMap((e) => [
              `${e.actor_name || "主持人"} · ${e.kind}`,
              e.text || "",
              e.roll ? JSON.stringify(e.roll, null, 2) : "",
              "",
            ]),
          ];
          const blob = new Blob([lines.join("\n")], {
              type: "text/plain;charset=utf-8",
            }),
            url = URL.createObjectURL(blob),
            a = document.createElement("a");
          a.href = url;
          a.download = "hexbound-journal.txt";
          a.click();
          setTimeout(() => URL.revokeObjectURL(url), 1000);
        } catch (error) {
          toast(error.message);
        } finally {
          button.disabled = false;
          button.textContent = "导出冒险日志";
        }
      };
    },
  );
}
function chatComposerHtml() {
  return `<section class="table-chat" aria-label="队内文字交流"><div class="row between"><strong>队内交流</strong><small>当前文字频道：${esc(room.text_scope?.channel || "当前场景")}</small></div><p class="helper">商量和闲聊不会提交角色行动。与 NPC 交涉请使用行动区。</p><form class="compose-box" id="intent-form"><textarea id="intent" aria-label="队内聊天" maxlength="1500" placeholder="与当前频道的同伴商量…">${esc(draft)}</textarea><div class="compose-bottom"><small>暂停、等待 DM 或其他人的回合也可聊天</small><button class="primary" type="submit" ${!connected || chatRequest ? "disabled" : ""}>${chatRequest ? "发送中…" : "发送聊天 ↗"}</button></div></form></section>`;
}
function bindChatComposer() {
  $("#intent").oninput = (event) => (draft = event.target.value);
  $("#intent").onkeydown = (event) => {
    if (event.key === "Enter" && (event.ctrlKey || event.metaKey)) {
      event.preventDefault();
      $("#intent-form").requestSubmit();
    }
  };
  $("#intent-form").onsubmit = async (event) => {
    event.preventDefault();
    const text = $("#intent").value.trim();
    if (text) await chatCommand(text);
  };
}
async function chatCommand(text) {
  if (!connected || chatRequest || !session || !room) return false;
  const request = newCommandId(), scope = activeTextScope;
  const seat = session, roomId = session.room_id, memberId = session.member_id;
  const sameScope = () => session === seat && session?.room_id === roomId && session?.member_id === memberId && activeTextScope === scope;
  const current = () => sameScope() && chatRequest === request;
  const body = {
    command_id: request, expected_version: room.version,
    expected_action_revision: room.action_revision,
    expected_scene_instance_id: room.scene_instance_id,
    expected_membership_epoch: room.membership_epoch,
    type: "chat", payload: { text },
  };
  chatRequest = request;
  draft = $("#intent")?.value || text;
  renderRoom();
  try {
    const send = () => api(`/api/rooms/${roomId}/commands`, { method: "POST", body: JSON.stringify(body) });
    let result;
    try { result = await send(); }
    catch (error) {
      if (!(error instanceof TypeError) && !error.retrySameCommand) throw error;
      if (!current()) return false;
      result = await send();
    }
    if (!current()) return false;
    if (result.room && result.room.version >= room.version) room = result.room;
    if (($("#intent")?.value || draft).trim() === text) {
      draft = "";
      if ($("#intent")) $("#intent").value = "";
    }
    return true;
  } catch (error) {
    if (current()) toast(error.message);
    return false;
  } finally {
    if (chatRequest === request) {
      chatRequest = null;
      if (sameScope()) renderRoom();
    }
  }
}
async function command(type, payload = {}) {
  if (type === "capability_propose" && payload.action_id === "end_turn") {
    type = "end_turn";
    payload = {};
  }
  if (type === "chat") return chatCommand(payload.text);
  if (busy || !connected) return false;
  if (type === "director_propose" || type === "capability_propose") actionEntry = "free";
  busy = true;
  renderRoom();
  const body = {
    command_id: newCommandId(),
    expected_version: room.version,
    expected_action_revision: room.action_revision,
    expected_scene_instance_id: room.scene_instance_id,
    expected_membership_epoch: room.membership_epoch,
    type,
    payload,
  };
  try {
    let result;
    try {
      result = await api(`/api/rooms/${session.room_id}/commands`, {
        method: "POST",
        body: JSON.stringify(body),
      });
    } catch (error) {
      if (!(error instanceof TypeError) && !error.retrySameCommand) throw error;
      toast("连接波动，正在安全重试同一操作…");
      result = await api(`/api/rooms/${session.room_id}/commands`, {
        method: "POST",
        body: JSON.stringify(body),
      });
    }
    if (result.room && result.room.version >= room.version) room = result.room;
    return true;
  } catch (error) {
    if (error.status === 409) {
      try {
        room = await api(`/api/rooms/${session.room_id}`);
      } catch {}
      toast("冒险已发生变化，已同步最新状态，请重新选择行动。");
    } else toast(error.message);
    return false;
  } finally {
    busy = false;
    renderRoom();
  }
}
function connect() {
  if (!session) return;
  clearTimeout(reconnectTimer);
  const ws = new WebSocket(
    `${location.protocol === "https:" ? "wss" : "ws"}://${location.host}/api/rooms/${session.room_id}/ws`,
  );
  socket = ws;
  ws.onopen = () => {
    ws.send(JSON.stringify({ token: session.token }));
  };
  ws.onmessage = (e) => {
    if (socket !== ws) return;
    try {
      const data = JSON.parse(e.data);
      if (data.type === "snapshot" && data.room) {
        connected = true;
        retry = 0;
        if (!room || data.room.version >= room.version) room = data.room;
        renderRoom();
      } else if (data.type === "error")
        toast(data.detail || data.message || "连接出现问题");
    } catch {
      toast("收到无效同步消息，正在重新同步");
    }
  };
  ws.onclose = (e) => {
    if (socket !== ws) return;
    connected = false;
    renderRoom();
    if (e.code === 4401 || e.code === 4403 || e.code === 1008) {
      toast("会话已失效或账号权限已变更，请前往账号中心重新登录。");
      return;
    }
    reconnectTimer = setTimeout(connect, Math.min(15000, 1000 * 2 ** retry++));
  };
  ws.onerror = () => ws.close();
}
async function boot() {
  try {
    catalog = await api("/api/catalog");
    try {
      const identity = await api("/api/auth/me");
      account = identity.user;
      csrfToken = identity.csrf_token;
      if (account.must_change_password) {
        location.href = "/account.html";
        return;
      }
      accountRooms = (await api("/api/my/rooms")).items || [];
      try {
        vaultCharacters = (await api("/api/my/characters")).items || [];
      } catch {
        vaultCharacters = [];
      }
    } catch (error) {
      if (error.status !== 401) throw error;
      account = null;
      csrfToken = "";
      accountRooms = [];
    }
    try {
      catalog.publishedScenarios =
        (await api("/api/content?kind=scenario")).items || [];
    } catch {
      catalog.publishedScenarios = [];
    }
    if (session?.token && account) {
      // Legacy seats are claimed explicitly from the home page, never silently.
      sessionStorage.removeItem("hexbound-session");
      session = null;
    }
    if (session) {
      try {
        room = await api(`/api/rooms/${session.room_id}`);
        saveSeat();
        renderRoom();
        connect();
        return;
      } catch (error) {
        if ([401, 403, 404].includes(error.status)) {
          sessionStorage.removeItem("hexbound-session");
          session = null;
          toast("原冒险桌或身份已失效，请重新入席。");
        } else throw error;
      }
    }
    home();
    const query = new URLSearchParams(location.search);
    if (
      query.has("scenario") ||
      ["create", "join"].includes(query.get("entry"))
    )
      entryDialog(query.get("entry") === "join" ? "join" : "create");
  } catch (error) {
    app.innerHTML = `<div class="loading"><div>冒险桌暂时无法连接</div><span>${esc(error.message)}</span><button id="retry">重新连接</button></div>`;
    $("#retry").onclick = boot;
  }
}

function trackEncounter() {
  if (encounterRoomId !== room.id) {
    encounterRoomId = room.id;
    previousCombatActive = false;
    showSettlement = false;
    combatView = "battle";
  }
  const active = !!room.combat?.active;
  if (active && !previousCombatActive) {
    combatView = "battle";
    showSettlement = false;
    combatCategory = "all";
    combatQuery = "";
  }
  if (!active && previousCombatActive) {
    showSettlement = true;
    combatView = "battle";
  }
  previousCombatActive = active;
}
function signed(value) {
  return Number(value) >= 0 ? `+${value}` : String(value);
}
function conditionLabels(actor) {
  const names = {
    poisoned: "中毒",
    prone: "倒地",
    restrained: "束缚",
    stunned: "震慑",
    unconscious: "昏迷",
    frightened: "恐慌",
    blinded: "目盲",
    charmed: "魅惑",
    paralyzed: "麻痹",
    deafened: "耳聋",
    invisible: "隐形",
    incapacitated: "失能",
    grappled: "擒抱",
    petrified: "石化",
    exhaustion: "力竭",
  };
  const values = (actor.conditions || []).map((c) =>
    typeof c === "string" ? c : c.name || c.id || c.condition || "状态",
  );
  if (actor.dead) values.push("死亡");
  else if (actor.hp <= 0)
    values.push(actor.stable ? "伤势稳定" : "倒地 / 死亡豁免");
  return (
    values
      .map(
        (value) =>
          `<span class="condition bad">${esc(names[value] || value)}</span>`,
      )
      .join("") +
    (actor.concentration
      ? `<span class="condition focus">专注 · ${esc(actor.concentration.name || actor.concentration.spell_name || actor.concentration.spell_id || "法术")}</span>`
      : "")
  );
}
function actionDisabledReason(action) {
  if (!connected) return "连接恢复后可行动";
  if (busy) return "上一项行动仍在处理中";
  if (room.status !== "playing")
    return room.status === "paused" ? "冒险已暂停" : "当前不是冒险进行阶段";
  if (action.host_only && room.host_id !== session.member_id)
    return "由房主推进队伍";
  if (action.supported === false)
    return action.disabled_reason || "仅供参考，尚未自动化";
  if (action.disabled_reason) return action.disabled_reason;
  if (action.disabled || action.enabled === false)
    return action.reason || "当前不可用";
  if (
    room.combat?.active &&
    room.combat.turn_actor_id !== session.member_id &&
    action.action_cost !== "reaction"
  )
    return "等待你的回合";
  return "";
}
function ownedActions() {
  const all = new Map(
    (room.available_actions || []).map((action) => [action.id, action]),
  );
  for (const action of room.combat_capabilities || [])
    all.set(action.id, { ...(all.get(action.id) || {}), ...action });
  return [...all.values()];
}
function actionGroup(action) {
  if (action.kind === "spell" || action.id.startsWith("cast:")) return "spells";
  if (action.kind === "feature" || action.id.startsWith("feature:"))
    return "features";
  if (action.kind === "item" || action.id === "heal") return "items";
  return "actions";
}
function actionPaletteHtml() {
  const actions = ownedActions().filter(
    (a) =>
      a.id !== "end_turn" &&
      (!a.host_only || room.host_id === session.member_id),
  );
  const selected = actions.filter(
    (a) =>
      (combatCategory === "all" || actionGroup(a) === combatCategory) &&
      (!combatQuery ||
        `${a.label} ${a.description || ""}`
          .toLowerCase()
          .includes(combatQuery.toLowerCase())),
  );
  return (
    selected
      .map((action) => {
        const reason = actionDisabledReason(action);
        return `<button class="combat-action" data-action="${esc(action.id)}" ${reason ? "disabled" : ""} title="${esc(reason || action.description || "")}"><span class="row between"><strong>${esc(action.label || action.name)}</strong><span class="action-cost">${{ action: "动作", bonus: "附赠动作", bonus_action: "附赠动作", reaction: "反应", free: "自由", none: "自由", attack: "攻击" }[action.action_cost] || "动作"}</span></span><small>${esc(action.description || "按服务端规则执行")}</small>${action.uses_remaining != null ? `<small>剩余 ${esc(action.uses_remaining)} 次</small>` : ""}${reason ? `<small class="action-unavailable">${esc(reason)}</small>` : `<small>${action.cast_levels?.length ? "选择法术位与目标 ↗" : action.target === "enemy" ? "对选中敌人使用 ↗" : action.target === "ally" ? "选择队友 ↗" : "执行行动 ↗"}</small>`}</button>`;
      })
      .join("") ||
    '<div class="combat-action-empty">没有匹配的能力。更改筛选或在人物卡中查看完整能力。</div>'
  );
}
function combatEvents() {
  const events = room.events || [];
  if (combatLogView === "story") return events;
  const combatKinds = new Set([
    "roll",
    "combat",
    "action",
    "damage",
    "healing",
    "death",
    "initiative",
    "spell",
    "condition",
    "resource",
  ]);
  return events.filter((event) => event.roll || combatKinds.has(event.kind));
}
function battleAllyHtml(member) {
  return `<article class="ally-card ${room.combat?.turn_actor_id === member.id ? "current" : ""}"><div class="row"><div class="avatar">${esc(member.name[0])}</div><div><button class="member-name" data-sheet="${esc(member.id)}">${esc(member.name)}${member.id === session.member_id ? " · 你" : ""} ↗</button><div class="member-class">${esc(member.class_name || member.class_id || member.character_id)} · Lv.${esc(member.level || 1)}</div></div></div>${hp(member)}<div class="conditions">${conditionLabels(member)}</div></article>`;
}
function renderBattleRoom() {
  const previousInput = $("#intent");
  if (previousInput) draft = previousInput.value;
  const oldLog = $("#journal-log"),
    oldScroll = oldLog?.scrollTop || 0,
    atBottom =
      !oldLog || oldLog.scrollHeight - oldScroll - oldLog.clientHeight < 90;
  const combat = room.combat || {},
    enemies = combat.enemies || [],
    mine = me(),
    myTurn = combat.turn_actor_id === session.member_id;
  const actors = [...(room.party || []), ...enemies],
    current = actors.find((a) => a.id === combat.turn_actor_id);
  if (!enemies.some((enemy) => enemy.id === selectedTarget && enemy.hp > 0))
    selectedTarget = enemies.find((enemy) => enemy.hp > 0)?.id || "";
  const order = (combat.order || []).map((entry) =>
    typeof entry === "string" ? { id: entry } : entry,
  );
  const endAction = (room.available_actions || []).find(
    (a) => a.id === "end_turn",
  );
  app.innerHTML = `<div class="encounter-shell"><header class="encounter-top"><div class="encounter-title"><div class="eyebrow">${showSettlement ? "ENCOUNTER RESOLVED" : "THE ENCOUNTER"} / ${esc(room.name)}</div><h1>${showSettlement ? "战斗结束，故事继续。" : esc(room.scene?.title || "遭遇战")}</h1></div><div class="row"><button class="small" id="battle-sheet">人物卡 ↗</button><button class="small" id="battle-story">探索日志</button><button class="ghost" id="room-menu" ${busy ? "disabled" : ""}>•••</button></div></header>${!connected ? '<div class="notice">正在重连。战斗状态由服务端保存。</div>' : room.status === "paused" ? '<div class="notice">冒险已暂停，等待房主继续。</div>' : ""}<main class="encounter-layout"><aside class="encounter-allies"><div class="section-title"><h2>你的队伍 / PARTY</h2><span class="mode-badge">${room.party.length} / 6</span></div>${room.party.map(battleAllyHtml).join("")}</aside><section class="encounter-center">${
    showSettlement
      ? settlementHtml()
      : `<div class="initiative-track" aria-label="先攻顺序"><span class="initiative-label">先攻顺序<br>ROUND ${esc(combat.round || 1)}</span>${order
          .map((entry) => {
            const actor = actors.find(
              (a) => a.id === (entry.id || entry.actor_id),
            );
            return `<div class="initiative-token ${(entry.id || entry.actor_id) === combat.turn_actor_id ? "current" : ""} ${enemies.some((e) => e.id === (entry.id || entry.actor_id)) ? "enemy-turn" : ""}"><strong>${esc(actor?.name || entry.name || entry.id || entry.actor_id)}</strong><small>${(entry.id || entry.actor_id) === combat.turn_actor_id ? "当前回合" : actor?.hp <= 0 ? "已倒下" : entry.initiative != null ? `先攻 ${entry.initiative}` : "等待行动"}</small></div>`;
          })
          .join(
            "",
          )}</div><div class="battlefield"><div class="battlefield-heading"><div><h2>选择你的目标</h2><p>点击敌方卡片，再选择一个行动。</p></div><span class="chip">${enemies.filter((e) => e.hp > 0).length} 个存活敌人</span></div><div class="enemy-grid">${enemies.map((enemy) => `<button class="combatant-card ${selectedTarget === enemy.id ? "targeted" : ""} ${enemy.hp <= 0 ? "defeated" : ""}" data-target="${esc(enemy.id)}" ${enemy.hp <= 0 ? "disabled" : ""} aria-pressed="${selectedTarget === enemy.id}"><div class="eyebrow">${enemy.hp <= 0 ? "DEFEATED" : "HOSTILE"}</div><div class="card-sigil" aria-hidden="true">♜</div><h3>${esc(enemy.name)}</h3>${hp(enemy)}<div class="conditions">${conditionLabels(enemy)}</div><div class="target-label">${enemy.hp <= 0 ? "已击倒" : selectedTarget === enemy.id ? "◎ 当前目标" : "选择为目标"}</div></button>`).join("")}</div></div><div class="combat-turn-panel"><div><h3>${myTurn ? "轮到你行动" : `等待 ${esc(current?.name || "下一位角色")}`}</h3><p>${myTurn ? "每次消耗都会实时同步给队伍。" : "可以查看人物卡、阅读记录或与同伴交谈。"}</p><div class="turn-resources"><span class="turn-resource ${combat.action_used ? "used" : ""}"><i></i>动作 ${combat.action_used ? "已使用" : "可用"}</span><span class="turn-resource ${combat.bonus_action_used ? "used" : ""}"><i></i>附赠 ${combat.bonus_action_used ? "已使用" : "可用"}</span><span class="turn-resource ${(combat.reactions_used || []).includes(session.member_id) ? "used" : ""}"><i></i>反应 ${(combat.reactions_used || []).includes(session.member_id) ? "已使用" : "保留"}</span>${combat.movement_budget != null ? `<span class="turn-resource">移动 ${Math.max(0, combat.movement_budget - (combat.movement_spent || 0))} / ${combat.movement_budget} 尺</span>` : ""}${combat.attacks_remaining != null ? `<span class="turn-resource">剩余攻击 ${esc(combat.attacks_remaining)}</span>` : ""}</div></div><button id="battle-end-turn" class="primary" ${!endAction || actionDisabledReason(endAction) ? "disabled" : ""}>结束回合 →</button></div><section class="combat-actions"><div class="action-toolbar"><div class="action-tabs">${Object.entries(
          {
            all: "全部",
            actions: "动作",
            spells: "法术",
            features: "特性",
            items: "物品",
          },
        )
          .map(
            ([id, label]) =>
              `<button data-action-category="${id}" class="${combatCategory === id ? "active" : ""}">${label}</button>`,
          )
          .join(
            "",
          )}</div><input class="action-search" id="combat-action-search" placeholder="搜索能力…" aria-label="搜索可用能力" value="${esc(combatQuery)}"></div><div class="action-grid" id="action-grid">${actionPaletteHtml()}</div></section>`
  }</section><aside class="encounter-ledger"><div class="encounter-subnav"><button data-combat-log="combat" class="${combatLogView === "combat" ? "active" : ""}">战斗记录</button><button data-combat-log="story" class="${combatLogView === "story" ? "active" : ""}">全部日志</button></div><div class="journal-log" id="journal-log" role="log" aria-label="战斗与规则记录">${combatEvents().map(eventHtml).join("") || '<p class="helper">行动发生后，规则凭据会显示在这里。</p>'}</div><div class="composer">${chatComposerHtml()}</div></aside></main></div>`;
  if(window.HexBoundLiveLog){activeJournalKey=room.id+':combat:'+combatLogView;window.HexBoundLiveLog.mount({key:activeJournalKey,placeholder:$('#journal-log'),events:combatEvents(),renderEvent:eventHtml,prefixHtml:'',emptyHtml:'<p class="helper">行动发生后，规则凭据会显示在这里。</p>'});}
  $("#battle-sheet").onclick = () => openCharacterSheet(session.member_id);
  $("#room-menu").onclick = roomMenu;
  $("#battle-story").onclick = () => {
    showSettlement = false;
    combatView = "story";
    renderRoom();
  };
  $("#return-exploration")?.addEventListener("click", () => {
    showSettlement = false;
    combatView = "story";
    renderRoom();
  });
  $("#battle-end-turn")?.addEventListener("click", () => command("end_turn"));
  app.querySelectorAll("[data-target]").forEach(
    (button) =>
      (button.onclick = () => {
        selectedTarget = button.dataset.target;
        renderRoom();
      }),
  );
  app.querySelectorAll("[data-action-category]").forEach(
    (button) =>
      (button.onclick = () => {
        combatCategory = button.dataset.actionCategory;
        renderRoom();
      }),
  );
  app.querySelectorAll("[data-combat-log]").forEach(
    (button) =>
      (button.onclick = () => {
        combatLogView = button.dataset.combatLog;
        renderRoom();
      }),
  );
  $("#combat-action-search")?.addEventListener("input", (event) => {
    combatQuery = event.target.value;
    $("#action-grid").innerHTML = actionPaletteHtml();
    bindActionTriggers();
  });
  bindSheetTriggers();
  bindActionTriggers();
  refreshSheetVitals();
  installDmProposals();
  bindChatComposer();
  const log = $("#journal-log");
  if(!window.HexBoundLiveLog) log.scrollTop = atBottom ? log.scrollHeight : oldScroll;
}
function settlementHtml() {
  const enemies = room.combat?.enemies || [],
    standing = room.party.filter((p) => p.hp > 0 && !p.dead).length;
  const won = enemies.length > 0 && enemies.every((enemy) => enemy.hp <= 0);
  return `<section class="settlement"><div class="eyebrow">${won ? "VICTORY" : "ENCOUNTER CLOSED"}</div><h2>${won ? "余音散去，灯火未熄。" : "这一场战斗，已写入记录。"}</h2><p>骰点、伤害和资源消耗已保存。查看队伍状态，再决定下一步。</p><div class="settlement-stats"><span><strong>${room.combat?.round || "—"}</strong>战斗轮数</span><span><strong>${enemies.filter((enemy) => enemy.hp <= 0).length}</strong>击倒敌人</span><span><strong>${standing} / ${room.party.length}</strong>仍站立的同伴</span></div><button id="return-exploration" class="primary">返回探索与结算记录 ↗</button></section>`;
}
function bindActionTriggers() {
  app.querySelectorAll("[data-action]").forEach(
    (button) =>
      (button.onclick = () => {
        const action = [
          ...(room.available_actions || []),
          ...(room.combat_capabilities || []),
        ].find((item) => item.id === button.dataset.action);
        if (!action) {
          toast("此行动已不可用，请查看最新场景。");
          return;
        }
        const reason = actionDisabledReason(action);
        if (reason) {
          toast(reason);
          return;
        }
        if (action.id === "end_turn") {
          command("end_turn");
          return;
        }
        if (
          action.kind === "spell" ||
          action.id.startsWith("cast:") ||
          action.cast_levels?.length ||
          action.max_targets > 1 ||
          action.resource_amount ||
          action.id === "feature:lay-on-hands"
        ) {
          castActionDialog(action);
          return;
        }
        if (action.target === "ally") {
          skillTargetDialog(action);
          return;
        }
        if (action.id === "heal") {
          healDialog();
          return;
        }
        let target =
          action.target === "self"
            ? session.member_id
            : action.target === "enemy" || action.id === "attack"
              ? selectedTarget
              : null;
        if (
          action.target === "enemy" &&
          action.targets?.length &&
          !action.targets.some((item) => item.id === target)
        ) {
          selectedTarget = action.targets[0].id;
          target = selectedTarget;
        }
        command("capability_propose", {
          action_id: action.id,
          ...(target
            ? { target_id: action.target === "enemy" ? selectedTarget : target }
            : {}),
        });
      }),
  );
}
function castActionDialog(action) {
  const targetList =
    action.targets ||
    (action.target === "ally"
      ? room.party
      : action.target === "enemy"
        ? room.combat?.enemies || []
        : [{ id: session.member_id, name: me()?.name || "自己" }]);
  const multiple = Number(action.max_targets || 1) > 1;
  const levels = action.cast_levels || [];
  openDialog(
    `<div class="row between"><div><div class="eyebrow">CONFIRM YOUR ACTION</div><h2 id="dialog-title" style="margin-top:8px">${esc(action.label)}</h2></div><button class="ghost" data-close aria-label="关闭">×</button></div><form class="form" id="cast-form"><p class="helper">${esc(action.description || "效果与资源消耗由服务端规则执行。")}${action.area_mode === "encounter-selection" ? "<br>当前为无网格遭遇范围：从合法目标中选择。" : ""}</p>${levels.length ? `<label>消耗法术位<select name="slot">${levels.map((slot, index) => `<option value="${index}" ${slot.current <= 0 ? "disabled" : ""}>${slot.source === "pact" ? "契约法术位" : "法术位"} · ${slot.level} 环 · 剩余 ${slot.current}</option>`).join("")}</select></label>` : ""}<div><p class="helper" style="margin-bottom:10px">${multiple ? `选择 ${action.min_targets || 1}–${action.max_targets} 个目标` : "选择目标"}</p><div class="target-checklist">${targetList.map((target, index) => `<label><input type="${multiple ? "checkbox" : "radio"}" name="target" value="${esc(target.id)}" ${!multiple && (target.id === selectedTarget || action.target === "self" || (index === 0 && !targetList.some((t) => t.id === selectedTarget))) ? "checked" : ""}>${esc(target.name)}</label>`).join("")}</div></div>${action.resource_amount || action.id === "feature:lay-on-hands" ? `<label>投入治疗点数<input name="resource_amount" type="number" min="1" max="${esc(action.max_amount || action.resource_amount?.max || me()?.resources?.["lay-on-hands"]?.current || 500)}" value="1" required></label>` : ""}<p id="cast-error" class="error" role="alert"></p><button type="submit" class="primary">审核目标与行动计划 ↗</button></form>`,
    (overlay, close) => {
      $("#cast-form", overlay).onsubmit = async (event) => {
        event.preventDefault();
        const form = event.currentTarget;
        const targets = [...form.querySelectorAll("[name=target]:checked")].map(
          (input) => input.value,
        );
        if (
          targets.length < Number(action.min_targets || 1) ||
          (multiple && targets.length > Number(action.max_targets))
        ) {
          $("#cast-error", overlay).textContent = "请选择规定数量的合法目标。";
          return;
        }
        const payload = {
          action_id: action.id,
          ...(multiple ? { target_ids: targets } : { target_id: targets[0] }),
        };
        const slotInput = $("[name=slot]", form);
        if (slotInput) {
          const slot = levels[Number(slotInput.value)];
          payload.slot_level = slot.level;
          payload.slot_source = slot.source;
        }
        const amount = $("[name=resource_amount]", form);
        if (amount) payload.resource_amount = Number(amount.value);
        close();
        await command("capability_propose", payload);
      };
    },
  );
}

const skillNames = {
  acrobatics: "杂技",
  "animal-handling": "驯兽",
  arcana: "奥秘",
  athletics: "运动",
  deception: "欺瞒",
  history: "历史",
  insight: "洞悉",
  intimidation: "威吓",
  investigation: "调查",
  medicine: "医药",
  nature: "自然",
  perception: "察觉",
  performance: "表演",
  persuasion: "游说",
  religion: "宗教",
  "sleight-of-hand": "巧手",
  stealth: "隐匿",
  survival: "求生",
};
const resourceNames = {
  rage: "狂暴",
  ki: "气",
  sorcery_points: "术法点",
  lay_on_hands: "圣疗池",
  channel_divinity: "引导神力",
  wild_shape: "荒野形态",
  bardic_inspiration: "诗人激励",
  second_wind: "回气",
  action_surge: "动作如潮",
  superiority_dice: "卓越骰",
  arcane_recovery: "奥术回想",
  indomitable: "不屈",
  luck: "幸运",
  hit_dice: "生命骰",
};
let sheetCatalog = { spells: [], classes: [], loaded: false };
function bindSheetTriggers() {
  app.querySelectorAll("[data-sheet]").forEach((element) => {
    element.onclick = () => openCharacterSheet(element.dataset.sheet);
    element.onkeydown = (event) => {
      if (event.key === "Enter" || event.key === " ") {
        event.preventDefault();
        openCharacterSheet(element.dataset.sheet);
      }
    };
  });
}
function refreshSheetVitals() {
  if (!sheetState) return;
  if(sheetState.overlay?.isConnected){
    const submit=$('#level-up-form [type=submit]',sheetState.overlay);
    if(submit)submit.disabled=!connected||busy||sheetState.loading||sheetState.mutationPending||!sheetState.owner||!sheetState.advancement?.can_level_up||!!room.combat?.active;
    const status=$('[data-sheet-connection]',sheetState.overlay);
    if(status)status.textContent=connected?'':'正在连接冒险桌，恢复连接后可确认成长。';
  }
  const latest = room.party.find((member) => member.id === sheetState.memberId);
  if (latest)
    document
      .querySelectorAll(".sheet-live-hp")
      .forEach(
        (label) =>
          (label.textContent = `HP ${latest.hp} / ${latest.max_hp} · AC ${latest.ac}`),
      );
}
async function fetchCompendium(kind, classId = "") {
  const items = [];
  let page = 1;
  while (true) {
    const data = await api(
      `/api/compendium?kind=${kind}${classId ? `&class_id=${encodeURIComponent(classId)}` : ""}&page=${page}&page_size=50`,
    );
    items.push(...(data.items || []));
    if (
      !data.items?.length ||
      items.length >= data.total ||
      data.items.length < 50
    )
      break;
    page++;
  }
  return items;
}
async function ensureSheetCatalog() {
  if (sheetCatalog.loaded) return;
  const [spells, classes] = await Promise.all([
    fetchCompendium("spells"),
    fetchCompendium("classes"),
  ]);
  sheetCatalog = { spells, classes, loaded: true };
}
async function openCharacterSheet(memberId, initialTab = "overview") {
  const requestScope = activeTextScope;
  const member = room.party.find((p) => p.id === memberId);
  if (!member) return;
  return openDialog(
    `<div class="row between"><h2 id="dialog-title">${esc(member.name)} · 人物档案</h2><button class="ghost" data-close aria-label="关闭">×</button></div><div id="character-sheet" style="margin-top:22px"><p class="helper" role="status">正在读取完整人物卡与成长状态…</p></div>`,
    async (overlay, close) => {
      $(".modal", overlay).classList.add("sheet-modal");
      sheetTab = initialTab;
      sheetState = {
        scope: requestScope,
        memberId,
        overlay,
        close,
        loading: true,
        character: member,
        owner: memberId === session.member_id,
      };
      try {
        const data = await api(
          `/api/rooms/${session.room_id}/characters/${memberId}`,
        );
        if (!overlay.isConnected || activeTextScope !== requestScope || sheetState?.overlay !== overlay) return;
        sheetState = {
          ...sheetState,
          ...data,
          memberId,
          overlay,
          close,
          loading: false,
        };
        renderCharacterSheet();
      } catch (error) {
        if (overlay.isConnected && activeTextScope === requestScope)
          $("#character-sheet", overlay).innerHTML =
            `<p class="error">${esc(error.message)}</p><p class="helper">完整人物数据尚未读取。当前生命 ${member.hp} / ${member.max_hp}。</p>`;
      }
    },
  );
}
async function reloadCharacterSheet() {
  if (!sheetState?.overlay?.isConnected) return;
  const state = sheetState;
  const data = await api(
    `/api/rooms/${session.room_id}/characters/${state.memberId}`,
  );
  if (!state.overlay.isConnected || activeTextScope !== state.scope || sheetState?.overlay !== state.overlay) return;
  sheetState = { ...state, ...data };
  renderCharacterSheet();
}
function characterData() {
  const c = sheetState?.character || {};
  return c.character || c;
}
function classLabel(character) {
  return (
    character.class_name ||
    sheetCatalog.classes.find((item) => item.id === character.class_id)?.name ||
    character.class_id ||
    character.class ||
    "冒险者"
  );
}
function sheetResourcesHtml(character) {
  const list = Object.entries(character.resources || {});
  if (character.hit_dice) list.unshift(["hit_dice", character.hit_dice]);
  if (!list.length)
    return '<p class="helper">当前角色没有可追踪的职业资源。</p>';
  return `<div class="sheet-resources">${list.map(([id, value]) => `<div class="sheet-resource">${esc(value.name || resourceNames[id] || id)}<strong>${esc(value.current ?? value.remaining ?? "—")} / ${esc(value.max ?? "—")}</strong><small>${id === "hit_dice" ? `d${esc(value.die || "—")}` : { short: "短休恢复", long: "长休恢复", short_rest: "短休恢复", long_rest: "长休恢复" }[value.recharge] || value.recharge || "按规则恢复"}${value.automated === false ? " · 需人工裁定" : ""}</small></div>`).join("")}</div>`;
}
function featuresHtml(character) {
  const features = character.features || [];
  return (
    features
      .map((feature) => {
        if (typeof feature === "string")
          feature = { id: feature, name: feature };
        return `<article class="sheet-feature"><div class="row between"><h4>${esc(feature.name || feature.id)}</h4><span class="badge">${feature.automated ? "规则自动化" : "参考 / 人工裁定"}</span></div><p>${esc(feature.description || feature.note || "详情见对应职业规则。")}</p>${feature.level ? `<p>获得等级 · ${esc(feature.level)}</p>` : ""}</article>`;
      })
      .join("") || '<p class="helper">暂无已获得的职业特性。</p>'
  );
}
function sheetOverviewHtml(character) {
  return `<div class="sheet-stats">${Object.entries(abilities)
    .map(([id, label]) => {
      const score = character.abilities?.[id];
      return `<div class="sheet-stat"><small>${label}</small><strong>${esc(score ?? "—")}</strong><em>${score != null ? signed(Math.floor((score - 10) / 2)) : "—"}</em></div>`;
    })
    .join(
      "",
    )}</div><div class="sheet-columns"><section class="sheet-section"><h3>战斗与成长</h3><div class="sheet-list"><div class="sheet-list-row"><span>生命 / 护甲</span><strong class="sheet-live-hp">HP ${character.hp} / ${character.max_hp} · AC ${character.ac}</strong></div><div class="sheet-list-row"><span>等级 / 经验</span><strong>Lv.${character.level || 1} · ${character.xp ?? 0} XP</strong></div><div class="sheet-list-row"><span>熟练加值</span><strong>${signed(character.proficiency ?? 2)}</strong></div><div class="sheet-list-row"><span>子职业</span><span>${esc(character.subclass_name || character.subclass_id || "尚未选择")}</span></div><div class="sheet-list-row"><span>死亡豁免</span><span>成功 ${character.death_successes || 0} / 失败 ${character.death_failures || 0}</span></div></div><div class="conditions">${conditionLabels(character)}</div></section><section class="sheet-section"><h3>可追踪资源</h3>${sheetResourcesHtml(character)}</section></div><section class="sheet-section"><h3>职业特性</h3>${featuresHtml(character)}</section>`;
}
function sheetSkillsHtml(character) {
  const proficient = character.skills || [],
    expertise = character.expertise || [];
  return `<div class="sheet-columns"><section class="sheet-section"><h3>18 项技能</h3><div class="sheet-list">${Object.entries(
    skillNames,
  )
    .map(
      ([id, label]) =>
        `<div class="sheet-list-row"><span>${label} <small>${expertise.includes(id) ? "专精" : proficient.includes(id) ? "熟练" : ""}</small></span><strong>${character.skill_modifiers?.[id] != null ? signed(character.skill_modifiers[id]) : "—"}</strong></div>`,
    )
    .join(
      "",
    )}</div></section><section class="sheet-section"><h3>六项豁免</h3><div class="sheet-list">${Object.entries(
    abilities,
  )
    .map(
      ([id, label]) =>
        `<div class="sheet-list-row"><span>${label} <small>${(character.saving_throws || []).includes(id) ? "熟练" : ""}</small></span><strong>${character.save_modifiers?.[id] != null ? signed(character.save_modifiers[id]) : "—"}</strong></div>`,
    )
    .join(
      "",
    )}</div><p class="helper" style="margin-top:16px">所有修正值读取服务端人物卡。场景需要检定时，请通过对应行动或 DM 提案执行。</p></section></div>`;
}
function spellInfo(id) {
  return (
    characterData().spell_details?.find((spell) => spell.id === id) ||
    sheetCatalog.spells.find((spell) => spell.id === id) || { id, name: id }
  );
}
function belongsToClass(spell, classId) {
  return (spell.classes || spell.class_ids || []).some(
    (value) =>
      (typeof value === "string" ? value : value.index || value.id) === classId,
  );
}
function spellLabel(spell) {
  return spell.display_name || spell.name_zh || spell.name || spell.id;
}
function spellDescription(spell) {
  const value = spell.description || spell.desc || "";
  return Array.isArray(value) ? value.join("\n") : value;
}
function slotHtml(character) {
  const slots = Object.entries(character.spell_slots || {});
  return `<div class="sheet-resources">${slots.map(([level, value]) => `<div class="sheet-resource">${level} 环法术位<strong>${value.current} / ${value.max}</strong><small>长休恢复</small></div>`).join("")}${character.pact_slots?.max ? `<div class="sheet-resource">契约法术位 · ${character.pact_slots.level} 环<strong>${character.pact_slots.current} / ${character.pact_slots.max}</strong><small>短休恢复</small></div>` : ""}</div>`;
}
function sheetSpellsHtml(character) {
  if (!sheetCatalog.loaded)
    return '<p class="helper" role="status">正在读取法术目录…</p>';
  const known = new Set([
    ...(character.cantrips || []),
    ...(character.known_spells || []),
    ...(character.prepared_spells || []),
    ...(character.spellbook || []),
    ...(character.ritual_spells || []),
    ...(character.always_prepared_spells || []),
    ...Object.values(character.arcanum || {}),
  ]);
  const casting = character.spellcasting || {};
  return `<section class="sheet-section"><div class="row between"><h3>施法能力</h3>${sheetState.owner && casting.prepared_limit > 0 ? '<button class="small" id="manage-spells">调整准备法术</button>' : ""}</div><p>${casting.ability ? `${abilities[casting.ability] || casting.ability} · 法术豁免 DC ${casting.save_dc ?? "—"} · 法术攻击 ${casting.attack_bonus != null ? signed(casting.attack_bonus) : "—"}` : "此职业当前没有施法能力。"}</p><p class="helper" style="margin:12px 0">目录收录不等于自动结算。只有规则引擎支持且当前合法的法术可以施放；其他法术显示规则参考。</p>${slotHtml(character)}</section><div class="spell-list">${
    [...known]
      .map((id) => {
        const spell = spellInfo(id),
          action = ownedActions().find((a) => a.id === `cast:${id}`),
          reason = action
            ? actionDisabledReason(action)
            : "当前没有可执行的施放动作";
        return `<article class="spell-card"><div class="spell-label">${spell.level === 0 || character.cantrips?.includes(id) ? "戏法" : `${spell.level ?? "—"} 环`} · ${character.prepared_spells?.includes(id) ? "已准备" : character.known_spells?.includes(id) ? "已知" : character.cantrips?.includes(id) ? "已掌握" : character.spellbook?.includes(id) ? "法术书" : "仪式"}</div><h4>${esc(spellLabel(spell) || id)}</h4><p>${esc(spellDescription(spell) || "该法术已列入人物记录。")}</p><p>${spell.concentration ? "需要专注 · " : ""}${esc(spell.casting_time || "")}${spell.range ? ` · ${esc(spell.range)}` : ""}</p>${action && sheetState.owner ? `<button data-sheet-cast="${esc(id)}" ${reason ? "disabled" : ""} title="${esc(reason)}">${reason ? esc(reason) : "选择法术位与目标 ↗"}</button>` : '<p style="margin-top:9px">规则参考 · 此刻不可自动施放</p>'}</article>`;
      })
      .join("") ||
    '<p class="helper">此角色尚未掌握法术。升级或法术管理中可选择当前等级允许的法术。</p>'
  }</div>`;
}
function itemName(item) {
  return typeof item === "string"
    ? item
    : item?.name || item?.label || item?.id || "物品";
}
function sheetEquipmentHtml(character) {
  const equipment = character.equipment || character.inventory || [];
  const entries = Array.isArray(equipment)
    ? equipment
    : Object.entries(equipment).map(([id, value]) =>
        typeof value === "object"
          ? { id, ...value }
          : { name: id, quantity: value },
      );
  return `<div class="sheet-columns"><section class="sheet-section"><h3>当前装备</h3><div class="sheet-list"><div class="sheet-list-row"><span>武器</span><strong>${esc(itemName(character.weapon))}</strong></div>${character.weapon ? `<div class="sheet-list-row"><span>武器伤害</span><span>${esc(character.weapon.dice || character.weapon.damage || "—")} · ${esc(abilities[character.weapon.ability] || character.weapon.ability || "")}</span></div>` : ""}<div class="sheet-list-row"><span>护甲</span><span>${esc(itemName(character.armor) || "—")}</span></div><div class="sheet-list-row"><span>治疗药水</span><span>${character.potions ?? "—"}</span></div></div></section><section class="sheet-section"><h3>随身物品</h3><div class="sheet-list">${entries.map((item) => `<div class="sheet-list-row"><span>${esc(itemName(item))}</span><span>${esc(item.quantity ?? item.count ?? 1)}</span></div>`).join("") || '<p class="helper">暂无额外物品记录。</p>'}</div></section></div><section class="sheet-section"><h3>剧情赋予的能力</h3>${(sheetState.equipped_custom_skill_ids || character.equipped_custom_skill_ids || []).map((id) => `<div class="sheet-list-row"><span>${esc(id)}</span><span>剧情能力</span></div>`).join("") || '<p class="helper">剧情能力由当前冒险允许的卡片决定。</p>'}${sheetState.owner ? '<button id="equip-skills" class="small" style="margin-top:14px">选择剧情能力卡</button>' : ""}</section><p class="helper">装备数据来自角色记录。当前页面不提供未实现的自由数值编辑。</p>`;
}
function renderCharacterSheet() {
  if (!sheetState?.overlay?.isConnected || sheetState.loading) return;
  const character = characterData(),
    container = $("#character-sheet", sheetState.overlay);
  $("#dialog-title", sheetState.overlay).textContent =
    `${character.name || room.party.find((p) => p.id === sheetState.memberId)?.name || "冒险者"} · 完整人物卡`;
  container.innerHTML = `<div class="character-sheet-top"><div class="avatar">${esc((character.name || "旅")[0])}</div><div><div class="eyebrow">CHARACTER DOSSIER / ${sheetState.owner ? "你的角色" : "队友档案 · 只读"}</div><h2 style="margin-top:8px">${esc(classLabel(character))} · Lv.${character.level || 1}</h2><p class="sheet-live-hp">HP ${character.hp} / ${character.max_hp} · AC ${character.ac}</p></div></div><nav class="sheet-tabs" aria-label="人物卡分类">${Object.entries(
    {
      overview: "属性与特性",
      skills: "技能与豁免",
      spells: "法术与法术位",
      equipment: "装备与能力",
      growth: "成长与休息",
    },
  )
    .map(
      ([id, label]) =>
        `<button data-sheet-tab="${id}" class="${sheetTab === id ? "active" : ""}">${label}</button>`,
    )
    .join(
      "",
    )}</nav><div id="sheet-body">${sheetTab === "overview" ? sheetOverviewHtml(character) : sheetTab === "skills" ? sheetSkillsHtml(character) : sheetTab === "spells" ? sheetSpellsHtml(character) : sheetTab === "equipment" ? sheetEquipmentHtml(character) : sheetGrowthHtml(character)}</div>`;
  container.querySelectorAll("[data-sheet-tab]").forEach(
    (button) =>
      (button.onclick = async () => {
        sheetTab = button.dataset.sheetTab;
        renderCharacterSheet();
        if (
          (sheetTab === "spells" || sheetTab === "growth") &&
          !sheetCatalog.loaded
        ) {
          try {
            await ensureSheetCatalog();
            renderCharacterSheet();
          } catch (error) {
            const body = $("#sheet-body");
            if (body)
              body.insertAdjacentHTML(
                "afterbegin",
                `<p class="error">法术目录读取失败：${esc(error.message)}</p>`,
              );
          }
        }
      }),
  );
  container.querySelectorAll("[data-sheet-cast]").forEach(
    (button) =>
      (button.onclick = () => {
        const action = ownedActions().find(
          (a) => a.id === `cast:${button.dataset.sheetCast}`,
        );
        if (action) {
          sheetState.close();
          castActionDialog(action);
        }
      }),
  );
  $("#manage-spells", container)?.addEventListener(
    "click",
    spellManagementDialog,
  );
  $("#equip-skills", container)?.addEventListener("click", equipSkillsDialog);
  $("#rest-short", container)?.addEventListener("click", () =>
    restDialog("short"),
  );
  $("#rest-long", container)?.addEventListener("click", () =>
    restDialog("long"),
  );
  $("#level-up-form", container)?.addEventListener("submit", confirmLevelUp);
}
function sheetGrowthHtml(character) {
  const preview = sheetState.advancement || {},
    target = preview.target_level || Math.min(20, (character.level || 1) + 1),
    choices = preview.required_choices || {};
  const canLevel =
    sheetState.owner && preview.can_level_up && !room.combat?.active && !busy && connected && !sheetState.loading && !sheetState.mutationPending;
  const blockers = preview.reasons || preview.errors || [];
  return `<section class="sheet-section"><h3>休息与恢复</h3><p>个人短休推进游戏时间 1 小时，按投入的生命骰恢复资源；全队长休由房主发起，耗时 8 小时，24 小时内不能重复。战斗中不能休息。</p><div class="row wrap" style="margin-top:14px"><button id="rest-short" class="small" ${!sheetState.owner || room.combat?.active || busy ? "disabled" : ""}>短休 · 选择生命骰</button><button id="rest-long" class="small" ${!sheetState.owner || room.host_id !== session.member_id || room.combat?.active || busy ? "disabled" : ""} title="由房主发起全队长休">全队长休 · 房主</button></div></section><section class="growth-preview"><div class="eyebrow">YOUR NEXT CHAPTER</div><h3>${character.level >= 20 ? "已达 20 级" : "Lv." + character.level + " → Lv." + target}</h3><p>当前 ${character.xp ?? 0} XP · 下一级需要 ${preview.xp_required ?? "—"} XP</p>${preview.hp_gain_before_asi != null ? `<p>最大生命基础增加 ${preview.hp_gain_before_asi}</p>` : ""}${(preview.features || preview.new_features || []).length ? `<p>本级特性：${(preview.features || preview.new_features).map((f) => esc(typeof f === "string" ? f : f.name || f.id)).join("、")}</p>` : ""}${!preview.can_level_up ? `<p class="error" style="margin-top:12px">${esc(preview.reason || blockers.join("；") || (character.level >= 20 ? "已达到当前等级上限。" : "当前尚未满足升级条件。"))}</p>` : ""}${!sheetState.owner ? '<p class="helper" style="margin-top:12px">只有角色所属玩家可以确认升级；房主不能代替他人选择。</p>' : ""}<form id="level-up-form"><div class="growth-choices">${growthChoiceHtml(character, choices, preview)}</div><p data-sheet-connection role="status" class="helper">${connected?'':'正在连接冒险桌，恢复连接后可确认成长。'}</p><p id="growth-error" class="error" role="alert"></p><button class="primary" type="submit" ${canLevel ? "" : "disabled"}>确认选择并升至 ${target} 级 ↗</button></form></section>`;
}
function optionId(item) {
  return typeof item === "string" ? item : item.id;
}
function optionLabel(item) {
  return typeof item === "string"
    ? skillNames[item] || spellLabel(spellInfo(item)) || item
    : item.display_name || item.name_zh || item.name || item.label || item.id;
}
function checkChoice(name, label, options, selected = [], maxHint = "") {
  return `<div><p class="helper" style="margin-bottom:9px">${label}${maxHint ? ` · ${maxHint}` : ""}</p><div class="growth-checklist">${
    options
      .map((item) => {
        const id = optionId(item);
        return `<label><input type="checkbox" name="${name}" value="${esc(id)}" ${selected.includes(id) ? "checked" : ""}>${esc(optionLabel(item))}${typeof item === "object" && item.level != null ? ` · ${item.level === 0 ? "戏法" : item.level + "环"}` : ""}</label>`;
      })
      .join("") || '<p class="helper">没有可选项目，或目录仍在载入。</p>'
  }</div></div>`;
}
function growthChoiceHtml(character, choices, preview) {
  let html = "";
  const subclasses = choices.subclass || choices.subclasses || [];
  if (subclasses.length)
    html += `<label>选择子职业<select name="subclass_id" required><option value="">请选择</option>${subclasses.map((item) => `<option value="${esc(optionId(item))}">${esc(optionLabel(item))}</option>`).join("")}</select></label>`;
  if (choices.asi)
    html += `<div><p class="helper" style="margin-bottom:10px">属性提升 · 分配 ${choices.asi.points || 2} 点，单项不超过 ${choices.asi.max || 20}</p><div class="field-grid">${Object.entries(
      abilities,
    )
      .map(
        ([id, label]) =>
          `<label>${label} (${character.abilities?.[id] ?? "—"})<input type="number" name="asi_${id}" value="0" min="0" max="${Math.max(0, Math.min(choices.asi.points || 2, (choices.asi.max || 20) - (character.abilities?.[id] || 10)))}"></label>`,
      )
      .join("")}</div></div>`;
  const eligible = (
    preview.eligible_spells ||
    sheetCatalog.spells.filter((spell) =>
      belongsToClass(spell, character.class_id),
    )
  ).map((item) => (typeof item === "string" ? spellInfo(item) : item));
  const cantrips = (preview.eligible_cantrips || []).map((item) =>
    typeof item === "string" ? spellInfo(item) : item,
  );
  const secrets = (preview.eligible_magical_secrets || []).map(spellInfo);
  if (choices.magical_secrets_count)
    html += checkChoice(
      "magical_secrets",
      "魔法奥秘（同时勾选到已知法术）",
      secrets,
      character.magical_secrets || [],
      `目标数量 ${choices.magical_secrets_count}`,
    );
  for (const [level, ids] of Object.entries(
    choices.arcanum_choices || preview.arcanum_choices || {},
  ))
    html += `<label>${level} 环秘法<select name="arcanum_${level}" required><option value="">请选择</option>${ids.map((id) => `<option value="${esc(id)}">${esc(spellLabel(spellInfo(id)))}</option>`).join("")}</select></label>`;
  if (choices.bonus_skills_count)
    html += checkChoice(
      "bonus_skills",
      "额外熟练技能",
      Object.keys(skillNames)
        .filter((id) => !(character.skills || []).includes(id))
        .map((id) => ({ id, name: skillNames[id] })),
      [],
      `选择 ${choices.bonus_skills_count} 项`,
    );
  if (choices.known_spells_count > 0)
    html += checkChoice(
      "known_spells",
      "已知法术",
      [...new Map([...eligible, ...secrets].map((s) => [s.id, s])).values()],
      character.known_spells || [],
      `目标数量 ${choices.known_spells_count}`,
    );
  if (choices.prepared_spells_limit > 0)
    html += checkChoice(
      "prepared_spells",
      "准备法术",
      eligible.filter((spell) => typeof spell === "string" || spell.level > 0),
      character.prepared_spells || [],
      `最多 ${choices.prepared_spells_limit}`,
    );
  if (choices.cantrips_count > 0)
    html += checkChoice(
      "cantrips",
      "戏法",
      cantrips,
      character.cantrips || [],
      `目标数量 ${choices.cantrips_count}`,
    );
  if (choices.spellbook_count > 0)
    html += checkChoice(
      "spellbook",
      "法术书",
      eligible,
      character.spellbook || [],
      `目标数量 ${choices.spellbook_count}，保留已有法术`,
    );
  if (choices.expertise_count)
    html += checkChoice(
      "expertise",
      "选择专精技能",
      (character.skills || []).map((id) => ({
        id,
        name: skillNames[id] || id,
      })),
      character.expertise || [],
      `数量 ${choices.expertise_count}`,
    );
  return (
    html ||
    '<p class="helper">此等级没有额外必选项。确认后将由服务端应用成长。</p>'
  );
}
async function confirmLevelUp(event) {
  event.preventDefault();
  if (!sheetState?.owner || busy || !connected || sheetState.loading || sheetState.mutationPending) return;
  const mutationSheet = sheetState;
  const form = event.currentTarget,
    values = new FormData(form),
    choices = {},
    required = sheetState.advancement?.required_choices || {};
  if (values.get("subclass_id"))
    choices.subclass_id = values.get("subclass_id");
  if (required.asi) {
    choices.asi = Object.fromEntries(
      Object.keys(abilities)
        .map((id) => [id, Number(values.get(`asi_${id}`) || 0)])
        .filter(([, value]) => value),
    );
    const count = Object.values(choices.asi).reduce((a, b) => a + b, 0);
    if (count !== (required.asi.points || 2)) {
      $("#growth-error", form).textContent =
        `请恰好分配 ${required.asi.points || 2} 点属性。`;
      return;
    }
  }
  for (const name of [
    "known_spells",
    "prepared_spells",
    "cantrips",
    "spellbook",
    "expertise",
    "magical_secrets",
    "bonus_skills",
  ])
    if (form.querySelector(`[name=${name}]`))
      choices[name] = values.getAll(name);
  const arcanumFields = [...form.querySelectorAll("[name^=arcanum_]")];
  if (arcanumFields.length)
    choices.arcanum = {
      ...(characterData().arcanum || {}),
      ...Object.fromEntries(
        arcanumFields.map((field) => [field.name.slice(8), field.value]),
      ),
    };
  const button = $("[type=submit]", form);
  button.disabled = true;
  mutationSheet.mutationPending=true;
  try {
    if (await command(room.status === "lobby" ? "prepare_level_up" : "level_up", { choices })) {
      toast("角色已升级，成长记录已保存。");
      if (sheetState?.overlay === mutationSheet.overlay && activeTextScope === mutationSheet.scope)
        await reloadCharacterSheet();
    } else if(form.isConnected) {
      $('#growth-error',form).textContent='升级未完成，请检查规则或连接状态后重试。';
    }
  } finally {
    mutationSheet.mutationPending=false;
    if (sheetState?.overlay === mutationSheet.overlay && activeTextScope === mutationSheet.scope) {
      sheetState.mutationPending=false;
      refreshSheetVitals();
    }
  }
}
async function spellManagementDialog() {
  const character = characterData(),
    casting = character.spellcasting || {};
  const classSpells = sheetCatalog.spells.filter(
    (spell) =>
      belongsToClass(spell, character.class_id) &&
      spell.level <= (casting.max_spell_level || 0) &&
      !(character.always_prepared_spells || []).includes(spell.id),
  );
  const preparedOptions =
    character.class_id === "wizard"
      ? classSpells.filter((spell) =>
          (character.spellbook || []).includes(spell.id),
        )
      : classSpells;
  openDialog(
    `<div class="row between"><h2 id="dialog-title">管理法术</h2><button data-close class="ghost">×</button></div><form id="spell-manage-form" class="form"><p class="helper">当前房规允许在战斗外调整准备法术，无需等待长休。已知法术、戏法和法术书只能在建角或升级时选择，不能免费重新学习。</p>${
      casting.prepared_limit != null
        ? checkChoice(
            "prepared_spells",
            "准备法术",
            preparedOptions.filter((spell) => spell.level > 0),
            character.prepared_spells || [],
            `上限 ${casting.prepared_limit}`,
          )
        : ""
    }<p id="spell-manage-error" class="error" role="alert"></p><button class="primary" ${room.combat?.active ? "disabled" : ""}>保存法术选择</button>${room.combat?.active ? '<p class="helper">战斗中不能更换法术。</p>' : ""}</form>`,
    (overlay, close) => {
      $("#spell-manage-form", overlay).onsubmit = async (event) => {
        event.preventDefault();
        const form = event.currentTarget,
          values = new FormData(form),
          payload = {};
        payload.prepared_spells = values.getAll("prepared_spells");
        const button = $("button.primary", form);
        button.disabled = true;
        if (await command("manage_spells", payload)) {
          close();
          await reloadCharacterSheet();
          toast("法术选择已保存。");
        } else {
          button.disabled = false;
          $("#spell-manage-error", form).textContent =
            "保存未完成，请检查数量、等级与规则限制。";
        }
      };
    },
  );
}
function restDialog(kind) {
  const character = characterData();
  openDialog(
    `<div class="row between"><h2 id="dialog-title">${kind === "short" ? "短休" : "长休"}</h2><button class="ghost" data-close>×</button></div><form id="rest-form" class="form"><p class="helper">${kind === "short" ? "投入生命骰恢复生命，并恢复短休职业资源。可以投入 0 枚，只恢复资源。" : "由房主为全队发起 8 小时长休。未死亡成员恢复生命、法术位与资源；24 小时内不能重复长休。"}</p>${kind === "short" ? `<label>使用生命骰（剩余 ${character.hit_dice?.current ?? 0} 枚）<input name="hit_dice" type="number" min="0" max="${character.hit_dice?.current ?? 0}" value="0" required></label>` : ""}<p id="rest-error" class="error" role="alert"></p><button class="primary">确认${kind === "short" ? "短休" : "长休"}</button></form>`,
    (overlay, close) => {
      $("#rest-form", overlay).onsubmit = async (event) => {
        event.preventDefault();
        const form = event.currentTarget,
          button = $("button.primary", form);
        button.disabled = true;
        const hitDice = Number($("[name=hit_dice]", form)?.value || 0);
        if (await command("rest", { kind, hit_dice: hitDice })) {
          close();
          await reloadCharacterSheet();
          toast("休息已完成，资源状态已同步。");
        } else {
          button.disabled = false;
          $("#rest-error", form).textContent = "当前无法休息，请查看操作提示。";
        }
      };
    },
  );
}
async function equipSkillsDialog() {
  const character = characterData();
  const skills =
    sheetState.available_custom_skills ||
    character.available_custom_skills ||
    [];
  openDialog(
    `<div class="row between"><h2 id="dialog-title">选择剧情能力卡</h2><button class="ghost" data-close>×</button></div><form class="form" id="equip-skills-form"><p class="helper">最多装备 4 张当前冒险包允许的能力卡。它们独立于职业技能与法术，不能修改卡片数值。</p>${checkChoice("skill_ids", "剧情能力", skills, sheetState.equipped_custom_skill_ids || character.equipped_custom_skill_ids || [])}<p id="equip-error" class="error"></p><button class="primary" ${room.combat?.active ? "disabled" : ""}>保存个人能力</button></form>`,
    (overlay, close) => {
      $("#equip-skills-form", overlay).onsubmit = async (event) => {
        event.preventDefault();
        const form = event.currentTarget;
        const button = $("button.primary", form);
        button.disabled = true;
        const chosen = new FormData(form).getAll("skill_ids");
        if (chosen.length > 4) {
          button.disabled = false;
          $("#equip-error", form).textContent = "最多选择 4 张剧情能力卡。";
          return;
        }
        if (await command("equip_skills", { skill_ids: chosen })) {
          close();
          await reloadCharacterSheet();
        } else {
          button.disabled = false;
          $("#equip-error", form).textContent =
            "保存失败，请选择当前剧情允许的技能。";
        }
      };
    },
  );
}

let actionEntry = "skills",
  freeActionDraft = "",
  skillIntentId = "",
  freeActionPending = false;
const failedProposals = new Set();
function installActionEntries() {
  if (room.status === "lobby" || room.status === "finished") return;
  const skillArea = $(".combat-actions") || $(".composer .actions");
  if (!skillArea) return;
  skillArea.insertAdjacentHTML(
    "beforebegin",
    `<nav class="action-entry-tabs" aria-label="行动方式"><button data-action-entry="skills" aria-pressed="${actionEntry === "skills"}">⚔ 技能行动<small>职业、法术与规则动作</small></button><button data-action-entry="free" aria-pressed="${actionEntry === "free"}">✦ 自由行动<small>描述意图，先裁定后执行${(room.director_proposals || []).length ? ` · ${(room.director_proposals || []).length} 项待处理` : ""}</small></button></nav>`,
  );
  const standardSkills = catalog.standard_skills || [];
  if (standardSkills.length) skillArea.insertAdjacentHTML("beforeend", `<details class="standard-skills"><summary>18 项标准技能 · 选择尝试方法</summary><p class="helper">选择技能后描述目标；DM 决定是否检定及后果。</p><div class="actions">${standardSkills.map(skill => `<button type="button" data-method-skill="${esc(skill.id)}">${esc(skill.name)} · ${esc(abilities[skill.ability] || skill.ability)}</button>`).join("")}</div></details>`);
  skillArea.classList.toggle("action-entry-hidden", actionEntry !== "skills");
  skillArea.insertAdjacentHTML(
    "afterend",
    `<section class="free-action-panel ${actionEntry === "free" ? "" : "action-entry-hidden"}"><div class="eyebrow">INTENT → RULING → CONFIRM</div><h3>你想如何改变眼前的局面？</h3><p class="helper">自由描述不等于免费行动。DM 将给出目标、检定、风险与资源代价；确认后由系统结算。</p>${freeActionContextHtml()}<form id="free-action-form"><label>希望采用的方法<select id="intent-skill"><option value="">由 DM 判断</option>${standardSkills.map(skill => `<option value="${esc(skill.id)}" ${skillIntentId === skill.id ? "selected" : ""}>${esc(skill.name)}</option>`).join("")}</select></label><label class="sr-only" for="free-action-intent">描述你的自由行动</label><textarea id="free-action-intent" maxlength="1500" required placeholder="例如：推倒木箱挡住敌人，借掩体接近门口…">${esc(freeActionDraft)}</textarea><div class="row between"><small>${room.combat?.active ? "战斗中仍受回合、动作与移动资源限制。" : "探索行动也可能消耗时间、资源或触发风险。"}</small><button class="primary" ${busy || !connected || room.status !== "playing" ? "disabled" : ""}>${freeActionPending ? "正在裁定…" : "请求裁定 ↗"}</button></div><p class="free-action-status" role="status">${freeActionPending ? "DM 正在把你的意图转换为可审核的规则计划；尚未执行行动。" : ""}</p></form><div id="free-action-proposals"></div></section>`,
  );
  app.querySelectorAll("[data-action-entry]").forEach(
    (button) =>
      (button.onclick = () => {
        actionEntry = button.dataset.actionEntry;
        renderRoom();
        if (actionEntry === "free") $("#free-action-intent")?.focus();
      }),
  );
  app.querySelectorAll("[data-free-object]").forEach(
    (button) =>
      (button.onclick = () => {
        const obj = (room.free_actions?.objects || []).find(
          (item) => item.id === button.dataset.freeObject,
        );
        freeActionDraft =
          (freeActionDraft ? freeActionDraft + " " : "") + (obj?.name || "");
        $("#free-action-intent").value = freeActionDraft;
        $("#free-action-intent").focus();
      }),
  );
  $("#intent-skill").onchange = event => (skillIntentId = event.target.value);
  app.querySelectorAll('[data-method-skill]').forEach(button => button.onclick = () => {
    skillIntentId = button.dataset.methodSkill;
    actionEntry = 'free';
    renderRoom();
    $('#free-action-intent')?.focus();
  });
  $("#free-action-intent").oninput = (event) =>
    (freeActionDraft = event.target.value);
  $("#free-action-form").onsubmit = async (event) => {
    event.preventDefault();
    const text = $("#free-action-intent").value.trim();
    if (!text || busy) return;
    freeActionDraft = text;
    freeActionPending = true;
    await command("director_propose", { text, ...(skillIntentId ? { skill_id: skillIntentId } : {}) });
    freeActionPending = false;
    renderRoom();
  };
}
function humanPlanValue(value) {
  if (value == null) return "未指定";
  if (Array.isArray(value)) return value.map(humanPlanValue).join("、") || "无";
  if (typeof value === "object")
    return Object.entries(value)
      .map(
        ([key, item]) =>
          `${{ action: "动作", bonus: "附赠动作", movement: "移动", reaction: "反应", minutes: "分钟", amount: "数量", type: "类型", target_id: "目标", dc: "DC", ability: "属性", skill: "技能", skill_id: "技能", damage: "伤害", condition: "状态", duration: "持续时间", dice: "骰式", on: "触发时机" }[key] || key}：${humanPlanValue(item)}`,
      )
      .join("；");
  return (
    {
      true: "需要",
      false: "不消耗",
      self: "自己",
      enemy: "敌人",
      ally: "队友",
      success: "成功时",
      failure: "失败时",
      always: "始终",
    }[String(value)] || String(value)
  );
}
function freeActionContextHtml() {
  const context = room.free_actions || {},
    tags = {
      movable: "可移动",
      cover: "可作掩护",
      flammable: "可燃",
      interactable: "可操作",
      searchable: "可搜索",
      sand: "沙土",
      fire: "火源",
    };
  return `<details class="free-context" open><summary>眼前可以互动的场景物件 · ${(context.objects || []).length}</summary><div class="free-object-grid">${(context.objects || []).map((obj) => `<button type="button" class="free-object" data-free-object="${esc(obj.id)}"><strong>${esc(obj.name)}</strong><small>${esc(obj.description || "")}</small><span>${(obj.tags || []).map((tag) => esc(tags[tag] || tag)).join(" · ")}</span><small>${obj.hp != null ? `耐久 ${esc(obj.hp)}` : ""}${obj.burning ? " · 燃烧中" : ""}${obj.collapsed ? " · 已倒塌" : ""}${obj.searched ? " · 已搜索" : ""}${obj.state ? ` · ${esc(humanPlanValue(obj.state))}` : ""}</small></button>`).join("") || '<p class="helper">此场景尚未登记可操作物件。可以描述针对角色的行动；不会凭空创建道具或奖励。</p>'}</div></details><details class="free-context"><summary>当前规则支持的自由行动</summary><div class="free-recipes">${(context.recipes || []).map((recipe) => `<div><strong>${esc(recipe.label)}</strong><small>${esc(recipe.cost_label || humanPlanValue(recipe.cost))}</small><p>${esc((recipe.summary || []).join(" "))}</p>${recipe.disabled_reason ? `<p class="action-unavailable">${esc(recipe.disabled_reason)}</p>` : ""}${recipe.targets?.length ? `<small>可选目标：${recipe.targets.map((t) => esc(t.name)).join("、")}</small>` : ""}${recipe.objects?.length ? `<small>可用物件：${recipe.objects.map((t) => esc(t.name)).join("、")}</small>` : ""}</div>`).join("") || '<p class="helper">规则上下文正在同步。</p>'}</div></details>`;
}
function proposalDetails(proposal) {
  const plan = proposal.plan;
  const method = (catalog.standard_skills || []).find(skill => skill.id === proposal.action_intent?.preferred_skill_id);
  const declaration = method ? `<p class="helper">方法意向：${esc(method.name)}；是否检定以本次裁定为准。</p>` : "";
  if (!plan)
    return `${declaration}${proposal.kind === "check" ? `<p><strong>${esc(proposal.skill_name || "检定")} · DC ${esc(proposal.dc)}</strong></p><p>成功：${esc(proposal.success_text || "按照提案推进")}</p><p>失败：${esc(proposal.failure_text || "按照提案承受后果")}</p>` : ""}${proposal.cost ? `<p>代价：${esc(humanPlanValue(proposal.cost))}</p>` : ""}`;
  const target =
    (plan.targets || []).find((item) => item.id === plan.target_id) ||
    room.party.find((item) => item.id === plan.target_id) ||
    (room.combat?.enemies || []).find((item) => item.id === plan.target_id);
  const object =
    (plan.objects || []).find((item) => item.id === plan.object_id) ||
    (room.free_actions?.objects || []).find(
      (item) => item.id === plan.object_id,
    );
  const targetNames = (plan.targets?.length ? plan.targets.map(item => item.name) : [target?.name]).filter(Boolean);
  return `${declaration}<dl class="proposal-facts"><div class="proposal-fact"><dt>资源代价</dt><dd>${esc(plan.cost_label || humanPlanValue(plan.cost || proposal.cost))}</dd></div><div class="proposal-fact"><dt>执行目标</dt><dd>${esc([...targetNames, object?.name].filter(Boolean).join(" · ") || "自己 / 当前环境")}</dd></div></dl><p><strong>检定与规则效果</strong></p><ul class="proposal-effects">${(plan.summary || []).map((text) => `<li>${esc(text)}</li>`).join("") || `<li>${esc(humanPlanValue(plan.check || plan.effects || "按规则计划执行"))}</li>`}</ul><p class="proposal-warning">${esc(proposal.risk || plan.risk || proposal.failure_text || "需要检定的行动可能失败。失败不会退还已使用的动作或移动；不会保证造成效果。")}</p>`;
}
function installDmProposals() {
  installActionEntries();
  const raw = room.director_proposals || [],
    proposals = Array.isArray(raw) ? raw : Object.values(raw);
  const pending = proposals.filter((p) => !p.resolved);
  if (!pending.length) return;
  const destination = $("#free-action-proposals") || $(".composer");
  if (!destination) return;
  destination.insertAdjacentHTML(
    "beforeend",
    `<section class="dm-proposals">${pending
      .map((proposal) => {
        const stale =
          failedProposals.has(proposal.id) ||
          proposal.stale ||
          proposal.status === "expired" ||
          proposal.status === "invalid";
        return `<article class="dm-proposal" data-proposal-id="${esc(proposal.id)}"><div class="eyebrow">${proposal.source === "llm" ? "AI DM" : "规则导演"} / ${stale ? "需要重新裁定" : "待确认提案"}</div><h3>${esc(proposal.label || "你的行动意图")}</h3><p>${esc(proposal.text || "")}</p>${proposalDetails(proposal)}${stale ? `<p class="proposal-warning" role="alert">${proposal.stale_reason === "challenge_unavailable" ? "这项挑战目前不能按原计划执行。请检查已有结果或目标事实；换一种说法不会重掷。" : "提案未执行或场景已变化。请核对当前状态，重新请求裁定。"}</p>` : ""}<div class="proposal-buttons"><button class="primary" data-director-resolve="${esc(proposal.id)}" ${stale || busy || !connected || room.status !== "playing" || (proposal.requires_host && room.host_id !== session.member_id) ? "disabled" : ""}>${proposal.kind === "encounter" ? "确认进入遭遇战" : "确认代价并执行"} ↗</button><button data-director-cancel="${esc(proposal.id)}" ${busy ? "disabled" : ""}>取消提案</button>${stale ? `<button data-director-revise="${esc(proposal.id)}">修改并重新裁定</button>` : ""}</div><p class="helper">${proposal.requires_host && room.host_id !== session.member_id ? "需要房主确认" : "确认前不会掷骰或消耗行动资源；世界变化后可能需要重新裁定。"}</p></article>`;
      })
      .join("")}</section>`,
  );
  app.querySelectorAll("[data-director-resolve]").forEach(
    (button) =>
      (button.onclick = async () => {
        const id = button.dataset.directorResolve;
        if (!(await command("director_resolve", { proposal_id: id }))) {
          failedProposals.add(id);
          renderRoom();
        }
      }),
  );
  app.querySelectorAll("[data-director-cancel]").forEach(
    (button) =>
      (button.onclick = async () => {
        if (
          await command("director_cancel", {
            proposal_id: button.dataset.directorCancel,
          })
        )
          toast("提案已取消，没有执行或消耗行动。");
      }),
  );
  app.querySelectorAll("[data-director-revise]").forEach(
    (button) =>
      (button.onclick = () => {
        const proposal = pending.find(
          (item) => item.id === button.dataset.directorRevise,
        );
        if (!freeActionDraft)
          freeActionDraft = proposal?.intent || proposal?.text || "";
        skillIntentId = proposal?.action_intent?.preferred_skill_id || "";
        actionEntry = "free";
        renderRoom();
        $("#free-action-intent")?.focus();
      }),
  );
}
async function openCharacterVault() {
  if(!account){location.href='/account.html?next=%2F';return;}
  try{vaultCharacters=(await api('/api/my/characters')).items||[];await ensureSheetCatalog();}catch(error){toast(error.message);return;}
  openDialog(`<div class="row between"><div><div class="eyebrow">YOUR ADVENTURERS</div><h2 id="dialog-title">我的角色</h2></div><button class="ghost" data-close>×</button></div><p class="helper">人物绑定账号。未进入冒险的角色可以重新编辑构筑；已使用的角色保留成长历史。</p><button id="new-character-builder" class="primary" style="margin:20px 0">自定义创建角色 ↗</button><div class="form">${vaultCharacters.map(hero=>`<details class="sheet-feature"><summary>${esc(hero.character.name)} · ${esc(classLabel(hero.character))} Lv.${hero.character.level}</summary><div style="margin-top:16px">${sheetOverviewHtml(hero.character)}<p>${esc(hero.character.profile?.background||'')}</p>${hero.can_rebuild?`<button data-edit-hero="${esc(hero.id)}">编辑人物构筑 ↗</button>`:'<p class="helper">此角色已有冒险历史，不能重新分配属性或职业。</p>'}</div></details>`).join('')||'<p class="helper">还没有角色。从职业、属性与人物设定开始。</p>'}</div>`,(overlay,close)=>{$('.modal',overlay).classList.add('sheet-modal');$('#new-character-builder',overlay).onclick=()=>{close();openCharacterBuilder();};overlay.querySelectorAll('[data-edit-hero]').forEach(button=>button.onclick=()=>{const hero=vaultCharacters.find(item=>item.id===button.dataset.editHero);close();openCharacterBuilder({hero});});});
}

let builderState = null;
function installLobbyBuilder() {
  $('.lobby-build')?.remove();
  if(room.status!=='lobby')return;
  const member=me();if(!member)return;
  const target=room.starting_level||1;
  const welcome=$('.welcome-scene')||$('.journal-heading');
  welcome?.insertAdjacentHTML('beforeend',`<section class="lobby-build"><strong>本桌起始等级 · Lv.${target}</strong><p>${member.build_ready===false?'你的构筑尚未完成。每一级的法术、专精和子职业需由你确认。':'你的角色已满足起始等级。'}${room.party.some(p=>p.build_ready===false)?' 所有玩家准备完毕后才能启程。':''}</p>${member.can_rebuild?'<button id="configure-character" class="primary">定制我的人物 ↗</button>':member.build_ready===false?'<button id="prepare-character" class="primary">补全起始等级选择 ↗</button>':''}</section>`);
  $('#configure-character')?.addEventListener('click',()=>openCharacterBuilder({roomMember:member,targetLevel:target}));
  $('#prepare-character')?.addEventListener('click',async()=>{try{await ensureSheetCatalog();await openCharacterSheet(session.member_id,'growth');}catch(error){toast(error.message);}});
}
function baseCharacterBuild(character={}) {
  return {class_id:character.class_id||'fighter',name:character.name||'',abilities:{str:15,dex:14,con:13,int:12,wis:10,cha:8,...character.abilities},profile:{appearance:'',personality:'',background:'',talents:[],...character.profile},choices:{},levels:[]};
}
async function openCharacterBuilder(options={}) {
  const requestScope=activeTextScope, roomId=session?.room_id;
  try{await ensureSheetCatalog();}catch(error){toast(error.message);return;}
  if(options.roomMember && (activeTextScope!==requestScope || session?.room_id!==roomId))return;
  let character=options.hero?.character||options.roomMember||{};
  if(options.roomMember){try{const detail=await api(`/api/rooms/${roomId}/characters/${options.roomMember.id}`);if(activeTextScope!==requestScope || session?.room_id!==roomId)return;character=detail.character;}catch(error){if(activeTextScope===requestScope)toast(error.message);return;}}
  const build=JSON.parse(JSON.stringify(options.hero?.build||character.build||baseCharacterBuild(character)));
  const actualTarget=options.targetLevel||character.level||1;
  builderState={...options,build,targetLevel:actualTarget,stage:'identity',preview:null,pending:false,error:'',notes:[],editingLevel:null};
  openDialog('<div id="character-builder"></div>',(overlay,close)=>{builderState.overlay=overlay;builderState.close=close;$('.modal',overlay).classList.add('builder-modal');renderCharacterBuilder();});
}
function readBuilderIdentity(form) {
  const data=new FormData(form),s=builderState;
  const classId=data.get('class_id');
  if(s.build.class_id!==classId){s.build.choices={};s.build.levels=[];}
  s.build.class_id=classId;s.build.name=String(data.get('name')||'').trim();
  s.build.abilities=Object.fromEntries(Object.keys(abilities).map(id=>[id,Number(data.get('ability_'+id))]));
  s.build.profile={appearance:data.get('appearance')||'',personality:data.get('personality')||'',background:data.get('background')||'',talents:String(data.get('talents')||'').split('\n').map(item=>item.trim()).filter(Boolean)};
  if(!s.roomMember)s.targetLevel=Number(data.get('target_level')||1);
}
async function previewCharacterBuild() {
  return api('/api/character-builds/preview',{method:'POST',body:JSON.stringify({build:builderState.build,target_level:builderState.targetLevel})});
}
function builderIdentityHtml(s) {
 const p=s.build.profile||{};
 return `<form id="builder-identity" class="form"><div class="field-grid"><label>角色姓名<input name="name" maxlength="32" required value="${esc(s.build.name)}"></label><label>职业<select name="class_id">${sheetCatalog.classes.map(cls=>`<option value="${esc(cls.id)}" ${cls.id===s.build.class_id?'selected':''}>${esc(cls.name)}</option>`).join('')}</select></label><label>套用预设模板<select id="builder-template"><option value="">自定义职业与属性</option>${(catalog.characters||[]).map(c=>`<option value="${esc(c.id)}">${esc(c.name)} · ${esc(c.class_name)}</option>`).join('')}</select></label><label>目标起始等级<input name="target_level" type="number" min="1" max="20" value="${s.targetLevel}" ${s.roomMember?'disabled':''} required></label></div><section class="builder-section"><h3>六项属性</h3><p class="helper">自定义房规：每项 8–20，可自由填写；不是标准购点或随机掷骰。所有修正值由服务器计算。请预留属性成长空间：上限为 20，目前属性提升不能替换为专长；六项全部 20 会导致后续属性提升等级没有合法选择。</p><div class="builder-abilities">${Object.entries(abilities).map(([id,label])=>`<label>${label}<input name="ability_${id}" type="number" min="8" max="20" required value="${s.build.abilities?.[id]??10}"></label>`).join('')}</div></section><div class="field-grid"><label>外貌<textarea name="appearance" maxlength="3000">${esc(p.appearance)}</textarea></label><label>性格<textarea name="personality" maxlength="3000">${esc(p.personality)}</textarea></label></div><label>背景故事<textarea name="background" maxlength="3000">${esc(p.background)}</textarea></label><label>叙事天赋（每行一项）<textarea name="talents" placeholder="例如：能凭星象辨认故乡的方向">${esc((p.talents||[]).join('\n'))}</textarea></label><p class="helper">外貌、背景与叙事天赋不会增加属性、技能熟练、伤害或资源。机械效果必须来自合法职业选项。</p><section class="builder-ai"><label>AI 精细化要求<textarea id="builder-ai-prompt" placeholder="描述你希望保留、修改或补充的细节…"></textarea></label><button type="button" id="builder-ai">生成可审阅草稿 ✦</button><small>只填充草稿，不保存人物，不跳过逐级选择。</small></section><button class="primary" type="submit">审阅 1 级合法选项 →</button></form>`;
}
function builderChoiceHtml(s) {
 const p=s.preview,initial=!p.character||p.next_level===1,c=p.character||{...s.build,skills:s.build.choices.skills||[]},o=initial?p.creation_options:p.advancement;
 const required=initial?o.required_choices:o.required_choices;
 const saved=initial?s.build.choices:(s.build.levels[s.editingLevel-2]?.choices||s.suggestedLevels?.[s.editingLevel-2]?.choices||{});
 return `<form id="builder-choice" class="form"><p class="helper">${initial?'配置一级职业能力。每项均来自合法目录。':`准备从 ${c.level} 级升至 ${p.next_level} 级。逐级确认，不自动跳级。`}</p>${initial?checkChoice('skills','职业熟练技能',o.skills.options,saved.skills||[],`恰好 ${o.skills.count} 项`):''}<div class="growth-choices">${growthChoiceHtml({...c,...saved,skills:saved.skills||(initial?o.skills.options.map(item=>item.id):c.skills)||[]},{...required,subclass:initial?o.subclass:required.subclass},o)}</div><button class="primary" type="submit">验证并确认 ${p.next_level||1} 级选择 →</button></form>`;
}
function renderCharacterBuilder() {
 const s=builderState;if(!s?.overlay?.isConnected)return;
 const root=$('#character-builder',s.overlay),p=s.preview;
 root.innerHTML=`<header class="row between"><div><div class="eyebrow">CHARACTER WORKSHOP / REVIEW EVERY LEVEL</div><h2 id="dialog-title">${s.hero?'编辑人物构筑':s.roomMember?'完成入席构筑':'创造你的旅人'}</h2></div><button class="ghost" id="builder-close" aria-label="关闭建角">×</button></header><nav class="builder-progress" aria-label="建角步骤"><button data-build-stage="identity" aria-current="${s.stage==='identity'?'step':'false'}">人物与属性</button>${Array.from({length:s.targetLevel},(_,i)=>`<button data-build-level="${i+1}" ${!p||i+1>(p.character?.level||0)?'disabled':''} aria-current="${s.stage==='choice'&&p?.next_level===i+1?'step':'false'}">Lv.${i+1}</button>`).join('')}<span>${s.stage==='review'?'最终审阅':'逐级确认'}</span></nav>${s.notes.length?`<div class="builder-notes">${s.notes.map(note=>`<p>${esc(note)}</p>`).join('')}</div>`:''}<p id="builder-error" class="error" role="alert">${esc(s.error)}</p>${s.pending?'<p role="status">正在验证构筑，请稍候…</p>':s.stage==='identity'?builderIdentityHtml(s):s.stage==='choice'?builderChoiceHtml(s):`<section class="builder-review"><div class="eyebrow">READY FOR YOUR REVIEW</div><h3>${esc(p.character.name)} · ${esc(classLabel(p.character))} Lv.${p.character.level}</h3>${sheetOverviewHtml(p.character)}<p>${esc(p.character.profile?.background||s.build.profile.background)}</p><p class="helper">你已逐级确认 ${s.targetLevel} 级构筑。保存后才会写入人物记录；不会为真实冒险授予额外经验。</p><button id="builder-save" class="primary">${s.roomMember?'确认构筑并准备入席':'保存人物构筑'} ↗</button></section>`}`;
 $('#builder-close',root).onclick=()=>s.close();
 $('[data-build-stage]',root).onclick=()=>{s.stage='identity';s.error='';renderCharacterBuilder();};
 root.querySelectorAll('[data-build-level]').forEach(button=>button.onclick=async()=>{const level=Number(button.dataset.buildLevel);s.build.levels=s.build.levels.slice(0,Math.max(0,level-2));if(level===1)s.build.choices={};s.error='';await runBuilderPreview();});
 if(s.pending)return;
 if(s.stage==='choice'){
  const saved=p.next_level===1?s.build.choices:(s.build.levels[p.next_level-2]?.choices||s.suggestedLevels?.[p.next_level-2]?.choices||{});
  if(saved.subclass_id&&$('[name=subclass_id]',root))$('[name=subclass_id]',root).value=saved.subclass_id;
  for(const [id,value] of Object.entries(saved.asi||{}))if($(`[name=asi_${id}]`,root))$(`[name=asi_${id}]`,root).value=value;
  for(const [level,id] of Object.entries(saved.arcanum||{}))if($(`[name=arcanum_${level}]`,root))$(`[name=arcanum_${level}]`,root).value=id;
  if(s.build.class_id==='wizard'){
   const syncPrepared=()=>{const book=[...root.querySelectorAll('[name=spellbook]:checked')].map(box=>box.value);root.querySelectorAll('[name=prepared_spells]').forEach(box=>{box.disabled=!book.includes(box.value);if(box.disabled)box.checked=false;});};
   root.querySelectorAll('[name=spellbook]').forEach(box=>box.addEventListener('change',syncPrepared));syncPrepared();
  }
 }
 $('#builder-identity',root)?.addEventListener('submit',async event=>{event.preventDefault();readBuilderIdentity(event.currentTarget);await startBuilderReview();});
 $('#builder-template',root)?.addEventListener('change',event=>{readBuilderIdentity($('#builder-identity',root));const c=(catalog.characters||[]).find(item=>item.id===event.target.value);if(c){s.build={...baseCharacterBuild(c),name:s.build.name||c.name,profile:s.build.profile};renderCharacterBuilder();}});
 $('#builder-ai',root)?.addEventListener('click',async()=>{readBuilderIdentity($('#builder-identity',root));const prompt=$('#builder-ai-prompt',root).value.trim();if(!prompt){s.error='请填写希望 AI 修改的具体内容。';renderCharacterBuilder();return;}s.pending=true;renderCharacterBuilder();try{const result=await api('/api/character-builds/ai',{method:'POST',body:JSON.stringify({build:s.build,target_level:s.targetLevel,prompt})});s.build=result.build;s.notes=[`来源：${result.source==='llm'?'AI 草稿':'本地草稿'}；请逐项审阅。`,...(result.notes||[])];s.error='';}catch(error){s.error=error.message;}finally{s.pending=false;s.stage='identity';renderCharacterBuilder();}});
 $('#builder-choice',root)?.addEventListener('submit',async event=>{event.preventDefault();const form=event.currentTarget,values=new FormData(form),choices={};for(const key of ['skills','known_spells','prepared_spells','cantrips','spellbook','expertise','magical_secrets','bonus_skills'])if(form.querySelector(`[name=${key}]`))choices[key]=values.getAll(key);if(values.get('subclass_id'))choices.subclass_id=values.get('subclass_id');if(form.querySelector('[name^=asi_]'))choices.asi=Object.fromEntries(Object.keys(abilities).map(id=>[id,Number(values.get('asi_'+id)||0)]));const arcanum=[...form.querySelectorAll('[name^=arcanum_]')];if(arcanum.length)choices.arcanum={...(p.character?.arcanum||{}),...Object.fromEntries(arcanum.map(field=>[field.name.slice(8),field.value]))};const initial=!p.character||p.next_level===1;if(initial)s.build.choices=choices;else {s.build.levels=s.build.levels.slice(0,p.next_level-2);s.build.levels.push({choices});}await runBuilderPreview({rollbackLevel:!initial});});
 $('#builder-save',root)?.addEventListener('click',saveCharacterBuild);
}
async function startBuilderReview() {
 const s=builderState,selected=s.build.choices;s.suggestedLevels=s.build.levels;s.build.levels=[];s.build.choices={};s.pending=true;renderCharacterBuilder();
 try{s.preview=await previewCharacterBuild();s.stage='choice';s.editingLevel=1;s.error='';}catch(error){s.error=error.message;}finally{s.build.choices=selected;s.pending=false;renderCharacterBuilder();}
}
async function runBuilderPreview({rollbackLevel=false}={}) {
 const s=builderState;s.pending=true;renderCharacterBuilder();
 try{s.preview=await previewCharacterBuild();s.error='';s.stage=s.preview.ready?'review':'choice';s.editingLevel=s.preview.next_level;if(s.preview.missing_choices?.length)s.notes=[`需要确认：${s.preview.missing_choices.join('、')}`];else s.notes=[];}
 catch(error){if(rollbackLevel)s.build.levels.pop();s.error=error.message;}
 finally{s.pending=false;renderCharacterBuilder();}
}
async function saveCharacterBuild() {
 const s=builderState;s.pending=true;renderCharacterBuilder();
 try{if(s.roomMember){if(!await command('configure_character',{build:s.build}))throw Error('构筑未保存，请检查规则要求后重试。');}else await api(s.hero?`/api/my/characters/${s.hero.id}`:'/api/my/characters',{method:s.hero?'PATCH':'POST',body:JSON.stringify({...(s.hero?{operation:'rebuild',expected_version:s.hero.version}:{class_id:s.build.class_id,name:s.build.name}),build:s.build,starting_level:s.targetLevel})});s.close();toast('人物构筑已保存。');if(!s.roomMember)await openCharacterVault();}
 catch(error){s.pending=false;s.error=error.message;renderCharacterBuilder();}
}

boot();

function groupScope() {
  return { scene_instance_id: room.scene_instance_id,
    membership_epoch: room.membership_epoch, action_revision: room.action_revision };
}
function groupIdentity() {
  return JSON.stringify([session?.room_id, session?.member_id, room?.scene_instance_id, room?.membership_epoch]);
}
function pendingGroupKey() {
  return `hexbound-group:${session?.room_id}:${session?.member_id}`;
}
function readPendingGroup() {
  try {
    const saved = JSON.parse(sessionStorage.getItem(pendingGroupKey()) || 'null');
    return saved?.plan?.plan_id && saved?.commandId ? saved : null;
  } catch { return null; }
}
function openPartyGroups() {
  if (busy || !connected || room.host_id !== session.member_id) return;
  const identity = groupIdentity(), roomId = session.room_id;
  openDialog(`<div class="row between"><h2 id="dialog-title">分队与合队</h2><button class="ghost" data-close aria-label="关闭">×</button></div><p class="helper">仅在没有战斗或待结算步骤的安全检查点操作。合队还需要同地点、同时间。</p><div id="group-content" class="form"><p role="status">正在读取队伍名单…</p></div>`, async (overlay, close) => {
    overlay.dataset.groupDialog = identity;
    const content = $('#group-content', overlay);
    let groups, plan = null, commandId = null, inFlight = false, unknown = false;
    const pendingKey = pendingGroupKey();
    overlay.addEventListener('click', event => {
      if ((unknown || (inFlight && busy)) && (event.target === overlay || event.target.closest('[data-close]'))) {
        event.preventDefault(); event.stopImmediatePropagation();
      }
    }, true);
    overlay.addEventListener('keydown', event => {
      if ((unknown || (inFlight && busy)) && event.key === 'Escape') {
        event.preventDefault(); event.stopImmediatePropagation();
      }
    }, true);
    const valid = () => overlay.isConnected && groupIdentity() === identity;
    const fail = (message) => {
      const error = $('#group-error', overlay);
      if (error) error.textContent = message;
      else if (overlay.isConnected) content.innerHTML = `<p class="error" role="alert">${esc(message)}</p><button data-close>关闭并重新打开</button>`;
    };
    const showForm = () => {
      if (!valid()) return;
      const others = groups.filter(group => group.id !== room.scene_instance_id);
      content.innerHTML = `<form id="group-form" class="form"><label>操作<select name="operation"><option value="split">组成独立小队</option>${others.length ? '<option value="merge">另一小队与本队会合</option>' : ''}</select></label><div id="group-members"><p class="helper">选择前往新小队的成员，双方至少保留一人。新小队将有独立的文字交流与行动。</p><div class="target-checklist">${room.party.map(member => `<label><input type="checkbox" name="member" value="${esc(member.id)}">${esc(member.name)}${member.id === session.member_id ? '（你）' : ''}</label>`).join('')}</div></div><label id="group-source" hidden>会合的小队<select name="source">${others.map(group => `<option value="${esc(group.id)}">${esc(group.members.map(member => member.name).join('、'))}</option>`).join('')}</select></label><p id="group-error" class="error" role="alert"></p><button type="submit" class="primary">查看操作方案 ↗</button></form>`;
      const form = $('#group-form', overlay);
      form.elements.operation.onchange = () => {
        const split = form.elements.operation.value === 'split';
        $('#group-members', overlay).hidden = !split;
        $('#group-source', overlay).hidden = split;
        $('#group-error', overlay).textContent = '';
      };
      form.onsubmit = async (event) => {
        event.preventDefault();
        if (inFlight || !valid()) return;
        const operation = form.elements.operation.value;
        const members = [...form.querySelectorAll('[name="member"]:checked')].map(input => input.value);
        if (operation === 'split' && (!members.length || members.length >= room.party.length)) {
          fail('请选择部分成员，双方至少保留一人。'); return;
        }
        inFlight = true;
        const button = form.querySelector('[type="submit"]');
        button.disabled = true;
        $('#group-error', overlay).textContent = '';
        try {
          const payload = { operation, expected_scope: groupScope(), ...(operation === 'split' ? {members} : {source:form.elements.source.value, target:room.scene_instance_id}) };
          const prepared = await api(`/api/rooms/${roomId}/groups/prepare`, {method:'POST', body:JSON.stringify(payload)});
          if (!valid()) return;
          plan = prepared; commandId = newCommandId(); showReview();
        } catch (error) { fail(error.message); }
        finally { inFlight = false; if (button.isConnected) button.disabled = false; }
      };
    };
    const showReview = () => {
      if (!valid() || !plan) return;
      const names = new Map(groups.flatMap(group => group.members).map(member => [member.id, member.name]));
      const moved = plan.members.map(id => names.get(id) || '冒险者').join('、');
      const split = plan.operation === 'split';
      content.innerHTML = `<div class="form"><h3>${unknown ? '核对分组结果' : `核对${split ? '分队' : '合队'}方案`}</h3>${unknown ? '<p class="notice" role="status">上次提交尚未收到完整回执，操作可能已经完成。请核对原操作；重试不会重复分组。</p>' : ''}<p>${esc(moved)}${split ? '将组成独立小队，留在当前位置。' : '将与当前小队会合。'}</p><p class="helper">${split ? `新小队由 ${esc(names.get(plan.new_leader_id) || '所选成员')} 担任领队，文字交流和行动独立进行。` : '合队保留每个人的已知范围，不会把另一队的私密记录合并公开。'}待执行提案与在途 DM 回应会取消。状态变化后需要重新准备。</p><p id="group-error" class="error" role="alert"></p><button id="group-confirm" class="primary">${unknown ? '核对并重试原操作' : `确认${split ? '分队' : '合队'}`} ↗</button>${unknown ? '' : '<button id="group-back">返回修改</button><button data-close>取消</button>'}</div>`;
      overlay.querySelector('.row [data-close]').hidden = unknown;
      $('#group-back', overlay)?.addEventListener('click', () => { if (!inFlight && !unknown) { plan = null; commandId = null; showForm(); } });
      $('#group-confirm', overlay).onclick = async () => {
        if (inFlight || !valid() || !plan) return;
        inFlight = true; busy = true;
        const button = $('#group-confirm', overlay);
        button.disabled = true;
        $('#group-error', overlay).textContent = '';
        const body = {plan_id:plan.plan_id, command_id:commandId};
        try {
          try { sessionStorage.setItem(pendingKey, JSON.stringify({plan, commandId})); }
          catch {
            fail('浏览器无法保存重试信息，本次尚未发送，请恢复存储后重试。');
            return;
          }
          let result;
          try {
            result = await api(`/api/rooms/${roomId}/groups/commit`, {method:'POST', body:JSON.stringify(body)});
          } catch (error) {
            if (!(error instanceof TypeError)) throw error;
            result = await api(`/api/rooms/${roomId}/groups/commit`, {method:'POST', body:JSON.stringify(body)});
          }
          if (result.group_change?.group_plan_id !== body.plan_id || result.group_change?.operation !== `scene_${plan.operation}` || result.room?.id !== roomId || !Number.isInteger(result.room?.version)) {
            throw new Error('尚未收到完整操作回执。');
          }
          sessionStorage.removeItem(pendingKey);
          unknown = false;
          if (session?.room_id === roomId && result.room?.version >= room.version) room = result.room;
          close(); toast('队伍分组已更新。');
        } catch (error) {
          if ([409, 422].includes(error.status) && !error.retrySameCommand && !error.responseIncomplete) {
            sessionStorage.removeItem(pendingKey); unknown = false;
            plan = null; commandId = null;
            try {
              const latest = await api(`/api/rooms/${roomId}`);
              if (session?.room_id === roomId && latest.version >= room.version) room = latest;
            } catch {}
            if (valid()) { showForm(); fail(error.message + ' 请重新查看方案。'); }
          } else {
            unknown = true;
            if (valid()) { showReview(); fail(error.message); }
          }
        } finally {
          inFlight = false; busy = false;
          if (button.isConnected) button.disabled = false;
          renderRoom();
        }
      };
    };
    try {
      groups = (await api(`/api/rooms/${roomId}/groups`)).groups;
      const pending = readPendingGroup();
      if (pending) { plan = pending.plan; commandId = pending.commandId; unknown = true; showReview(); }
      else showForm();
    } catch (error) { fail(error.message); }
  });
}

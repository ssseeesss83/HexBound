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
const modeNames = { preset: "预设剧本", free: "自由冒险", hybrid: "混合冒险" };
const interactionNames = {
  guided: "预设引导",
  freeform: "自由创作",
  assisted: "LLM 引导",
};
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
  composeMode = "narrate",
  mobileTab = "story",
  selectedTarget = "",
  toastTimer;
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
  let data;
  try {
    data = await response.json();
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
  }<section class="feature-grid"><div class="feature"><div class="eyebrow">01 / Your story</div><h3>沿着剧本，或走出地图</h3><p>预设、自由与混合模式，为不同的冒险留出空间。</p></div><div class="feature"><div class="eyebrow">02 / True consequence</div><h3>每次掷骰，都有据可查</h3><p>脚本执行检定与战斗。模型讲述结果，不替你决定命运。</p></div><div class="feature"><div class="eyebrow">03 / Together</div><h3>六个席位，一段共同记忆</h3><p>实时同行、自动保存。暂时离席，也不会失去故事。</p></div></section><footer class="footer"><span>HEXBOUND / 六席之间 · 原创文字冒险</span><button class="ghost small" id="rules">查看本版规则范围 ↗</button></footer></main>`;
  $(".home-header").insertAdjacentHTML(
    "beforeend",
    `<a class="small" href="/account.html">${account ? esc(account.display_name) + " · 账号中心" : "登录 / 注册"}</a>`,
  );
  $("#create").onclick = () => entryDialog("create");
  $("#join").onclick = () => entryDialog("join");
  $("#rules").onclick = rulesDialog;
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
  setup?.(overlay, close);
  overlay.querySelector("input,button")?.focus();
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
  let mode = "preset";
  const create = kind === "create";
  const descriptions = {
    preset: "沿原创预设冒险推进，探索、交涉与战斗都有明确规则。",
    free: "需要服务端配置 LLM。生成主题和故事；数值挑战仍受规则模板约束。",
    hybrid: "保留预设冒险主线，让 LLM 丰富场景与角色回应。",
  };
  openDialog(
    `<div class="row between"><div><div class="eyebrow">${create ? "Begin a chapter" : "Take your seat"}</div><h2 id="dialog-title" style="margin-top:8px">${create ? "让冒险从这里开始" : "你的同伴正在等你"}</h2></div><button class="ghost" data-close aria-label="关闭">×</button></div><form class="form" id="entry-form">${create ? '<label>冒险名称<input name="name" maxlength="60" value="雾港来信" required></label>' : '<label>房间邀请码<input name="invite_code" maxlength="32" placeholder="输入同伴发来的邀请码" autocomplete="off" required></label>'}<div class="columns"><label>冒险者名字<input name="player_name" maxlength="30" placeholder="你的名字" required></label><label>选择角色<select name="character_id">${(catalog.characters || []).map((c) => `<option value="${esc(c.id)}">${esc(c.name || c.label)} · ${esc(c.class_name || c.role || c.class || "")}</option>`).join("")}</select></label></div><p class="helper" id="character-description"></p>${
      create
        ? '<div><div class="eyebrow" style="margin-bottom:10px">选择故事模式</div><div class="modes">' +
          Object.entries(modeNames)
            .map(
              ([id, label]) =>
                `<button type="button" data-mode="${id}" ${id === "free" && !catalog.llm?.configured ? 'disabled title="需要服务端配置 LLM"' : ""} class="${id === mode ? "active" : ""}">${label}</button>`,
            )
            .join("") +
          '</div></div><p class="helper" id="mode-description">' +
          descriptions[mode] +
          '</p><label>世界主题（可选）<textarea name="theme" maxlength="500" placeholder="例如：迷雾中的海港、被遗忘的钟楼，以及一封没有署名的信。"></textarea></label>'
        : ""
    }<div class="error" id="entry-error" role="alert"></div><button class="primary" type="submit">${create ? "创建六席冒险桌" : "加入冒险"} ↗</button><p class="helper">角色身份保存在此浏览器。刷新自动恢复，首页可继续冒险；新标签页可加入另一角色。</p></form>`,
    (overlay, close) => {
      const form = $("#entry-form", overlay),
        characterSelect = $("[name=character_id]", form);
      if (create) {
        $("#entry-error", form).insertAdjacentHTML(
          "beforebegin",
          `<label>选择剧情本<select name="scenario_id"><option value="">经典冒险 · 雾港最后一盏灯</option>${(catalog.publishedScenarios || []).map((s) => `<option value="${esc(s.id)}">${esc(s.name)} · 发布 v${esc(s.published_revision)}</option>`).join("")}</select></label><label>交互方式<select name="interaction_mode">${Object.entries(
            interactionNames,
          )
            .map(([id, label]) => `<option value="${id}">${label}</option>`)
            .join(
              "",
            )}</select></label><p class="helper">预设引导：场景选项推进。自由创作：玩家共同叙述，房主可编辑场景。LLM 引导：模型建议、玩家确认、脚本裁定。已发布剧情会锁定当前版本。</p>`,
        );
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
      overlay.querySelectorAll("[data-mode]").forEach(
        (button) =>
          (button.onclick = () => {
            mode = button.dataset.mode;
            overlay
              .querySelectorAll("[data-mode]")
              .forEach((b) => b.classList.toggle("active", b === button));
            $("#mode-description", overlay).textContent = descriptions[mode];
            const scenarioSelect = $("[name=scenario_id]", form);
            if (scenarioSelect) {
              scenarioSelect.disabled = mode === "free";
              if (mode === "free") scenarioSelect.value = "";
            }
          }),
      );
      form.onsubmit = async (e) => {
        e.preventDefault();
        const submit = $("[type=submit]", form);
        submit.disabled = true;
        $("#entry-error", form).textContent = "";
        try {
          const body = Object.fromEntries(new FormData(form));
          if (create) {
            body.mode = mode;
            if (!body.scenario_id) delete body.scenario_id;
          } else body.invite_code = body.invite_code.trim();
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
  saveSeat();
  clearTimeout(reconnectTimer);
  const oldSocket = socket;
  socket = null;
  oldSocket?.close();
  session = null;
  room = null;
  connected = false;
  busy = false;
  draft = "";
  mobileTab = "story";
  sessionStorage.removeItem("hexbound-session");
  if (account) {
    api("/api/my/rooms")
      .then((data) => {
        accountRooms = data.items || [];
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
          `<div class="party-member ${p.id === session.member_id ? "mine" : ""}"><div class="avatar">${esc((p.name || "?")[0])}</div><div class="member-info"><div class="member-name">${esc(p.name)} ${p.id === session.member_id ? "<small>· 你</small>" : ""}${p.id === room.host_id ? ' <span class="mode-badge">♔</span>' : ""}</div><div class="member-class">${esc(p.class_name || p.character_id)} · ${p.online ? "在线" : "离线"}${room.combat?.turn_actor_id === p.id ? " · 当前回合" : ""}</div>${hp(p)}</div></div>`,
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
  return `<article class="event ${kind === "chat" ? "chat" : ""}"><div class="event-meta"><span class="${dm ? "dm-label" : ""}">${dm ? `✦ ${event.source === "llm" ? "AI 主持人" : event.source === "fallback" ? "本地主持 · 模型回退" : "本地主持"}` : esc(event.actor_name || "规则引擎")}</span><span>·</span><span>${esc(kind === "chat" ? "桌边交谈" : event.roll ? "权威判定" : dm ? "冒险日志" : "角色行动")}</span><span style="margin-left:auto">${String(event.seq || event.id || "").padStart(3, "0")}</span></div><p>${esc(event.text)}</p>${event.roll ? rollHtml(event.roll) : ""}${event.suggested_action_id && (room.available_actions || []).some((a) => a.id === event.suggested_action_id && (!a.host_only || room.host_id === session.member_id)) ? `<button class="small" data-action="${esc(event.suggested_action_id)}" ${busy || !connected || room.status !== "playing" ? "disabled" : ""}>建议行动：${esc((room.available_actions || []).find((a) => a.id === event.suggested_action_id)?.label)} ↗</button>` : ""}</article>`;
}
function renderRoom() {
  if (!room) return;
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
  app.innerHTML = `<div class="table-shell"><header class="table-header">${brand}<div class="room-title"><strong>${esc(room.name)}</strong><small>${esc(interactionNames[room.interaction_mode] || modeNames[room.mode])} / ${esc(statusNames[room.status] || room.status)}</small></div><div class="row"><span class="chip header-status"><span class="dot" style="background:${connected ? "var(--jade)" : "var(--brass)"}"></span>${connected ? "已连接" : "正在重连"}</span><button class="small" id="invite">邀请同伴 ↗</button><button class="small scene-toggle" id="scene-toggle">场景</button><button class="ghost" id="room-menu" aria-label="房间设置">•••</button></div></header>${!connected ? '<div class="notice">正在连接冒险桌，写入操作将在连接恢复后可用。</div>' : room.status === "paused" ? '<div class="notice">冒险已暂停。聊天仍然开放，等待房主继续。</div>' : ""}<main class="table-main"><aside class="sidebar party-sidebar ${mobileTab === "party" ? "mobile-visible" : ""}"><div class="section-title"><h2>同行者 / THE PARTY</h2><span class="mode-badge">${room.party.length} / 6</span></div>${partyHtml()}<div class="sidebar-bottom"><button class="small" id="copy-code">邀请码 ${esc(room.invite_code || session.invite_code)} ⧉</button><p>每个席位都有自己的命运。<br>你们将共同书写这段故事。</p></div></aside><section class="journal"><div class="journal-heading"><div><div class="eyebrow">${room.status === "lobby" ? "Before the journey" : "The adventure journal"}</div><h1>${esc(scene.title || room.name)}</h1></div><span class="chip">${esc(statusNames[room.status])}</span></div>${combat ? `<div class="combat-bar"><strong>第 ${esc(combat.round)} 轮</strong><span>${myTurn ? "轮到你行动" : `等待 ${esc(current?.name || "下一位角色")}`}</span><span style="margin-left:auto">${enemies.filter((e) => e.hp > 0).length} 名敌人</span></div>` : ""}<div class="journal-log" id="journal-log" role="log" aria-label="冒险记录">${room.status === "lobby" ? `<div class="welcome-scene"><div class="eyebrow">The first page is yours</div><h2>空白的一页，等你们落笔。</h2><p>邀请同伴入席，或独自开启旅程。<br>${host ? "准备好后，开始属于你们的冒险。" : "等待房主开始冒险。"}</p>${host ? '<button class="primary" id="start">启程 ↗</button>' : ""}</div>` : ""}${events.map(eventHtml).join("")}${!events.length && room.status !== "lobby" ? `<article class="event"><p>${esc(scene.text || "冒险日志正在载入…")}</p></article>` : ""}</div><div class="composer">${room.dm_pending ? '<p class="helper" role="status" style="margin-bottom:10px">✦ 主持人正在组织故事…</p>' : ""}<div class="actions">${(
    room.available_actions || []
  )
    .filter((a) => !a.host_only || host)
    .map(
      (a) =>
        `<button data-action="${esc(a.id)}" title="${esc(a.description || "")}" ${!canAct ? "disabled" : ""}>${esc(a.label)}${a.uses_remaining != null ? ` · 剩余 ${esc(a.uses_remaining)} 次` : ""} ↗</button>`,
    )
    .join(
      "",
    )}${combat && !(room.available_actions || []).some((a) => a.id === "end_turn") ? `<button id="end-turn" ${!canAct ? "disabled" : ""}>结束回合 →</button>` : ""}</div><form class="compose-box" id="intent-form"><textarea id="intent" aria-label="你的角色行动或聊天" maxlength="1500" placeholder="${active ? "描述你的角色如何行动，或与同伴交谈…" : "与同伴打个招呼…"}">${esc(draft)}</textarea><div class="compose-bottom"><select id="compose-mode" aria-label="发言类型"><option value="narrate" ${composeMode === "narrate" ? "selected" : ""}>角色扮演</option><option value="chat" ${composeMode === "chat" ? "selected" : ""}>桌边聊天</option></select><button class="primary" type="submit" ${!connected || busy ? "disabled" : ""}>${busy ? "处理中…" : "发送 ↗"}</button></div></form><div class="compose-hint"><span>数值判定请使用上方行动 · Ctrl/⌘ + Enter 发送</span><span>自动存档 · v${esc(room.version)}</span></div></div></section><aside class="sidebar scene-sidebar ${mobileTab === "scene" ? "mobile-visible" : ""}"><div class="section-title"><h2>此刻 / THE SCENE</h2><span>◇</span></div>${mapArt}<div class="eyebrow">Current location</div><h3>${esc(scene.title || "冒险尚未开始")}</h3><p>${esc(scene.text || "在这里，你将看到场景、目标和角色状态。")}</p>${scene.objective ? `<div class="objective"><div class="eyebrow">当前目标</div><p>${esc(scene.objective)}</p></div>` : ""}${enemies.length ? `<div class="objective"><div class="eyebrow">选择战斗目标</div>${enemies.map((e) => `<div class="enemy ${selectedTarget === e.id ? "selected" : ""}"><div class="row between"><strong>${esc(e.name)}</strong><span>${e.hp > 0 ? "敌对" : "已倒下"}</span></div>${hp(e)}${e.hp > 0 ? `<button class="small" data-target="${esc(e.id)}">${selectedTarget === e.id ? "✓ 当前目标" : "选择目标"}</button>` : ""}</div>`).join("")}</div>` : ""}${
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
  const log = $("#journal-log");
  if (atBottom) log.scrollTop = log.scrollHeight;
  else log.scrollTop = oldScroll;
  if (focused) {
    $("#intent").focus();
    $("#intent").setSelectionRange(selection, selection);
  }
  $("#invite").onclick = invite;
  $("#copy-code").onclick = invite;
  $("#room-menu").onclick = roomMenu;
  $(".sidebar-bottom").insertAdjacentHTML(
    "beforeend",
    '<p><a href="/account.html">账号与安全 ↗</a></p>',
  );
  if ($("#start")) $("#start").disabled = !connected || busy;
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
  app.querySelectorAll("[data-action]").forEach(
    (b) =>
      (b.onclick = () => {
        const action = (room.available_actions || []).find(
          (a) => a.id === b.dataset.action,
        );
        if (action?.target === "ally") {
          skillTargetDialog(action);
          return;
        }
        if (b.dataset.action === "heal") {
          healDialog();
          return;
        }
        command("action", {
          action_id: b.dataset.action,
          ...((b.dataset.action === "attack" || action?.target === "enemy") &&
          selectedTarget
            ? { target_id: selectedTarget }
            : {}),
        });
      }),
  );
  app.querySelectorAll("[data-target]").forEach(
    (b) =>
      (b.onclick = () => {
        selectedTarget = b.dataset.target;
        renderRoom();
      }),
  );
  $("#compose-mode").onchange = (e) => (composeMode = e.target.value);
  $("#intent").oninput = (e) => (draft = e.target.value);
  $("#intent").onkeydown = (e) => {
    if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) {
      e.preventDefault();
      $("#intent-form").requestSubmit();
    }
  };
  $("#intent-form").onsubmit = async (e) => {
    e.preventDefault();
    const text = $("#intent").value.trim();
    if (!text || busy) return;
    const type = active ? composeMode : "chat";
    if (await command(type, { text })) {
      draft = "";
      $("#intent").value = "";
    }
  };
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
            command("action", { action_id: "heal", target_id: b.dataset.heal });
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
    (p) => !p.dead && (action.effect !== "heal" || p.hp < p.max_hp),
  );
  openDialog(
    `<div class="row between"><h2 id="dialog-title">${esc(action.label)} · 选择目标</h2><button data-close class="ghost">×</button></div><div class="form">${allies.map((p) => `<button data-skill-target="${esc(p.id)}">${esc(p.name)} · HP ${esc(p.hp)} / ${esc(p.max_hp)}</button>`).join("") || '<p class="helper">没有合法目标。</p>'}</div>`,
    (overlay, close) => {
      overlay.querySelectorAll("[data-skill-target]").forEach(
        (b) =>
          (b.onclick = () => {
            close();
            command("action", {
              action_id: action.id,
              target_id: b.dataset.skillTarget,
            });
          }),
      );
    },
  );
}
function sceneEditor() {
  const scene = room.scene;
  openDialog(
    `<div class="row between"><h2 id="dialog-title">共同创作 · 当前场景</h2><button data-close class="ghost">×</button></div><form class="form" id="scene-form"><p class="helper">只修改叙述，不改变骰点、生命、技能、分支或胜负。修改会记入全队日志。</p><label>场景标题<input name="title" maxlength="80" required value="${esc(scene.title)}"></label><label>叙事<textarea name="text" maxlength="1800" required>${esc(scene.text)}</textarea></label><label>目标说明<input name="objective" maxlength="180" value="${esc(scene.objective)}"></label><button type="submit" class="primary">保存到当前冒险</button></form>`,
    (overlay, close) => {
      $("#scene-form", overlay).onsubmit = async (e) => {
        e.preventDefault();
        const payload = Object.fromEntries(new FormData(e.target));
        close();
        await command("scene_edit", payload);
      };
    },
  );
}
function roomMenu() {
  const host = room.host_id === session.member_id;
  openDialog(
    `<div class="row between"><h2 id="dialog-title">冒险桌设置</h2><button class="ghost" data-close>×</button></div><div class="form"><p class="helper">${esc(room.name)} · ${esc(modeNames[room.mode])}<br>进度自动保存在服务器，刷新会恢复当前角色。</p>${host && room.status === "playing" ? '<button id="pause">暂停冒险</button>' : ""}${host && room.status === "paused" ? '<button id="resume">继续冒险</button>' : ""}<button id="export-log">导出冒险日志</button><button id="view-rules">查看规则范围</button><button id="return-home" ${busy ? "disabled" : ""}>返回首页 · 保留我的席位</button><p class="helper">身份已保存在此浏览器。关闭标签页或返回首页会离线，席位仍保留；可从首页继续冒险。清除浏览器数据会丢失身份。</p></div>`,
    (overlay, close) => {
      if (host && room.status !== "finished") {
        $(".form", overlay).insertAdjacentHTML(
          "afterbegin",
          `<label>交互方式<select id="interaction-mode">${Object.entries(
            interactionNames,
          )
            .map(
              ([id, label]) =>
                `<option value="${id}" ${room.interaction_mode === id ? "selected" : ""}>${label}</option>`,
            )
            .join(
              "",
            )}</select></label><button id="apply-interaction">应用交互方式</button>${room.interaction_mode === "freeform" && room.status !== "lobby" ? '<button id="edit-scene">编辑当前场景叙述</button>' : ""}`,
        );
        $("#apply-interaction", overlay).onclick = () => {
          const mode = $("#interaction-mode", overlay).value;
          close();
          command("set_interaction", { mode });
        };
        $("#edit-scene", overlay)?.addEventListener("click", () => {
          close();
          sceneEditor();
        });
      }
      $("#pause", overlay)?.addEventListener("click", () => {
        close();
        command("pause");
      });
      $("#resume", overlay)?.addEventListener("click", () => {
        close();
        command("resume");
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
          let after = 0;
          while (true) {
            const page = await api(
              `/api/rooms/${session.room_id}/events?after=${after}`,
            );
            all.push(...page.events);
            after += page.events.length;
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
async function command(type, payload = {}) {
  if (busy || !connected) return false;
  busy = true;
  renderRoom();
  const body = {
    command_id: newCommandId(),
    expected_version: room.version,
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
      if (!(error instanceof TypeError)) throw error;
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
boot();

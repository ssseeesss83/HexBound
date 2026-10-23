const root = document.querySelector("#studio");
const $ = (s, r = document) => r.querySelector(s);
const escapeHTML = (v) =>
  String(v ?? "").replace(
    /[&<>"']/g,
    (c) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[
        c
      ],
  );
const clone = (v) => JSON.parse(JSON.stringify(v));
const kinds = {
  skill: { name: "技能卡", sub: "Actions & abilities", symbol: "✧" },
  monster: { name: "怪兽卡", sub: "Creatures & encounters", symbol: "♜" },
  scenario: { name: "剧情本", sub: "Stories & branching worlds", symbol: "◇" },
};
const effects = { attack: "攻击", heal: "治疗", check: "检定", defend: "防御" },
  abilities = {
    str: "力量",
    dex: "敏捷",
    con: "体质",
    int: "智力",
    wis: "感知",
    cha: "魅力",
  },
  targets = { self: "自身", ally: "队友", enemy: "敌人", scene: "场景" };
let token = sessionStorage.getItem("hexbound-studio-token") || "",
  account = null,
  csrfToken = "",
  legacyEnabled = false,
  admin = false,
  writeEnabled = false,
  kind = "skill",
  items = [],
  publicItems = [],
  selected = null,
  model = null,
  dirty = false,
  query = "",
  filter = "active",
  issues = [],
  warnings = [],
  valid = null,
  busy = false,
  tab = "edit",
  timer;
const e = escapeHTML;
function toast(text) {
  const node = $("#studio-toast");
  node.textContent = text;
  node.hidden = false;
  clearTimeout(timer);
  timer = setTimeout(() => (node.hidden = true), 6000);
}
async function api(path, options = {}) {
  const response = await fetch(path, {
    ...options,
    headers: {
      "Content-Type": "application/json",
      ...(csrfToken ? { "X-CSRF-Token": csrfToken } : {}),
      ...(legacyEnabled && !account && token
        ? { Authorization: `Bearer ${token}` }
        : {}),
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
        : Array.isArray(data.detail)
          ? data.detail.map((x) => `${x.loc?.join(".")}: ${x.msg}`).join("；")
          : `请求失败 (${response.status})`,
    );
    error.status = response.status;
    error.data = data;
    throw error;
  }
  return data;
}
function extractItem(data) {
  return data.item || data;
}
function dirtyConfirm() {
  return (
    !dirty ||
    window.confirm("当前有未保存的修改。离开会丢弃这些修改，是否继续？")
  );
}
function status(item) {
  return item.archived
    ? "archived"
    : item.published_revision === item.revision
      ? "published"
      : "draft";
}
function statusLabel(item) {
  return item.archived
    ? "已归档"
    : item.published_revision === item.revision
      ? "已发布"
      : item.published_revision
        ? "已发布 · 有新草稿"
        : "草稿";
}
function touch() {
  dirty = true;
  valid = null;
  const indicator = $("#save-indicator");
  if (indicator) indicator.textContent = "● 有未保存修改";
  const save = $("#save");
  if (save) save.disabled = false;
  updatePreview();
}
function currentItems() {
  return (admin ? items : publicItems)
    .filter((i) => i.kind === kind)
    .filter(
      (i) =>
        !query ||
        `${i.name} ${i.description || i.draft?.description || ""} ${(i.tags || i.draft?.tags || []).join(" ")}`
          .toLowerCase()
          .includes(query.toLowerCase()),
    )
    .filter(
      (i) =>
        !admin ||
        filter === "all" ||
        (filter === "active" && !i.archived) ||
        (filter === "published" && !!i.published_revision && !i.archived) ||
        (filter === "draft" && status(i) === "draft") ||
        (filter === "archived" && i.archived),
    );
}
function field(label, path, value, type = "text", extra = "") {
  return `<label>${label}<input data-field="${e(path)}" type="${type}" value="${e(value ?? "")}" ${extra}></label>`;
}
function area(label, path, value, rows = 3) {
  return `<label>${label}<textarea data-field="${e(path)}" rows="${rows}">${e(value)}</textarea></label>`;
}
function select(label, path, value, options) {
  return `<label>${label}<select data-field="${e(path)}">${Object.entries(
    options,
  )
    .map(
      ([id, text]) =>
        `<option value="${e(id)}" ${String(value ?? "") === id ? "selected" : ""}>${e(text)}</option>`,
    )
    .join("")}</select></label>`;
}
function getRefOptions(refKind, checksOnly = false) {
  return Object.fromEntries(
    items
      .filter(
        (i) =>
          i.kind === refKind &&
          !i.archived &&
          (!checksOnly ||
            i.draft?.effect === "check" ||
            i.published?.effect === "check"),
      )
      .map((i) => [
        i.id,
        `${i.name} ${i.published_revision ? "" : "（尚未发布）"}`,
      ]),
  );
}
function nodeOptions() {
  return {
    "": "选择目标节点",
    ...Object.fromEntries(
      (model?.nodes || []).map((n) => [
        n.id,
        `${n.title || "未命名"} · ${n.id}`,
      ]),
    ),
  };
}
function listHtml() {
  const filtered = currentItems();
  return `<div class="row between"><div><div class="eyebrow">CONTENT LIBRARY</div><h2 style="font-size:18px;font-weight:400;margin-top:8px">${kinds[kind].name} <small style="font-size:11px">${filtered.length}</small></h2></div>${admin ? '<button id="new-item" class="small primary">＋ 新建</button>' : ""}</div><div class="list-tools"><input id="search" aria-label="搜索名称或标签" placeholder="搜索名称、标签…" value="${e(query)}"><select id="status-filter" aria-label="内容状态" ${admin ? "" : "disabled"}>${Object.entries(
    {
      active: "未归档",
      all: "全部状态",
      draft: "草稿",
      published: "已发布",
      archived: "已归档",
    },
  )
    .map(
      ([id, label]) =>
        `<option value="${id}" ${filter === id ? "selected" : ""}>${label}</option>`,
    )
    .join(
      "",
    )}</select></div><div class="content-list">${filtered.map((i) => `<button class="content-item ${selected?.id === i.id ? "selected" : ""}" data-open="${e(i.id)}"><h3>${e(i.name)}</h3><p>${e(i.description || i.draft?.description || "尚未添加简介")}</p><div class="row"><span class="badge ${admin ? status(i) : "published"}">${admin ? statusLabel(i) : "已发布"}</span><span class="muted">${admin ? "r" + i.revision : (i.tags || []).slice(0, 2).map(e).join(" · ")}</span></div></button>`).join("") || '<p class="helper" style="padding:20px 4px">没有符合条件的内容。试试更改筛选，或创建第一张卡片。</p>'}</div>`;
}
function shell() {
  root.innerHTML = `<div class="studio-shell"><header class="studio-header"><a href="/" class="brand"><span class="symbol">⬡</span><div>HEXBOUND<div class="studio-subtitle">内容工坊 / THE ATELIER</div></div></a><div class="row"><a href="/" class="inline-link">返回冒险桌 ↗</a><span class="chip">${admin ? "内容管理" : "公开内容目录"}</span><button id="auth" class="small">${account ? "账号中心" : legacyEnabled ? (admin ? "退出管理" : "管理员解锁") : "登录 / 注册"}</button></div></header><div class="admin-banner">${admin ? "<strong>草稿与发布分离。</strong> 保存只更新草稿；校验通过并发布后，内容才可用于新冒险。已开始的冒险保持原有版本。" : writeEnabled ? "你正在浏览已发布内容摘要。创作者或管理员登录后可编辑技能、怪兽与完整剧情。" : "你正在浏览公开目录。请登录具有创作者或管理员权限的账号管理内容。"}</div><main class="studio-layout"><nav class="studio-nav" aria-label="内容分类">${Object.entries(
    kinds,
  )
    .map(
      ([id, k]) =>
        `<button data-kind="${id}" class="${kind === id ? "active" : ""}"><strong>${k.symbol} ${k.name}</strong><small>${k.sub}</small></button>`,
    )
    .join(
      "",
    )}<div class="nav-bottom">${admin ? '<button id="import"><strong>↥ 导入内容包</strong><small>JSON bundle · 草稿导入</small></button><button id="generate"><strong>✦ 灵感助手</strong><small>LLM 辅助生成草稿</small></button>' : '<p class="helper">故事需要想象力，<br>规则需要确定性。</p>'}</div></nav><section class="studio-list" id="list">${listHtml()}</section><section class="studio-detail" id="detail"></section></main></div>`;
  bindShell();
  renderDetail();
}
function bindShell() {
  $("#auth").onclick = () => {
    if (account || !legacyEnabled) {
      if (dirtyConfirm()) location.href = "/account.html?next=%2Fstudio.html";
    } else (admin ? logout : authDialog)();
  };
  root.querySelectorAll("[data-kind]").forEach(
    (b) =>
      (b.onclick = () => {
        if (!dirtyConfirm()) return;
        kind = b.dataset.kind;
        selected = null;
        model = null;
        dirty = false;
        issues = [];
        valid = null;
        shell();
      }),
  );
  $("#import")?.addEventListener("click", importDialog);
  $("#generate")?.addEventListener("click", generateDialog);
  bindList();
}
function bindList() {
  $("#search").oninput = (event) => {
    query = event.target.value;
    const position = event.target.selectionStart;
    $("#list").innerHTML = listHtml();
    bindList();
    $("#search").focus();
    $("#search").setSelectionRange(position, position);
  };
  $("#status-filter").onchange = (event) => {
    filter = event.target.value;
    $("#list").innerHTML = listHtml();
    bindList();
  };
  $("#new-item")?.addEventListener("click", newItem);
  root
    .querySelectorAll("[data-open]")
    .forEach((b) => (b.onclick = () => openItem(b.dataset.open)));
}
function renderDetail() {
  const detail = $("#detail");
  if (!selected) {
    detail.innerHTML = `<div class="studio-empty"><div class="symbol">${kinds[kind].symbol}</div><h2>每一张卡，都是故事的可能。</h2><p>${admin ? "从左侧选择内容，或新建一份草稿。这里的规则字段会进入服务端脚本判定，叙事不会覆盖数值。" : "选择一份已发布内容，阅读其简介与标签。完整剧情仅向创作者与管理员开放，避免提前揭露冒险。"}</p>${admin ? '<button class="primary" id="empty-new">新建' + kinds[kind].name + " ↗</button>" : ""}</div>`;
    $("#empty-new")?.addEventListener("click", newItem);
    return;
  }
  if (!admin) {
    detail.innerHTML = `<div class="detail-header"><div><div class="eyebrow">PUBLISHED / ${kinds[kind].sub}</div><h1>${e(selected.name)}</h1></div><span class="badge published">已发布</span></div><div class="preview-card"><div class="preview-mark">${kinds[kind].symbol}</div><p>${e(selected.description || "暂无简介")}</p><div class="preview-tags">${(selected.tags || []).map((t) => `<span class="badge">${e(t)}</span>`).join("")}</div></div><p class="publish-note">这里只展示公开摘要。完整规则、怪兽数值及剧情分支需要管理员身份查看。</p>${kind === "scenario" ? `<a href="/?scenario=${encodeURIComponent(selected.id)}" class="inline-link">用此剧本创建冒险 ↗</a>` : ""}`;
    return;
  }
  detail.innerHTML = `<div class="detail-header"><div><div class="eyebrow">${e(kinds[kind].sub)}</div><h1>${e(model.name || "未命名草稿")}</h1><div class="detail-meta"><span class="badge ${status(selected)}">${statusLabel(selected)}</span> ${selected.id ? `草稿 r${selected.revision} · 发布 ${selected.published_revision ? "r" + selected.published_revision : "—"}` : "尚未保存"} <span id="save-indicator" class="dirty-dot">${dirty ? "● 有未保存修改" : ""}</span></div></div></div><div class="detail-actions"><button id="save" class="primary" ${busy || !dirty || selected.archived ? "disabled" : ""}>保存草稿</button><button id="validate" ${!selected.id || busy ? "disabled" : ""}>校验</button><button id="publish" ${!selected.id || selected.archived || busy ? "disabled" : ""}>发布版本 ↗</button><button id="duplicate" ${!selected.id || busy ? "disabled" : ""}>复制</button><button id="export" ${!selected.id || busy ? "disabled" : ""}>导出</button><button id="archive" ${!selected.id || selected.archived || busy ? "disabled" : ""}>归档</button></div><p class="publish-note">${selected.published_revision ? "已发布版本继续供新冒险使用；保存修改不会自动替换发布内容。" : "草稿仅管理员可见。发布前请核对规则字段、引用依赖与剧情出口。"}</p>${kind === "scenario" && selected.published_revision && !selected.archived ? `<p style="margin-bottom:20px"><a href="/?scenario=${encodeURIComponent(selected.id)}" class="inline-link">用已发布版本创建冒险 ↗</a></p>` : ""}<div id="validation">${validationHtml()}</div><div class="studio-tabs"><button data-tab="edit" class="${tab === "edit" ? "active" : ""}">编辑与预览</button><button data-tab="history" class="${tab === "history" ? "active" : ""}" ${selected.id ? "" : "disabled"}>版本记录</button></div>${tab === "history" ? '<div id="history-list"><p class="helper">正在读取版本记录…</p></div>' : `<div class="editor-grid"><div class="editor-form" id="editor">${editorHtml()}</div><aside class="card-preview"><div class="preview-label">LIVE PREVIEW / 当前草稿预览</div><div id="preview"></div></aside></div><details class="advanced"><summary>高级：查看与编辑原始数据</summary><p class="helper" style="margin-top:12px">常规编辑无需使用此处。应用 JSON 只修改当前草稿，仍需保存、校验并发布。</p><textarea id="raw-json" aria-label="原始内容 JSON">${e(JSON.stringify(model, null, 2))}</textarea><button class="small" id="apply-json" style="margin-top:10px">应用到草稿</button></details>`}`;
  bindValidation();
  $("#save").onclick = save;
  $("#validate").onclick = validate;
  $("#publish").onclick = publish;
  $("#duplicate").onclick = duplicate;
  $("#export").onclick = exportCurrent;
  $("#archive").onclick = archive;
  detail.querySelectorAll("[data-tab]").forEach(
    (b) =>
      (b.onclick = () => {
        tab = b.dataset.tab;
        renderDetail();
      }),
  );
  if (tab === "history") {
    loadHistory();
    return;
  }
  bindEditor();
  updatePreview();
  if (selected.archived)
    $("#editor")
      .querySelectorAll("input,textarea,select,button")
      .forEach((el) => (el.disabled = true));
  $("#apply-json").onclick = () => {
    try {
      const parsed = JSON.parse($("#raw-json").value);
      if (!parsed || typeof parsed !== "object" || Array.isArray(parsed))
        throw new Error("内容必须是 JSON 对象");
      model = parsed;
      touch();
      renderDetail();
    } catch (error) {
      toast("JSON 未应用：" + error.message);
    }
  };
}
function validationHtml() {
  if (issues.length)
    return `<div class="issues" role="alert"><h3>请先解决 ${issues.length} 个问题</h3><ul>${issues.map((i, index) => `<li>${e(typeof i === "string" ? i : JSON.stringify(i))} <button class="inline-link" data-issue="${index}">定位字段 ↗</button></li>`).join("")}</ul></div>`;
  return (
    (valid === true
      ? '<div class="valid-status">✓ 内容校验通过。确认内容后即可发布。</div>'
      : "") +
    (warnings.length
      ? `<p class="helper">${warnings.map(e).join("；")}</p>`
      : "")
  );
}
function editorHtml() {
  const base = `<div class="field-grid">${field("内容名称", "name", model.name, "text", 'maxlength="80"')}${field("唯一标识 ID", "id", model.id, "text", selected.id ? "readonly" : 'pattern="[a-zA-Z0-9_-]+"')}</div>${area("公开简介 · 请勿在此填写剧情谜底", "description", model.description)}${field("标签 · 使用逗号分隔", "tags", (model.tags || []).join(", "))}`;
  if (kind === "skill")
    return (
      base +
      `<section class="editor-section"><h2>规则配置 <small>由服务端执行</small></h2><div class="field-grid">${select("效果类型", "effect", model.effect, effects)}${select("作用目标", "target", model.target, allowedTargets(model.effect))}${select("使用属性", "ability", model.ability, abilities)}${
        model.effect === "check"
          ? select(
              "熟练技能 · 可选",
              "proficiency_skill",
              model.proficiency_skill || "",
              Object.fromEntries([
                ["", "纯属性检定"],
                ["acrobatics", "杂技 · 敏捷"],
                ["animal-handling", "驯兽 · 感知"],
                ["arcana", "奥秘 · 智力"],
                ["athletics", "运动 · 力量"],
                ["deception", "欺瞒 · 魅力"],
                ["history", "历史 · 智力"],
                ["insight", "洞悉 · 感知"],
                ["intimidation", "威吓 · 魅力"],
                ["investigation", "调查 · 智力"],
                ["medicine", "医药 · 感知"],
                ["nature", "自然 · 智力"],
                ["perception", "察觉 · 感知"],
                ["performance", "表演 · 魅力"],
                ["persuasion", "游说 · 魅力"],
                ["religion", "宗教 · 智力"],
                ["sleight-of-hand", "巧手 · 敏捷"],
                ["stealth", "隐匿 · 敏捷"],
                ["survival", "求生 · 感知"],
              ]),
            )
          : ""
      }${field("使用次数 · 留空表示不限次", "uses", model.uses, "number", 'min="1" max="20"')}${field("骰子表达式", "dice", model.dice, "text", 'placeholder="例如 1d8"')}${field("固定加值", "bonus", model.bonus, "number", 'min="-10" max="20"')}${field("检定难度 DC", "dc", model.dc, "number", 'min="5" max="30"')}</div><p class="helper" style="margin-top:12px">${model.effect === "check" ? "检定使用 d20 + 属性修正 + 所选技能熟练/专精 + 固定加值，对抗 DC；未选技能时只用属性。骰子字段不参与检定；剧情通过成功 / 失败出口推进。" : model.effect === "attack" ? "命中 = d20 + 属性修正 + 熟练加值 + 固定加值；伤害 = 伤害骰 + 属性修正 + 固定加值。暴击翻倍伤害骰。" : model.effect === "heal" ? "治疗量为骰子 + 固定加值，不使用属性修正，且不超过目标最大生命值。请明确作用于自身或队友。" : "防御消耗一次动作，使攻击者在针对你的攻击中承受劣势，持续到你的下一回合。此效果不使用属性、骰子、加值和 DC 字段。"}</p></section>`
    );
  if (kind === "monster")
    return (
      base +
      `<section class="editor-section"><h2>战斗数据</h2><div class="field-grid three">${field("击败经验 XP", "xp", model.xp ?? 50, "number", 'min="0" max="155000"')}${field("生命 HP", "hp", model.hp, "number", 'min="1" max="500"')}${field("护甲 AC", "ac", model.ac, "number", 'min="5" max="30"')}${field("先攻加值", "initiative_bonus", model.initiative_bonus, "number", 'min="-5" max="20"')}${field("攻击加值", "attack_bonus", model.attack_bonus, "number", 'min="-5" max="20"')}${field("伤害骰", "damage_dice", model.damage_dice)}${field("伤害加值", "damage_bonus", model.damage_bonus, "number", 'min="-5" max="20"')}</div><p class="helper" style="margin-top:12px">怪兽数值是固定模板。引用此怪兽的剧情发布后，会将版本固定到新房间。</p></section>`
    );
  return (
    base +
    `<section class="editor-section"><h2>剧情结构 <small>${(model.nodes || []).length} 个节点</small></h2>${select("起始节点", "entry_node_id", model.entry_node_id, nodeOptions())}<p class="helper" style="margin-top:12px">每个选项必须通向已有节点。检定行动分别连接成功与失败出口；结局节点不再提供行动或遭遇。</p><div class="field-grid" style="margin-top:15px">${referenceChecks("本剧情可用技能", "skill_ids", "skill")}${referenceChecks("本剧情可用怪兽", "monster_ids", "monster")}</div>${(model.nodes || []).map((node, index) => nodeHtml(node, index)).join("")}<button id="add-node" type="button" style="margin-top:15px">＋ 添加剧情节点</button></section>`
  );
}
function allowedTargets(effect) {
  return Object.fromEntries(
    (effect === "attack"
      ? ["enemy"]
      : effect === "heal"
        ? ["self", "ally"]
        : effect === "check"
          ? ["scene"]
          : ["self"]
    ).map((id) => [id, targets[id]]),
  );
}
function referenceChecks(label, path, refKind) {
  const options = getRefOptions(refKind);
  return `<div><div class="field-label">${label}</div><div class="stack" style="gap:7px;margin-top:10px">${
    Object.entries(options)
      .map(
        ([id, name]) =>
          `<label style="display:flex;flex-direction:row;align-items:center;gap:8px;font-size:11px"><input type="checkbox" data-ref="${e(path)}" value="${e(id)}" ${(getPath(model, path) || []).includes(id) ? "checked" : ""} style="width:auto">${e(name)}</label>`,
      )
      .join("") || '<p class="helper">请先创建并发布引用内容。</p>'
  }</div></div>`;
}
const objectTags = {
  movable: "可移动",
  cover: "可遮挡",
  flammable: "可燃",
  fire: "火源",
  searchable: "可搜索",
  interactable: "可交互",
  sand: "沙土",
};
function objectHtml(obj, index, oi) {
  const path = `nodes.${index}.objects.${oi}`;
  return `<div class="node-action"><div class="row between"><h4>环境对象 ${oi + 1}</h4><button data-remove-object="${index}:${oi}">移除</button></div><div class="field-grid">${field("名称", `${path}.name`, obj.name)}${field("对象 ID", `${path}.id`, obj.id)}</div>${area("可观察描述", `${path}.description`, obj.description, 2)}<div class="field-grid">${field("耐久 HP（1–100）", `${path}.hp`, obj.hp, "number", 'min="1" max="100"')}${field("难度 DC（5–25）", `${path}.dc`, obj.dc, "number", 'min="5" max="25"')}</div><div class="field-grid">${Object.entries(
    objectTags,
  )
    .map(
      ([tag, label]) =>
        `<label><input type="checkbox" data-object-tag="${path}.tags" value="${tag}" ${(obj.tags || []).includes(tag) ? "checked" : ""}>${label}</label>`,
    )
    .join("")}</div></div>`;
}
function nodeHtml(node, index) {
  const path = `nodes.${index}`;
  return `<section class="node-editor" data-node="${index}"><div class="node-heading"><strong>${index + 1}. ${e(node.title || "未命名节点")} ${node.ending ? "· 结局" : ""}</strong><button data-remove-node="${index}">删除节点</button></div><div class="node-fields"><div class="field-grid">${field("节点名称", `${path}.title`, node.title)}${field("节点 ID", `${path}.id`, node.id)}</div>${area("场景叙述", `${path}.text`, node.text, 4)}${field("当前目标", `${path}.objective`, node.objective)}<h4>环境对象 · ${(node.objects || []).length}/20</h4><p class="helper">仅这些明确存在的对象可供环境行动选择；标签不执行任意代码。未配置即无对象。</p>${(node.objects || []).map((obj, oi) => objectHtml(obj, index, oi)).join("")}<button data-add-object="${index}" ${(node.objects || []).length >= 20 ? "disabled" : ""}>＋ 添加环境对象</button><label style="flex-direction:row;align-items:center"><input type="checkbox" data-field="${path}.ending" ${node.ending ? "checked" : ""} style="width:auto">这是结局节点（无后续行动与遭遇）</label>${!node.ending ? `${referenceChecks("此节点遭遇", `${path}.monster_ids`, "monster")}<div>${(node.actions || []).map((action, aIndex) => actionHtml(action, index, aIndex)).join("")}</div><button class="small" data-add-action="${index}">＋ 添加玩家选项</button>` : ""}</div></section>`;
}
function actionHtml(action, index, aIndex) {
  const path = `nodes.${index}.actions.${aIndex}`;
  return `<div class="node-action"><div class="row between"><h4>选项 ${aIndex + 1}</h4><button class="inline-link" data-remove-action="${index}:${aIndex}">移除</button></div><div class="field-grid">${field("玩家看到的选项", `${path}.label`, action.label)}${field("行动 ID", `${path}.id`, action.id)}</div>${select("判定方式", `${path}.skill_id`, action.skill_id, { "": "直接推进 · 无检定", ...getRefOptions("skill", true) })}${action.skill_id ? `<div class="field-grid">${select("检定成功 →", `${path}.success_node_id`, action.success_node_id, nodeOptions())}${select("检定失败 →", `${path}.failure_node_id`, action.failure_node_id, nodeOptions())}</div>` : select("行动后前往 →", `${path}.next_node_id`, action.next_node_id, nodeOptions())}</div>`;
}
function getPath(obj, path) {
  return path.split(".").reduce((o, k) => o?.[k], obj);
}
function setPath(obj, path, value) {
  const parts = path.split(".");
  let cursor = obj;
  for (const key of parts.slice(0, -1)) {
    if (!cursor[key]) cursor[key] = {};
    cursor = cursor[key];
  }
  cursor[parts.at(-1)] = value;
}
function redrawEditor() {
  const scroll = window.scrollY;
  renderDetail();
  window.scrollTo?.(0, scroll);
}
function bindEditor() {
  const editor = $("#editor");
  if (kind === "skill") {
    const inactive =
      model.effect === "defend"
        ? ["ability", "dice", "bonus", "dc"]
        : model.effect === "heal"
          ? ["ability", "dc"]
          : model.effect === "attack"
            ? ["dc"]
            : ["dice"];
    editor.querySelectorAll("[data-field]").forEach((input) => {
      if (inactive.includes(input.dataset.field)) {
        input.disabled = true;
        input.title = "此效果不使用这个字段";
      }
    });
  }
  editor.querySelectorAll("[data-field]").forEach((input) => {
    input.addEventListener(
      input.tagName === "SELECT" ||
        input.type === "checkbox" ||
        /^nodes\.\d+\.(id|title)$/.test(input.dataset.field)
        ? "change"
        : "input",
      () => {
        const path = input.dataset.field;
        let value =
          input.type === "checkbox"
            ? input.checked
            : input.type === "number"
              ? input.value === ""
                ? null
                : Number(input.value)
              : input.value;
        if (path === "tags")
          value = input.value
            .split(/[,，]/)
            .map((t) => t.trim())
            .filter(Boolean);
        if (path === "proficiency_skill") value = value || null;
        const previous = getPath(model, path);
        setPath(model, path, value);
        if (/^nodes\.\d+\.id$/.test(path)) {
          if (model.entry_node_id === previous) model.entry_node_id = value;
          for (const n of model.nodes)
            for (const a of n.actions || [])
              for (const key of [
                "next_node_id",
                "success_node_id",
                "failure_node_id",
              ])
                if (a[key] === previous) a[key] = value;
          touch();
          redrawEditor();
          return;
        }
        if (/^nodes\.\d+\.title$/.test(path)) {
          touch();
          redrawEditor();
          return;
        }
        if (path === "proficiency_skill" && value) {
          model.ability = {
            acrobatics: "dex",
            "animal-handling": "wis",
            arcana: "int",
            athletics: "str",
            deception: "cha",
            history: "int",
            insight: "wis",
            intimidation: "cha",
            investigation: "int",
            medicine: "wis",
            nature: "int",
            perception: "wis",
            performance: "cha",
            persuasion: "cha",
            religion: "int",
            "sleight-of-hand": "dex",
            stealth: "dex",
            survival: "wis",
          }[value];
          touch();
          redrawEditor();
          return;
        }
        if (path === "ability") model.proficiency_skill = null;
        if (path === "effect") {
          if (value !== "check") model.proficiency_skill = null;
          model.target = Object.keys(allowedTargets(value))[0];
          if (value === "check") model.dice = "1d20";
          touch();
          redrawEditor();
          return;
        }
        if (path.endsWith(".skill_id")) {
          const action = getPath(model, path.split(".").slice(0, -1).join("."));
          if (value) {
            delete action.next_node_id;
            action.success_node_id ||= "";
            action.failure_node_id ||= "";
            if (!model.skill_ids.includes(value)) model.skill_ids.push(value);
          } else {
            delete action.skill_id;
            delete action.success_node_id;
            delete action.failure_node_id;
            action.next_node_id = "";
          }
          touch();
          redrawEditor();
          return;
        }
        if (path.endsWith(".ending")) {
          const node = getPath(model, path.split(".").slice(0, -1).join("."));
          if (value) {
            node.actions = [];
            node.monster_ids = [];
          }
          touch();
          redrawEditor();
          return;
        }
        touch();
      },
    );
  });
  editor.querySelectorAll("[data-ref]").forEach(
    (input) =>
      (input.onchange = () => {
        const path = input.dataset.ref,
          values = getPath(model, path) || [];
        setPath(
          model,
          path,
          input.checked
            ? [...new Set([...values, input.value])]
            : values.filter((x) => x !== input.value),
        );
        if (
          path.startsWith("nodes.") &&
          input.checked &&
          !model.monster_ids.includes(input.value)
        )
          model.monster_ids.push(input.value);
        touch();
      }),
  );
  editor.querySelectorAll("[data-object-tag]").forEach(
    (input) =>
      (input.onchange = () => {
        const path = input.dataset.objectTag,
          values = getPath(model, path) || [];
        setPath(
          model,
          path,
          input.checked
            ? [...new Set([...values, input.value])]
            : values.filter((t) => t !== input.value),
        );
        touch();
      }),
  );
  editor.querySelectorAll("[data-add-object]").forEach(
    (button) =>
      (button.onclick = () => {
        const node = model.nodes[Number(button.dataset.addObject)];
        node.objects ||= [];
        if (node.objects.length >= 20) return;
        node.objects.push({
          id: uniqueId("object", node.objects),
          name: "环境对象",
          description: "",
          tags: [],
          hp: 10,
          dc: 12,
        });
        touch();
        redrawEditor();
      }),
  );
  editor.querySelectorAll("[data-remove-object]").forEach(
    (button) =>
      (button.onclick = () => {
        const [ni, oi] = button.dataset.removeObject.split(":").map(Number);
        model.nodes[ni].objects.splice(oi, 1);
        touch();
        redrawEditor();
      }),
  );
  $("#add-node")?.addEventListener("click", () => {
    model.nodes.push({
      id: uniqueId("node", model.nodes),
      title: "新的场景",
      text: "",
      objective: "",
      actions: [],
      monster_ids: [],
      objects: [],
      ending: false,
    });
    touch();
    redrawEditor();
  });
  editor.querySelectorAll("[data-remove-node]").forEach(
    (b) =>
      (b.onclick = () => {
        const index = Number(b.dataset.removeNode),
          node = model.nodes[index];
        if (
          !window.confirm(`删除「${node.title}」？引用它的分支需要重新连接。`)
        )
          return;
        model.nodes.splice(index, 1);
        touch();
        redrawEditor();
      }),
  );
  editor.querySelectorAll("[data-add-action]").forEach(
    (b) =>
      (b.onclick = () => {
        const node = model.nodes[Number(b.dataset.addAction)];
        node.actions.push({
          id: uniqueId("action", node.actions),
          label: "新的选择",
          next_node_id: "",
        });
        touch();
        redrawEditor();
      }),
  );
  editor.querySelectorAll("[data-remove-action]").forEach(
    (b) =>
      (b.onclick = () => {
        const [n, a] = b.dataset.removeAction.split(":").map(Number);
        model.nodes[n].actions.splice(a, 1);
        touch();
        redrawEditor();
      }),
  );
}
function uniqueId(prefix, arr = []) {
  let n = arr.length + 1;
  while (arr.some((x) => x.id === `${prefix}-${n}`)) n++;
  return `${prefix}-${n}`;
}
function updatePreview() {
  const preview = $("#preview");
  if (!preview || !model) return;
  let stats = "",
    rule = "";
  if (kind === "skill") {
    stats = `<div><strong>${e(model.dice)}</strong><small>骰子</small></div><div><strong>${e(model.bonus)}</strong><small>固定加值</small></div><div><strong>${model.uses ?? "∞"}</strong><small>使用次数</small></div>`;
    rule = `${effects[model.effect] || model.effect} · ${abilities[model.ability] || model.ability} · ${targets[model.target] || model.target}${model.effect === "check" ? ` · DC ${model.dc}` : ""}`;
    if (model.effect === "defend") {
      stats = "";
      rule = "防御姿态 · 消耗动作 · 来袭攻击劣势至下回合";
    } else if (model.effect === "check") {
      stats = `<div><strong>d20</strong><small>检定骰</small></div><div><strong>${e(model.dc)}</strong><small>难度 DC</small></div><div><strong>${model.uses ?? "∞"}</strong><small>使用次数</small></div>`;
    }
  } else if (kind === "monster") {
    stats = `<div><strong>${e(model.hp)}</strong><small>生命</small></div><div><strong>${e(model.ac)}</strong><small>护甲</small></div><div><strong>${e(model.initiative_bonus)}</strong><small>先攻</small></div>`;
    rule = `攻击 ${Number(model.attack_bonus) >= 0 ? "+" : ""}${e(model.attack_bonus)} · 伤害 ${e(model.damage_dice)} + ${e(model.damage_bonus)}`;
  }
  preview.innerHTML = `<div class="preview-card"><div class="eyebrow">${kinds[kind].sub}</div><div class="preview-mark">${kinds[kind].symbol}</div><h2>${e(model.name || "未命名内容")}</h2><p>${e(model.description || "在左侧填写简介，让旅人了解它的来历。")}</p>${stats ? `<div class="preview-stats">${stats}</div>` : ""}${rule ? `<div class="preview-rule">${rule}</div>` : ""}${kind === "scenario" ? `<div class="preview-rule">${(model.nodes || []).length} 个节点 · ${(model.nodes || []).filter((n) => n.ending).length} 个结局<br>${graphWarnings().map(e).join("<br>")}${graphWarnings().length ? "<br>" : ""}起点：${e(model.nodes?.find((n) => n.id === model.entry_node_id)?.title || "尚未选择")}</div>${(model.nodes || []).map((n) => `<div class="preview-scene"><strong>${e(n.title)} ${n.ending ? "· 结局" : ""}</strong><p>${e(n.objective || n.text?.slice(0, 90))}</p>${(n.actions || []).map((a) => `<p>↳ ${e(a.label)} → ${e(a.skill_id ? `成功：${nodeName(a.success_node_id)} / 失败：${nodeName(a.failure_node_id)}` : nodeName(a.next_node_id))}</p>`).join("")}${(n.objects || []).map((o) => `<p>◈ ${e(o.name)} · ${e((o.tags || []).map((t) => objectTags[t] || t).join(" / "))} · HP ${e(o.hp)} · DC ${e(o.dc)}</p>`).join("")}${n.monster_ids?.length ? `<p>遭遇：${n.monster_ids.map((id) => e(items.find((i) => i.id === id)?.name || id)).join("、")}</p>` : ""}</div>`).join("")}` : ""}<div class="preview-tags">${(model.tags || []).map((t) => `<span class="badge">${e(t)}</span>`).join("")}</div></div><p class="helper" style="margin-top:12px">预览反映当前未保存的表单。实际效果以发布时的服务端校验与运行规则为准。</p>`;
}
function nodeName(id) {
  return model.nodes?.find((n) => n.id === id)?.title || "未连接";
}
function graphWarnings() {
  const nodes = model?.nodes || [],
    byId = new Map(nodes.map((n) => [n.id, n])),
    visited = new Set(),
    todo = [model?.entry_node_id];
  while (todo.length) {
    const id = todo.pop();
    if (visited.has(id) || !byId.has(id)) continue;
    visited.add(id);
    for (const a of byId.get(id).actions || [])
      for (const k of ["next_node_id", "success_node_id", "failure_node_id"])
        if (a[k]) todo.push(a[k]);
  }
  const objectIssues = nodes.flatMap((n) => {
    const objects = n.objects || [],
      ids = objects.map((o) => o.id);
    const invalid =
      objects.length > 20 ||
      new Set(ids).size !== ids.length ||
      objects.some(
        (o) =>
          !/^[a-zA-Z0-9][a-zA-Z0-9_-]{0,63}$/.test(o.id || "") ||
          !o.name?.trim() ||
          o.name.length > 80 ||
          (o.description || "").length > 1000 ||
          !Number.isInteger(o.hp) ||
          o.hp < 1 ||
          o.hp > 100 ||
          !Number.isInteger(o.dc) ||
          o.dc < 5 ||
          o.dc > 25 ||
          (o.tags || []).some((t) => !objectTags[t]) ||
          new Set(o.tags || []).size !== (o.tags || []).length,
      );
    return invalid
      ? [`⚠ ${n.title || n.id}：环境对象 ID、标签或 HP/DC 不合法`]
      : [];
  });
  return objectIssues.concat(
    nodes
      .filter((n) => !visited.has(n.id))
      .map(
        (n) =>
          `⚠ ${n.ending ? "不可达结局" : "不可达节点"}：${n.title || n.id}`,
      ),
  );
}
function bindValidation() {
  document.querySelectorAll("[data-issue]").forEach(
    (button) =>
      (button.onclick = () => {
        const issue = String(issues[Number(button.dataset.issue)] || "");
        if (tab !== "edit") {
          tab = "edit";
          renderDetail();
        }
        let field = issue.match(
          /(?:nodes\.\d+\.)?(?:(?:actions|objects)\.\d+\.)?(?:name|description|id|text|title|entry_node_id|next_node_id|success_node_id|failure_node_id|skill_id|hp|ac|dice|damage_dice|effect|target|uses|bonus|dc)/,
        )?.[0];
        const match = (model.nodes || []).findIndex((n) =>
          issue.includes(`节点 ${n.id}`),
        );
        if (match >= 0) field = `nodes.${match}.title`;
        const target =
          [...document.querySelectorAll("[data-field]")].find(
            (el) => el.dataset.field === field,
          ) || $("#editor");
        target?.scrollIntoView?.({ behavior: "smooth", block: "center" });
        target?.focus?.();
      }),
  );
}
function defaultData(type) {
  const id = `${type}-${Date.now().toString(36)}`;
  const common = {
    id,
    name: `新的${kinds[type].name}`,
    description: "",
    tags: [],
  };
  if (type === "skill")
    return {
      ...common,
      effect: "check",
      ability: "wis",
      dice: "1d20",
      bonus: 0,
      dc: 12,
      uses: null,
      target: "scene",
    };
  if (type === "monster")
    return {
      ...common,
      hp: 12,
      xp: 50,
      ac: 12,
      attack_bonus: 3,
      damage_dice: "1d6",
      damage_bonus: 1,
      initiative_bonus: 1,
    };
  return {
    ...common,
    entry_node_id: "opening",
    skill_ids: [],
    monster_ids: [],
    nodes: [
      {
        id: "opening",
        title: "故事的开端",
        text: "",
        objective: "",
        actions: [
          { id: "continue", label: "踏上旅途", next_node_id: "ending" },
        ],
        monster_ids: [],
        ending: false,
      },
      {
        id: "ending",
        title: "旅途之后",
        text: "",
        objective: "",
        actions: [],
        monster_ids: [],
        ending: true,
      },
    ],
  };
}
function newItem() {
  if (!dirtyConfirm()) return;
  model = defaultData(kind);
  selected = {
    id: null,
    kind,
    revision: 0,
    published_revision: null,
    archived: false,
  };
  dirty = true;
  issues = [];
  valid = null;
  tab = "edit";
  shell();
}
async function openItem(id) {
  if (!dirtyConfirm()) return;
  try {
    selected = admin
      ? extractItem(await api(`/api/studio/items/${encodeURIComponent(id)}`))
      : publicItems.find((i) => i.id === id);
    model = admin ? clone(selected.draft) : null;
    dirty = false;
    issues = [];
    valid = null;
    tab = "edit";
    shell();
  } catch (error) {
    toast(error.message);
  }
}
async function reloadItems() {
  if (admin) {
    const pages = await Promise.all([
      api("/api/studio/items"),
      api("/api/studio/items?archived=true"),
    ]);
    items = pages.flatMap((p) => p.items || []);
  } else {
    const pages = await Promise.all(
      Object.keys(kinds).map((k) => api(`/api/content?kind=${k}`)),
    );
    publicItems = pages.flatMap((p) => p.items || []);
  }
}
async function save() {
  if (busy) return;
  busy = true;
  try {
    const data = selected.id
      ? await api(`/api/studio/items/${encodeURIComponent(selected.id)}`, {
          method: "PUT",
          body: JSON.stringify({
            expected_revision: selected.revision,
            data: model,
          }),
        })
      : await api("/api/studio/items", {
          method: "POST",
          body: JSON.stringify({ kind, data: model }),
        });
    selected = extractItem(data);
    model = clone(selected.draft);
    dirty = false;
    valid = null;
    issues = [];
    await reloadItems();
    toast("草稿已保存，尚未发布。");
  } catch (error) {
    if (error.status === 409)
      toast("内容已被其他窗口修改。请先复制未保存数据，再重新打开最新版本。");
    else toast(error.message);
    issues = error.data?.issues || [error.message];
  } finally {
    busy = false;
    shell();
  }
}
async function validate() {
  if (dirty) {
    toast("请先保存草稿，再校验此版本。");
    return false;
  }
  try {
    const data = await api(
      `/api/studio/items/${encodeURIComponent(selected.id)}/validate`,
      { method: "POST", body: "{}" },
    );
    valid = data.valid;
    issues = data.issues || [];
    warnings = data.warnings || [];
    $("#validation").innerHTML = validationHtml();
    bindValidation();
    return valid;
  } catch (error) {
    toast(error.message);
    return false;
  }
}
async function publish() {
  if (dirty) {
    toast("请先保存草稿，再发布此版本。");
    return;
  }
  if (!(await validate())) return;
  if (
    !window.confirm(
      `发布「${model.name}」的 r${selected.revision}？它将供新创建的冒险使用。`,
    )
  )
    return;
  busy = true;
  try {
    selected = extractItem(
      await api(
        `/api/studio/items/${encodeURIComponent(selected.id)}/publish`,
        {
          method: "POST",
          body: JSON.stringify({ expected_revision: selected.revision }),
        },
      ),
    );
    model = clone(selected.draft);
    await reloadItems();
    toast("此版本已发布。");
  } catch (error) {
    toast(error.message);
    issues = error.data?.issues || [error.message];
  } finally {
    busy = false;
    shell();
  }
}
async function duplicate() {
  if (dirty && !dirtyConfirm()) return;
  try {
    selected = extractItem(
      await api(
        `/api/studio/items/${encodeURIComponent(selected.id)}/duplicate`,
        { method: "POST", body: "{}" },
      ),
    );
    model = clone(selected.draft);
    dirty = false;
    issues = [];
    valid = null;
    await reloadItems();
    shell();
    toast("已创建独立副本草稿。");
  } catch (error) {
    toast(error.message);
  }
}
async function archive() {
  if (dirty) {
    toast("请先保存或放弃当前修改。");
    return;
  }
  if (
    !window.confirm(
      `归档「${selected.name}」？已有冒险保留快照，此内容将从新冒险目录隐藏。`,
    )
  )
    return;
  try {
    selected = extractItem(
      await api(
        `/api/studio/items/${encodeURIComponent(selected.id)}/archive`,
        {
          method: "POST",
          body: JSON.stringify({ expected_revision: selected.revision }),
        },
      ),
    );
    model = clone(selected.draft);
    await reloadItems();
    shell();
    toast("内容已归档。");
  } catch (error) {
    toast(error.message);
  }
}
function download(data, name) {
  const url = URL.createObjectURL(
      new Blob([JSON.stringify(data, null, 2)], { type: "application/json" }),
    ),
    a = document.createElement("a");
  a.href = url;
  a.download = name;
  a.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
async function exportCurrent() {
  if (dirty) {
    toast("导出以已保存草稿为准，请先保存修改。");
    return;
  }
  try {
    const data = await api("/api/studio/export", {
      method: "POST",
      body: JSON.stringify({ ids: [selected.id] }),
    });
    download(data.package || data, `${selected.id}-bundle.json`);
    toast("内容包已导出，不包含管理凭证。");
  } catch (error) {
    toast(error.message);
  }
}
async function loadHistory() {
  try {
    const data = await api(
      `/api/studio/items/${encodeURIComponent(selected.id)}/history`,
    );
    $("#history-list").innerHTML =
      (data.items || [])
        .map(
          (h, i) =>
            `<div class="history-row"><div class="row between"><strong>r${e(h.revision)} · ${e({ create: "创建", update: "保存草稿", publish: "发布", archive: "归档", duplicate: "复制", import: "导入" }[h.action] || h.action)}</strong><button class="small" data-history="${i}">查看内容</button></div><p>${e(h.created_at || "")} ${h.published_revision ? "· 发布 r" + e(h.published_revision) : ""}</p></div>`,
        )
        .join("") || '<p class="helper">暂无版本记录。</p>';
    document.querySelectorAll("[data-history]").forEach(
      (b) =>
        (b.onclick = () =>
          modal(
            "版本内容",
            `<p class="helper">历史记录只读。恢复会创建新的草稿版本，不会更改已发布内容。</p><pre class="json-view">${e(JSON.stringify(data.items[Number(b.dataset.history)].data, null, 2))}</pre>${!selected.archived ? '<button id="restore-version" class="primary">恢复为新草稿</button>' : ""}`,
            (overlay, close) => {
              $("#restore-version", overlay)?.addEventListener(
                "click",
                async () => {
                  if (dirty && !dirtyConfirm()) return;
                  try {
                    const result = await api(
                      `/api/studio/items/${encodeURIComponent(selected.id)}/restore`,
                      {
                        method: "POST",
                        body: JSON.stringify({
                          expected_revision: selected.revision,
                          revision:
                            data.items[Number(b.dataset.history)].revision,
                        }),
                      },
                    );
                    selected = extractItem(result);
                    model = clone(selected.draft);
                    dirty = false;
                    valid = null;
                    issues = [];
                    tab = "edit";
                    await reloadItems();
                    close();
                    shell();
                    toast("历史内容已恢复为新草稿，尚未重新发布。");
                  } catch (error) {
                    toast(error.message);
                  }
                },
              );
            },
          )),
    );
  } catch (error) {
    const list = $("#history-list");
    if (list)
      list.innerHTML = `<p class="studio-error">${e(error.message)}</p>`;
  }
}
function modal(title, body, setup) {
  const previous = document.activeElement,
    overlay = document.createElement("div");
  overlay.className = "modal-backdrop";
  overlay.innerHTML = `<section class="modal" role="dialog" aria-modal="true" aria-labelledby="studio-dialog-title"><div class="row between"><h2 id="studio-dialog-title">${e(title)}</h2><button class="ghost" data-close aria-label="关闭">×</button></div><div style="margin-top:22px">${body}</div></section>`;
  document.body.append(overlay);
  const close = () => {
    overlay.remove();
    previous?.focus();
  };
  overlay.onclick = (event) => {
    if (event.target === overlay || event.target.closest("[data-close]"))
      close();
  };
  overlay.onkeydown = (event) => {
    if (event.key === "Escape") close();
    if (event.key === "Tab") {
      const list = [
          ...overlay.querySelectorAll(
            "button:not(:disabled),input,textarea,select",
          ),
        ],
        first = list[0],
        last = list.at(-1);
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last?.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first?.focus();
      }
    }
  };
  setup?.(overlay, close);
  overlay.querySelector("input,button")?.focus();
}
function authDialog() {
  modal(
    "管理员解锁",
    `<p class="helper">输入部署者设置的 HEXBOUND_ADMIN_TOKEN。凭证仅保存在当前标签页会话中，不会写入导出的内容包。</p>${!writeEnabled ? '<p class="studio-error" style="margin-top:12px">服务器尚未开启内容写入。请先配置 HEXBOUND_ADMIN_TOKEN 并重启服务。</p>' : ""}<form class="form" id="auth-form"><label>管理员凭证<input name="token" type="password" autocomplete="off" required></label><p class="studio-error" id="auth-error"></p><button class="primary" ${writeEnabled ? "" : "disabled"}>解锁内容管理</button></form>`,
    (overlay, close) => {
      $("#auth-form", overlay).onsubmit = async (event) => {
        event.preventDefault();
        const button = $("button.primary", overlay);
        button.disabled = true;
        const candidate = $("[name=token]", overlay).value.trim();
        const previous = token;
        token = candidate;
        try {
          await api("/api/studio/items");
          admin = true;
          sessionStorage.setItem("hexbound-studio-token", token);
          await reloadItems();
          selected = null;
          model = null;
          dirty = false;
          close();
          shell();
        } catch (error) {
          token = previous;
          $("#auth-error", overlay).textContent = error.message;
        } finally {
          button.disabled = false;
        }
      };
    },
  );
}
function logout() {
  if (!dirtyConfirm()) return;
  token = "";
  admin = false;
  sessionStorage.removeItem("hexbound-studio-token");
  items = [];
  selected = null;
  model = null;
  dirty = false;
  reloadItems()
    .then(shell)
    .catch((error) => toast(error.message));
}
function importDialog() {
  modal(
    "导入内容包",
    `<p class="helper">选择 HEXBOUND JSON 内容包。导入结果均为草稿，不会自动发布；同 ID 冲突会拒绝覆盖现有内容。</p><form class="form" id="import-form"><label class="import-file">内容包文件<input name="file" type="file" accept=".json,application/json" required></label><p class="studio-error" id="import-error"></p><button class="primary">校验并导入草稿</button></form>`,
    (overlay, close) => {
      $("#import-form", overlay).onsubmit = async (event) => {
        event.preventDefault();
        const button = $("button.primary", overlay);
        button.disabled = true;
        try {
          const file = $("[name=file]", overlay).files[0];
          if (file.size > 2 * 1024 * 1024)
            throw new Error("内容包请控制在 2 MB 以内");
          const pkg = JSON.parse(await file.text());
          await api("/api/studio/import", {
            method: "POST",
            body: JSON.stringify({ package: pkg, conflict: "reject" }),
          });
          await reloadItems();
          close();
          shell();
          toast("内容包已导入为草稿。请检查并分别发布依赖和剧情。");
        } catch (error) {
          $("#import-error", overlay).textContent = error.message;
        } finally {
          button.disabled = false;
        }
      };
    },
  );
}
function generateDialog() {
  if (!dirtyConfirm()) return;
  modal(
    "灵感助手",
    `<p class="helper">让已配置的 LLM 提供${kinds[kind].name}草稿。生成内容不会自动保存或发布，仍需核对数值与分支。</p><form class="form" id="generate-form"><label>你的构想<textarea name="prompt" maxlength="1500" rows="5" placeholder="描述主题、风格与希望达成的玩法…" required></textarea></label><p class="studio-error" id="generate-error"></p><button class="primary">生成${kinds[kind].name}草稿 ✦</button></form>`,
    (overlay, close) => {
      $("#generate-form", overlay).onsubmit = async (event) => {
        event.preventDefault();
        const button = $("button.primary", overlay);
        button.disabled = true;
        button.textContent = "正在构思，请稍候…";
        try {
          const data = await api("/api/studio/generate", {
            method: "POST",
            body: JSON.stringify({
              kind,
              prompt: $("[name=prompt]", overlay).value,
            }),
          });
          model = data.data;
          selected = {
            id: null,
            kind,
            revision: 0,
            published_revision: null,
            archived: false,
          };
          dirty = true;
          issues = data.issues || [];
          valid = null;
          tab = "edit";
          close();
          shell();
          toast("已生成未保存草稿，请检查字段后保存。");
        } catch (error) {
          $("#generate-error", overlay).textContent = error.message;
        } finally {
          button.disabled = false;
          button.textContent = "重新生成";
        }
      };
    },
  );
}
window.addEventListener("beforeunload", (event) => {
  if (dirty) {
    event.preventDefault();
    event.returnValue = "";
  }
});
async function boot() {
  try {
    const state = await api("/api/studio/status");
    legacyEnabled = !!state.legacy_enabled;
    writeEnabled = legacyEnabled
      ? !!state.legacy_write_enabled
      : !!state.write_enabled;
    try {
      const identity = await api("/api/auth/me");
      account = identity.user;
      csrfToken = identity.csrf_token;
      admin =
        !account.must_change_password &&
        ["creator", "admin"].includes(account.role);
    } catch (error) {
      if (error.status !== 401) throw error;
      account = null;
    }
    if (!legacyEnabled) {
      token = "";
      sessionStorage.removeItem("hexbound-studio-token");
    }
    if (!account && legacyEnabled && token && writeEnabled) {
      try {
        await api("/api/studio/items");
        admin = true;
      } catch {
        token = "";
        sessionStorage.removeItem("hexbound-studio-token");
      }
    }
    await reloadItems();
    shell();
  } catch (error) {
    root.innerHTML = `<div class="loading"><div>内容工坊暂时无法连接</div><span>${e(error.message)}</span><button id="retry-studio">重新连接</button><a href="/">返回冒险桌</a></div>`;
    $("#retry-studio").onclick = boot;
  }
}
boot();

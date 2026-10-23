const root = document.querySelector("#account");
const $ = (selector, context = document) => context.querySelector(selector);
const escapeHTML = (value) =>
  String(value ?? "").replace(
    /[&<>"']/g,
    (char) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[
        char
      ],
  );
const roles = { player: "玩家", creator: "创作者", admin: "管理员" };
const roleDescriptions = {
  player: "加入冒险、管理自己的角色与游戏记录。",
  creator: "拥有玩家权限，并可编辑与发布内容工坊素材。",
  admin: "拥有创作者权限，并可管理账号、角色权限与审计记录。",
};
let user = null;
let csrf = "";
let registrationEnabled = true;
let authTab =
  new URLSearchParams(location.search).get("mode") === "register"
    ? "register"
    : "login";
let adminTab = "users";
let page = 1;
let total = 0;
const pageSize = 20;
let users = [];
let audit = [];
let search = "";
let roleFilter = "";
let statusFilter = "";
let listRequest = 0;
let toastTimer;
const brand =
  '<span class="brand"><span class="symbol">⬡</span><span>HEXBOUND</span></span>';
const e = escapeHTML;

function continueToRequestedPage() {
  if (!user || user.must_change_password) return;
  const requested = new URLSearchParams(location.search).get("next");
  if (
    !requested ||
    !requested.startsWith("/") ||
    requested.startsWith("//") ||
    requested.includes("\\")
  )
    return;
  try {
    const target = new URL(requested, location.origin);
    if (
      target.origin !== location.origin ||
      target.pathname === "/account.html"
    )
      return;
    location.assign(target.pathname + target.search + target.hash);
  } catch {
    /* Invalid return paths never leave the account center. */
  }
}

function toast(message) {
  const target = $("#account-toast");
  target.textContent = message;
  target.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => {
    target.hidden = true;
  }, 6000);
}

async function api(path, options = {}) {
  const method = options.method || "GET";
  const response = await fetch(path, {
    ...options,
    credentials: "same-origin",
    headers: {
      "Content-Type": "application/json",
      ...(!["GET", "HEAD"].includes(method) && csrf
        ? { "X-CSRF-Token": csrf }
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
    const detail =
      typeof data.detail === "string"
        ? data.detail
        : Array.isArray(data.detail)
          ? data.detail
              .map((item) => `${item.loc?.slice(1).join(".")}: ${item.msg}`)
              .join("；")
          : `操作未完成 (${response.status})`;
    const error = new Error(detail);
    error.status = response.status;
    throw error;
  }
  return data;
}

function acceptSession(data) {
  user = data.user;
  csrf = data.csrf_token || "";
}

function clearSession() {
  user = null;
  csrf = "";
  users = [];
  audit = [];
  page = 1;
  total = 0;
  listRequest++;
  sessionStorage.removeItem("hexbound-session");
}

function dateLabel(value) {
  if (!value) return "—";
  const date = new Date(value);
  return Number.isNaN(date.valueOf())
    ? String(value)
    : date.toLocaleString("zh-CN", { hour12: false });
}

function header() {
  return `<header class="account-header"><a href="/" aria-label="返回冒险桌">${brand}</a><nav class="account-nav" aria-label="应用导航"><a href="/">冒险桌 ↗</a><a href="/studio.html">内容工坊 ↗</a><span class="chip">${user ? e(roles[user.role] || user.role) : "旅人档案"}</span></nav></header>`;
}

function render() {
  if (!user) renderAuth();
  else renderAccount();
}

function renderAuth() {
  const register = authTab === "register" && registrationEnabled;
  root.innerHTML = `<div class="account-shell">${header()}<main class="auth-layout"><section class="auth-intro"><div class="eyebrow">YOUR NAME. YOUR STORY.</div><h1>留下名字，<br>让故事<em>记住你。</em></h1><p>一个属于你的旅人档案。与同伴继续未完的冒险，或成为创作者，写下下一个世界。</p><div class="auth-seal" aria-hidden="true"><span>H</span></div></section><section class="auth-panel"><div class="account-tabs" role="tablist" aria-label="账号入口"><button id="login-tab" role="tab" aria-selected="${!register}" class="${register ? "" : "active"}">登录</button><button id="register-tab" role="tab" aria-selected="${register}" class="${register ? "active" : ""}" ${registrationEnabled ? "" : "disabled"}>注册新账号</button></div>${!registrationEnabled ? '<p class="account-notice">当前站点已关闭注册，请联系管理员获取账号。</p>' : ""}<form id="auth-form" class="form"><label>用户名<input name="username" autocomplete="username" minlength="3" maxlength="32" pattern="[A-Za-z0-9][A-Za-z0-9_.-]{2,31}" required placeholder="你的登录用户名"></label>${register ? '<label>显示名称<input name="display_name" autocomplete="nickname" maxlength="40" placeholder="同伴如何称呼你（可选）"></label>' : ""}<label>密码<input name="password" type="password" autocomplete="${register ? "new-password" : "current-password"}" minlength="10" maxlength="128" required placeholder="${register ? "至少 10 个字符" : "输入密码"}"></label>${register ? '<label>确认密码<input name="confirm_password" type="password" autocomplete="new-password" minlength="10" maxlength="128" required placeholder="再次输入密码"></label><p class="account-helper">用户名为 3–32 位英文字母、数字、下划线、点或连字符，以字母或数字开头。注册后默认为玩家。</p>' : ""}<p id="auth-error" class="account-form-error" role="alert"></p><button type="submit" class="primary">${register ? "创建旅人档案 ↗" : "登录并继续 ↗"}</button><p class="account-helper">会话由受保护的浏览器 Cookie 保存。密码不会保存在本地存储中。</p></form></section></main></div>`;
  $("#login-tab").onclick = () => {
    authTab = "login";
    renderAuth();
  };
  $("#register-tab").onclick = () => {
    authTab = "register";
    renderAuth();
  };
  $("#auth-form").onsubmit = async (event) => {
    event.preventDefault();
    const form = event.currentTarget;
    const values = Object.fromEntries(new FormData(form));
    const errorBox = $("#auth-error");
    errorBox.textContent = "";
    if (register && values.password !== values.confirm_password) {
      errorBox.textContent = "两次输入的密码不一致。";
      return;
    }
    const button = $("button[type=submit]", form);
    button.disabled = true;
    button.textContent = register ? "正在创建…" : "正在登录…";
    try {
      const payload = {
        username: values.username.trim(),
        password: values.password,
      };
      if (register && values.display_name.trim())
        payload.display_name = values.display_name.trim();
      acceptSession(
        await api(register ? "/api/auth/register" : "/api/auth/login", {
          method: "POST",
          body: JSON.stringify(payload),
        }),
      );
      form.reset();
      render();
      toast(register ? "旅人档案已创建，欢迎入席。" : "登录成功。");
      continueToRequestedPage();
    } catch (error) {
      errorBox.textContent = error.message;
      button.disabled = false;
      button.textContent = register ? "创建旅人档案 ↗" : "登录并继续 ↗";
    }
  };
}

function profileHtml() {
  return `<aside class="profile-panel"><div class="profile-avatar" aria-hidden="true">${e((user.display_name || user.username || "?")[0])}</div><h2>${e(user.display_name || user.username)}</h2><div class="username">@${e(user.username)}</div><div style="margin-top:12px"><span class="account-badge">${e(roles[user.role])}</span></div><div class="profile-meta">加入时间<br>${e(dateLabel(user.created_at))}<br><span style="display:block;margin-top:10px">${e(roleDescriptions[user.role] || "")}</span></div><div class="profile-buttons"><button id="change-password">修改密码</button><button id="logout">退出当前设备</button><button id="logout-all" class="danger-button">退出全部设备</button></div></aside>`;
}

function renderAccount() {
  const forced = !!user.must_change_password;
  root.innerHTML = `<div class="account-shell">${header()}<main class="account-content"><div class="account-title"><div><div class="eyebrow">THE TRAVELER'S RECORD</div><h1>${user.role === "admin" ? "旅人档案与账号管理" : "你的旅人档案"}</h1><p>每一个名字，都是故事的一部分。</p></div><span class="chip"><span class="dot"></span>已登录</span></div>${forced ? '<div class="account-notice" role="alert">你的密码已被管理员重置。为保护账号，请先修改密码，再继续访问冒险与内容管理。</div>' : ""}<div class="account-layout">${profileHtml()}${user.role === "admin" && !forced ? adminHtml() : `<section class="security-panel"><div class="eyebrow">${forced ? "ACTION REQUIRED" : "ACCOUNT & ACCESS"}</div><h2 style="margin-top:14px">${forced ? "为这段旅程设置新密码" : "安心出发，随时归来。"}</h2><p>${forced ? "设置仅由你知晓的新密码。成功后，其他设备的旧会话会失效。" : "登录状态由服务器管理。你可以修改密码，或结束所有设备上的会话。"}</p>${forced ? '<button id="forced-password" class="primary" style="margin-top:24px">现在修改密码 ↗</button>' : `<div class="security-row"><h3>${e(roles[user.role])}权限</h3><p>${e(roleDescriptions[user.role])}</p></div><div class="security-row"><h3>继续冒险</h3><p>返回冒险桌，与同伴一起书写下一页。</p><a href="/" class="inline-link">前往冒险桌 ↗</a></div>${user.role === "creator" ? '<div class="security-row"><h3>创造你的世界</h3><p>编辑技能卡、怪兽与分支剧情，发布可供冒险使用的内容。</p><a href="/studio.html" class="inline-link">打开内容工坊 ↗</a></div>' : ""}`}</section>`}</div></main></div>`;
  $("#change-password").onclick = changePasswordDialog;
  $("#forced-password")?.addEventListener("click", changePasswordDialog);
  $("#logout").onclick = () => logout(false);
  $("#logout-all").onclick = () => logout(true);
  if (user.role === "admin" && !forced) {
    document.querySelectorAll("[data-admin-tab]").forEach((button) => {
      button.onclick = () => {
        adminTab = button.dataset.adminTab;
        page = 1;
        renderAccount();
      };
    });
    loadAdmin();
  }
}

function adminHtml() {
  return `<section class="admin-panel"><nav class="admin-top" aria-label="管理功能"><button data-admin-tab="users" class="${adminTab === "users" ? "active" : ""}">账号管理</button><button data-admin-tab="audit" class="${adminTab === "audit" ? "active" : ""}">操作审计</button></nav><div class="admin-body" id="admin-body"><p class="account-helper" role="status">正在读取${adminTab === "users" ? "账号" : "审计"}记录…</p></div></section>`;
}

async function loadAdmin() {
  const requestId = ++listRequest;
  const mode = adminTab;
  const body = $("#admin-body");
  if (body) {
    body.setAttribute("aria-busy", "true");
    body.querySelectorAll("button").forEach((button) => {
      button.disabled = true;
    });
  }
  try {
    const params = new URLSearchParams({
      page: String(page),
      page_size: String(pageSize),
    });
    if (mode === "users") {
      if (search) params.set("q", search);
      if (roleFilter) params.set("role", roleFilter);
      if (statusFilter) params.set("disabled", statusFilter);
    }
    const data = await api(
      `/api/admin/${mode === "users" ? "users" : "audit"}?${params}`,
    );
    if (requestId !== listRequest || !user || !$("#admin-body")) return;
    total = data.total;
    page = data.page;
    if (mode === "users") users = data.items || [];
    else audit = data.items || [];
    renderAdminBody();
  } catch (error) {
    if (requestId !== listRequest) return;
    if (error.status === 401) {
      clearSession();
      render();
      toast("会话已失效，请重新登录。");
      return;
    }
    const body = $("#admin-body");
    if (body) {
      body.innerHTML = `<p class="account-form-error">${e(error.message)}</p><button id="retry-admin" class="small" style="margin-top:14px">重新读取</button>`;
      $("#retry-admin").onclick = loadAdmin;
    }
  }
}

function renderAdminBody() {
  const isUsers = adminTab === "users";
  $("#admin-body").setAttribute("aria-busy", "false");
  $("#admin-body").innerHTML = `${
    isUsers
      ? `<form class="admin-filters" id="user-filter"><input name="q" aria-label="搜索用户名或名称" placeholder="搜索用户名、显示名称…" maxlength="80" value="${e(search)}"><select name="role" aria-label="筛选角色"><option value="">全部角色</option>${Object.entries(
          roles,
        )
          .map(
            ([id, name]) =>
              `<option value="${id}" ${roleFilter === id ? "selected" : ""}>${name}</option>`,
          )
          .join(
            "",
          )}</select><select name="disabled" aria-label="筛选账号状态"><option value="">全部状态</option><option value="false" ${statusFilter === "false" ? "selected" : ""}>已启用</option><option value="true" ${statusFilter === "true" ? "selected" : ""}>已禁用</option></select><button type="submit">查询</button></form><div class="users-table-wrap"><table class="users-table"><thead><tr><th scope="col">旅人</th><th scope="col">角色</th><th scope="col">状态</th><th scope="col">操作</th></tr></thead><tbody>${users.map((account) => `<tr><td><strong>${e(account.display_name || account.username)}${account.id === user.id ? " · 你" : ""}</strong><small>@${e(account.username)}</small></td><td><span class="account-badge">${e(roles[account.role] || account.role)}</span></td><td><span class="account-badge ${account.disabled ? "disabled" : "active"}">${account.disabled ? "已禁用" : "已启用"}</span>${account.must_change_password ? "<small>下次登录须改密</small>" : ""}</td><td><button data-manage="${e(account.id)}">管理 ↗</button></td></tr>`).join("")}</tbody></table>${!users.length ? '<div class="admin-empty">没有找到符合条件的账号。</div>' : ""}</div>`
      : `<p class="account-helper" style="margin-bottom:14px">账号与权限变更的服务端记录。审计不展示密码和会话凭证。</p>${audit.map((item) => `<article class="audit-item"><div class="audit-heading"><strong>${e(auditLabel(item.action))}</strong><small>${e(dateLabel(item.created_at))}</small></div><p>${e(item.actor_username || "系统")} ${item.target_username ? `→ ${e(item.target_username)}` : ""}</p>${item.details && Object.keys(item.details).length ? `<details><summary>变更详情</summary><pre>${e(JSON.stringify(item.details, null, 2))}</pre></details>` : ""}</article>`).join("") || '<div class="admin-empty">暂无操作记录。</div>'}`
  }${paginationHtml()}`;
  if (isUsers) {
    $("#user-filter").onsubmit = (event) => {
      event.preventDefault();
      const values = Object.fromEntries(new FormData(event.currentTarget));
      search = values.q.trim();
      roleFilter = values.role;
      statusFilter = values.disabled;
      page = 1;
      loadAdmin();
    };
    document.querySelectorAll("[data-manage]").forEach((button) => {
      button.onclick = () =>
        manageDialog(
          users.find((account) => account.id === button.dataset.manage),
        );
    });
  }
  $("#previous-page").onclick = () => {
    page--;
    loadAdmin();
  };
  $("#next-page").onclick = () => {
    page++;
    loadAdmin();
  };
}

function paginationHtml() {
  const pages = Math.max(1, Math.ceil(total / pageSize));
  return `<div class="pagination"><span>共 ${total} 条 · 第 ${page} / ${pages} 页</span><div class="row"><button id="previous-page" ${page <= 1 ? "disabled" : ""}>← 上一页</button><button id="next-page" ${page >= pages ? "disabled" : ""}>下一页 →</button></div></div>`;
}

function auditLabel(action) {
  return (
    {
      register: "注册账号",
      login: "账号登录",
      login_failed: "登录失败",
      logout: "退出当前设备",
      logout_all: "退出全部设备",
      change_password: "修改密码",
      reset_password: "管理员重置密码",
      update_user: "更新账号权限或状态",
      update_account: "更新账号权限或状态",
      bootstrap_admin: "初始化管理员",
      role_changed: "调整角色权限",
      user_disabled: "禁用账号",
      user_enabled: "启用账号",
    }[action] || action
  );
}

function modal(title, body, setup) {
  const previous = document.activeElement;
  const overlay = document.createElement("div");
  overlay.className = "modal-backdrop";
  overlay.innerHTML = `<section class="modal" role="dialog" aria-modal="true" aria-labelledby="account-dialog-title"><div class="row between"><h2 id="account-dialog-title">${e(title)}</h2><button class="ghost" data-close aria-label="关闭">×</button></div>${body}</section>`;
  document.body.append(overlay);
  const close = () => {
    overlay.querySelectorAll("input[type=password]").forEach((input) => {
      input.value = "";
    });
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
      const controls = [
        ...overlay.querySelectorAll(
          "button:not(:disabled),input:not(:disabled),select:not(:disabled),textarea:not(:disabled)",
        ),
      ];
      const first = controls[0],
        last = controls.at(-1);
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last?.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first?.focus();
      }
    }
  };
  setup(overlay, close);
  overlay.querySelector("input,button")?.focus();
}

function changePasswordDialog() {
  modal(
    "修改密码",
    `<p class="account-helper" style="margin-top:18px">修改后，其他设备的旧会话会失效，当前设备将获得新的登录会话。</p><form id="password-form" class="form"><label>当前密码<input type="password" name="current_password" autocomplete="current-password" minlength="10" maxlength="128" required></label><label>新密码<input type="password" name="new_password" autocomplete="new-password" minlength="10" maxlength="128" required></label><label>再次输入新密码<input type="password" name="confirm_password" autocomplete="new-password" minlength="10" maxlength="128" required></label><p id="password-error" class="account-form-error" role="alert"></p><button type="submit" class="primary">修改密码并更新会话</button></form>`,
    (overlay, close) => {
      $("#password-form", overlay).onsubmit = async (event) => {
        event.preventDefault();
        const form = event.currentTarget,
          values = Object.fromEntries(new FormData(form));
        const errorBox = $("#password-error", overlay);
        errorBox.textContent = "";
        if (values.new_password !== values.confirm_password) {
          errorBox.textContent = "两次输入的新密码不一致。";
          return;
        }
        const button = $("button[type=submit]", form);
        button.disabled = true;
        try {
          acceptSession(
            await api("/api/auth/change-password", {
              method: "POST",
              body: JSON.stringify({
                current_password: values.current_password,
                new_password: values.new_password,
              }),
            }),
          );
          form.reset();
          close();
          render();
          toast("密码已更新，其他旧会话已退出。");
          continueToRequestedPage();
        } catch (error) {
          errorBox.textContent = error.message;
          button.disabled = false;
        }
      };
    },
  );
}

async function logout(all) {
  if (
    all &&
    !window.confirm(
      "退出所有设备上的账号会话，包括当前设备？游戏与内容存档不会删除。",
    )
  )
    return;
  const button = $(all ? "#logout-all" : "#logout");
  if (button) button.disabled = true;
  try {
    await api(all ? "/api/auth/logout-all" : "/api/auth/logout", {
      method: "POST",
      body: "{}",
    });
    clearSession();
    authTab = "login";
    render();
    toast(all ? "已退出全部设备。" : "已退出当前设备。");
  } catch (error) {
    if (error.status === 401) {
      clearSession();
      render();
    } else {
      toast(error.message);
      if (button) button.disabled = false;
    }
  }
}

function manageDialog(account) {
  if (!account) return;
  const isSelf = account.id === user.id;
  modal(
    "管理旅人账号",
    `<p class="account-modal-identity"><strong>${e(account.display_name || account.username)}</strong> · @${e(account.username)}${isSelf ? " · 当前账号" : ""}</p><p class="account-helper">角色调整、禁用和密码重置会撤销该账号的已有会话。系统会保留至少一名有效管理员。</p><form id="manage-form" class="form"><label>账号角色<select name="role">${Object.entries(
      roles,
    )
      .map(
        ([id, name]) =>
          `<option value="${id}" ${account.role === id ? "selected" : ""}>${name}</option>`,
      )
      .join(
        "",
      )}</select></label><p id="role-description" class="account-helper">${e(roleDescriptions[account.role])}</p><label style="flex-direction:row;align-items:center;gap:10px"><input type="checkbox" name="disabled" style="width:auto" ${account.disabled ? "checked" : ""}>禁用此账号</label><p id="manage-error" class="account-form-error" role="alert"></p><button type="submit" class="primary">保存角色与状态</button></form><section class="manage-section"><h3>重置密码</h3><p class="account-helper">设置临时密码后，该旅人下次登录必须自行修改。请通过可信渠道告知对方，不要将密码写入公开消息。</p><form id="reset-form" class="form"><label>新的临时密码<input type="password" name="new_password" autocomplete="new-password" minlength="10" maxlength="128" required></label><label>确认临时密码<input type="password" name="confirm_password" autocomplete="new-password" minlength="10" maxlength="128" required></label><p id="reset-error" class="account-form-error" role="alert"></p><button type="submit" class="danger-button">重置密码并结束该账号所有会话</button></form></section>`,
    (overlay, close) => {
      $("[name=role]", overlay).onchange = (event) => {
        $("#role-description", overlay).textContent =
          roleDescriptions[event.target.value];
      };
      $("#manage-form", overlay).onsubmit = async (event) => {
        event.preventDefault();
        const role = $("[name=role]", overlay).value;
        const disabled = $("[name=disabled]", overlay).checked;
        const button = $("button[type=submit]", event.currentTarget);
        $("#manage-error", overlay).textContent = "";
        if (role === account.role && disabled === account.disabled) {
          $("#manage-error", overlay).textContent = "角色和状态没有变化。";
          return;
        }
        if (
          !window.confirm(
            `确认将 @${account.username} 设为${roles[role]}，${disabled ? "禁用" : "启用"}账号？该账号的已有会话会失效。`,
          )
        )
          return;
        button.disabled = true;
        try {
          await api(`/api/admin/users/${encodeURIComponent(account.id)}`, {
            method: "PATCH",
            body: JSON.stringify({
              role,
              disabled,
              expected_version: account.version,
            }),
          });
          close();
          if (isSelf) await reloadIdentity();
          else await loadAdmin();
          toast("账号权限与状态已更新。");
        } catch (error) {
          $("#manage-error", overlay).textContent =
            error.status === 409
              ? `${error.message} 请关闭窗口并重新查询最新账号。`
              : error.message;
          button.disabled = false;
        }
      };
      $("#reset-form", overlay).onsubmit = async (event) => {
        event.preventDefault();
        const form = event.currentTarget,
          values = Object.fromEntries(new FormData(form));
        const errorBox = $("#reset-error", overlay);
        errorBox.textContent = "";
        if (values.new_password !== values.confirm_password) {
          errorBox.textContent = "两次输入的临时密码不一致。";
          return;
        }
        if (
          !window.confirm(
            `确认重置 @${account.username} 的密码并撤销全部会话？`,
          )
        )
          return;
        const button = $("button[type=submit]", form);
        button.disabled = true;
        try {
          await api(
            `/api/admin/users/${encodeURIComponent(account.id)}/reset-password`,
            {
              method: "POST",
              body: JSON.stringify({
                new_password: values.new_password,
                expected_version: account.version,
              }),
            },
          );
          form.reset();
          close();
          if (isSelf) await reloadIdentity();
          else await loadAdmin();
          toast("临时密码已设置，该旅人下次登录必须修改密码。");
        } catch (error) {
          errorBox.textContent = error.message;
          button.disabled = false;
        }
      };
    },
  );
}

async function reloadIdentity() {
  try {
    acceptSession(await api("/api/auth/me"));
  } catch (error) {
    if (error.status === 401) clearSession();
    else throw error;
  }
  render();
}

async function boot() {
  try {
    const status = await api("/api/auth/status");
    registrationEnabled = !!status.registration_enabled;
    await reloadIdentity();
    continueToRequestedPage();
  } catch (error) {
    root.innerHTML = `<div class="loading"><div>旅人档案暂时无法连接</div><span>${e(error.message)}</span><button id="retry-account">重新连接</button><a href="/">返回冒险桌</a></div>`;
    $("#retry-account").onclick = boot;
  }
}

boot();

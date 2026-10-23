/* Stable, keyed journal DOM shared by exploration and combat renders. */
(function (global) {
  'use strict';
  const logs = new Map();
  const nearBottom = (node) => node.scrollHeight - node.clientHeight - node.scrollTop <= 48;
  function capture(key) {
    const state = logs.get(key);
    if (!state || !state.node.isConnected || !state.node.clientHeight) return;
    state.follow = nearBottom(state.node);
    state.top = state.node.scrollTop;
    const top = state.node.getBoundingClientRect().top;
    const row = [...state.node.querySelectorAll('[data-event-id]')].find(n => n.getBoundingClientRect().bottom > top);
    state.anchor = row ? { id: row.dataset.eventId, offset: row.getBoundingClientRect().top - top } : null;
  }
  function mount({ key, placeholder, events = [], renderEvent, prefixHtml = '', emptyHtml = '' }) {
    if (!placeholder) return null;
    let s = logs.get(key);
    if (!s) {
      const node = placeholder.cloneNode(false);
      node.style.overflowAnchor = 'none';
      const prefix = document.createElement('div');
      prefix.className = 'log-prefix';
      const empty = document.createElement('div');
      empty.className = 'log-empty';
      const jump = document.createElement('button');
      jump.type = 'button';
      jump.className = 'log-new-events small';
      jump.hidden = true;
      jump.setAttribute('aria-label', '跳转到最新日志');
      s = { node, prefix, empty, jump, records: new Map(), follow: true, top: 0, unread: 0, max: -Infinity, initialized: false, generation: 0 };
      node.append(prefix, empty);
      jump.onclick = () => { s.follow = true; s.unread = 0; jump.hidden = true; node.scrollTop = Math.max(0, node.scrollHeight - node.clientHeight); };
      node.addEventListener('scroll', () => {
        if (!node.isConnected || !node.clientHeight) return;
        s.generation++;
        s.follow = nearBottom(node);
        if (s.follow) { s.unread = 0; jump.hidden = true; }
      }, { passive: true });
      logs.set(key, s);
    }
    // Carry current accessibility labels without replacing the scrolling surface.
    for (const attr of ['id', 'class', 'role', 'aria-label']) {
      if (placeholder.hasAttribute(attr)) s.node.setAttribute(attr, placeholder.getAttribute(attr));
    }
    placeholder.replaceWith(s.node);
    s.node.after(s.jump);
    if (s.prefix.innerHTML !== prefixHtml) s.prefix.innerHTML = prefixHtml;
    s.prefix.hidden = !prefixHtml;
    let fresh = 0;
    for (const event of events) {
      const id = event.id ?? event.seq;
      if (id == null) continue;
      const keyId = String(id), html = renderEvent(event);
      let entry = s.records.get(keyId);
      if (!entry) {
        const template = document.createElement('template');
        template.innerHTML = html;
        const row = template.content.firstElementChild || document.createElement('article');
        row.dataset.eventId = keyId;
        entry = { row, html, id: Number(id) };
        s.records.set(keyId, entry);
        if (s.initialized && Number(id) > s.max) fresh++;
      } else if (entry.html !== html) {
        // Preserve the event root and expanded dice receipts when controls change.
        const opened = [...entry.row.querySelectorAll('details')].map(n => n.open);
        const template = document.createElement('template');
        template.innerHTML = html;
        const replacement = template.content.firstElementChild;
        if (replacement) {
          entry.row.className = replacement.className;
          entry.row.innerHTML = replacement.innerHTML;
          entry.row.querySelectorAll('details').forEach((n, i) => { n.open = !!opened[i]; });
        }
        entry.html = html;
      }
    }
    const ordered = [...s.records.values()].sort((a, b) => a.id - b.id);
    let previous = s.prefix;
    for (const entry of ordered) {
      if (previous.nextSibling !== entry.row) previous.after(entry.row);
      previous = entry.row;
    }
    if (previous.nextSibling !== s.empty) previous.after(s.empty);
    s.empty.hidden = !!ordered.length;
    if (!ordered.length && s.empty.innerHTML !== emptyHtml) s.empty.innerHTML = emptyHtml;
    s.max = ordered.length ? ordered[ordered.length - 1].id : -Infinity;
    s.initialized = true;
    if (s.follow) {
      s.unread = 0;
      s.node.scrollTop = Math.max(0, s.node.scrollHeight - s.node.clientHeight);
      const generation = s.generation;
      global.requestAnimationFrame?.(() => {
        if (s.node.isConnected && s.follow && generation === s.generation)
          s.node.scrollTop = Math.max(0, s.node.scrollHeight - s.node.clientHeight);
      });
    } else {
      s.unread += fresh;
      const anchor = s.anchor && s.records.get(s.anchor.id)?.row;
      if (anchor) {
        s.node.scrollTop += anchor.getBoundingClientRect().top - s.node.getBoundingClientRect().top - s.anchor.offset;
      } else s.node.scrollTop = s.top;
    }
    s.jump.hidden = s.unread === 0 || s.follow;
    s.jump.textContent = `${s.unread} 条新记录 · 跳到最新 ↓`;
    return s.node;
  }
  function clear() { for (const s of logs.values()) { s.node.remove(); s.jump.remove(); } logs.clear(); }
  global.HexBoundLiveLog = { capture, mount, clear };
})(window);

/* ═══════════════════════════════════════════════════════════════
   协作消息（IM）前端模块 · 2026-10-29
   · 现场作业台与二线控制台共用同一份实现（两页结构不同，靠 ID 约定）
   · 与 AI 对话完全独立：AI 在各自面板，人聊只在这里
   · 不经过桥接器：纯 浏览器 ↔ 服务器
   必需 DOM：
     #imMsgs      消息列表
     #imText      输入框（textarea）
     #imSend      发送按钮
     #imReadonly  归档提示（可选）
     #imFilesMask / #imFilesPanel / #imFilesClose  （可选，文件面板）
     #filesCount  文件数（可选，与既有 room_files 代码共用）
   可选徽标：window.IM_BADGE = ['#tabBadgeField', ...]
   ═══════════════════════════════════════════════════════════════ */
(function () {
  const $ = s => document.querySelector(s);
  const IMC = window.IM_CFG || {};
  const POLL_MS = IMC.poll || 2500;
  const S = { msgs: [], lastId: 0, closed: false, timer: null, busy: false, me: '', role: '', started: false };

  function room() {
    try { return (window.NP && NP.state && NP.state.room && NP.state.room.code) || ''; } catch (e) { return ''; }
  }
  function esc(s) {
    return String(s == null ? '' : s).replace(/&/g, '&amp;').replace(/</g, '&lt;')
      .replace(/>/g, '&gt;').replace(/"/g, '&quot;');
  }
  function hhmm(ts) {
    if (!ts) return '';
    const m = String(ts).match(/(\d{2}):(\d{2})/);
    if (m) return m[1] + ':' + m[2];
    const d = new Date(ts);
    return isNaN(d) ? '' : String(d.getHours()).padStart(2, '0') + ':' + String(d.getMinutes()).padStart(2, '0');
  }
  function fsize(n) {
    n = Number(n || 0);
    if (n >= 1048576) return (n / 1048576).toFixed(1) + ' MB';
    if (n >= 1024) return Math.round(n / 1024) + ' KB';
    return n + ' B';
  }
  function roleName(r) {
    return ({ field: '渠道工程师', cc: 'CC 工程师', expert: '二线工程师', admin: '管理员' })[r] || (r || '');
  }

  /* ── 渲染 ───────────────────────────────────────────── */
  function bubble(m) {
    if (m.kind === 'system') {
      return '<div class="im-sys"><span>' + esc(m.text || '') + '</span></div>';
    }
    const mine = !!m.mine;
    const who = mine ? '我' : (m.sender || '') + ' · ' + roleName(m.sender_role);
    let body = '';
    if (m.recalled) {
      body = '<div class="im-recalled">该消息已撤回</div>';
    } else {
      if (m.kind === 'image' && m.file) {
        body += '<a class="im-img" href="' + esc(m.file.url) + '" target="_blank" rel="noopener">' +
          '<img src="' + esc(m.file.url) + '" alt="' + esc(m.file.filename) + '"></a>';
      } else if (m.file) {
        body += '<a class="im-file" href="' + esc(m.file.url) + '" target="_blank" rel="noopener" download>' +
          '<span class="im-file-ic">📄</span><span class="im-file-name">' + esc(m.file.filename) +
          '</span><span class="im-file-sz">' + fsize(m.file.size) + '</span></a>';
      }
      if (m.text) body += '<div class="im-text">' + esc(m.text).replace(/\n/g, '<br>') + '</div>';
    }
    const canRecall = mine && !m.recalled && !S.closed;
    return '<div class="im-row' + (mine ? ' mine' : '') + '" data-id="' + m.id + '">' +
      '<div class="im-meta">' + esc(who) + ' <span class="im-t">' + hhmm(m.at) + '</span>' +
      (canRecall ? ' <button class="im-recall" data-id="' + m.id + '" title="2 分钟内可撤回">撤回</button>' : '') +
      '</div><div class="im-bubble">' + body + '</div></div>';
  }

  function paint() {
    const box = $('#imMsgs');
    if (!box) return;
    if (!S.msgs.length) {
      box.innerHTML = '<div class="im-empty">还没有消息。现场与二线的对话都在这里，<br>' +
        '附上截图或日志包会更清楚（客户机不用开机也能聊）。</div>';
      return;
    }
    const nearBottom = box.scrollHeight - box.scrollTop - box.clientHeight < 80;
    box.innerHTML = S.msgs.map(bubble).join('');
    box.querySelectorAll('.im-recall').forEach(b => b.addEventListener('click', () => recall(b.dataset.id)));
    if (nearBottom) box.scrollTop = box.scrollHeight;
  }

  function setUnread(n) {
    (window.IM_BADGE || []).forEach(sel => {
      const el = $(sel);
      if (!el) return;
      el.textContent = n > 0 ? String(n) : '';
      el.classList.toggle('hidden', !(n > 0));
    });
  }

  /* ── 取数 ───────────────────────────────────────────── */
  function api(path, body) {
    const opt = body === undefined
      ? { credentials: 'same-origin' }
      : { method: 'POST', credentials: 'same-origin', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) };
    return fetch(path, opt).then(r => r.json().then(j => {
      if (!r.ok) { const e = new Error(j.error || ('HTTP ' + r.status)); throw e; }
      return j;
    }));
  }

  function merge(list) {
    const seen = new Set(S.msgs.map(m => m.id));
    let added = 0;
    list.forEach(m => {
      const i = S.msgs.findIndex(x => x.id === m.id);
      if (i >= 0) { S.msgs[i] = m; return; }
      if (!seen.has(m.id)) { S.msgs.push(m); added++; }
    });
    S.msgs.sort((a, b) => a.id - b.id);
    if (S.msgs.length) S.lastId = S.msgs[S.msgs.length - 1].id;
    return added;
  }

  function loadHistory() {
    const rc = room();
    if (!rc) return Promise.resolve();
    return api('/api/room/im?room_code=' + encodeURIComponent(rc) + '&limit=40').then(js => {
      S.msgs = [];
      S.closed = !!js.closed;
      merge(js.messages || []);
      applyClosed();
      paint();
      return markRead();
    }).catch(() => { });
  }

  function poll() {
    const rc = room();
    if (!rc || S.busy) return;
    S.busy = true;
    api('/api/room/im?room_code=' + encodeURIComponent(rc) + '&after_id=' + S.lastId + '&limit=30')
      .then(js => {
        const added = merge(js.messages || []);
        S.closed = !!js.closed;
        applyClosed();
        if (added) {
          paint();
          const last = S.msgs[S.msgs.length - 1];
          const paneVisible = (IMC.pane ? !$(IMC.pane).classList.contains('hidden') : true);
          if (last && !last.mine && !paneVisible && window.NP && NP.toast) {
            try { NP.toast('协作消息：' + (last.sender || '') + ' 发来一条新消息', 'ok'); } catch (e) { }
          }
        }
      })
      .catch(() => { })
      .finally(() => { S.busy = false; });
    api('/api/room/im/unread?room_code=' + encodeURIComponent(rc)).then(js => {
      const n = js.unread || 0;
      const pv = (IMC.pane ? !$(IMC.pane).classList.contains('hidden') : true);
      if (pv && n > 0) { markRead(); } else { setUnread(n); }
    }).catch(() => { });
  }

  function markRead() {
    const rc = room();
    if (!rc || !S.lastId) return Promise.resolve();
    return api('/api/room/im/read', { room_code: rc, last_read_id: S.lastId })
      .then(() => setUnread(0)).catch(() => { });
  }

  /* ── 发送 / 撤回 ─────────────────────────────────────── */
  function send() {
    const box = $('#imText');
    if (!box) return;
    const text = (box.value || '').trim();
    const rc = room();
    if (!text || !rc || S.closed) return;
    box.value = '';
    api('/api/room/im/send', { room_code: rc, text: text }).then(js => {
      merge([js.message]); paint(); markRead();
    }).catch(e => {
      box.value = text;
      if (window.NP && NP.toast) { try { NP.toast('发送失败：' + e.message, 'danger'); } catch (x) { } }
    });
  }

  function recall(id) {
    const rc = room();
    if (!rc) return;
    api('/api/room/im/recall', { room_code: rc, id: Number(id) }).then(js => {
      const i = S.msgs.findIndex(m => m.id === js.message.id);
      if (i >= 0) S.msgs[i] = js.message;
      paint();
    }).catch(e => { if (window.NP && NP.toast) { try { NP.toast('撤回失败：' + e.message, 'danger'); } catch (x) { } } });
  }

  /* ── 归档只读 ───────────────────────────────────────── */
  function applyClosed() {
    const box = $('#imText'), btn = $('#imSend'), tip = $('#imReadonly');
    if (box) { box.disabled = S.closed; box.placeholder = S.closed ? '房间已归档，仅可查看' : (IMC.placeholder || '输入消息，Enter 发送 / Shift+Enter 换行'); }
    if (btn) btn.disabled = S.closed;
    if (tip) tip.classList.toggle('hidden', !S.closed);
  }

  /* ── 文件：上传即消息（走既有 room_files 分块接口） ──── */
  function uploadFiles(files) {
    const rc = room();
    if (!rc || !files || !files.length) return;
    Array.from(files).forEach(f => uploadOne(rc, f));
  }
  function uploadOne(rc, f) {
    const CHUNK = 4 * 1024 * 1024;
    const total = Math.max(1, Math.ceil(f.size / CHUNK));
    const fid = 'im' + Date.now().toString(36) + Math.random().toString(36).slice(2, 8);
    const prog = $('#imUpload');
    const setProg = t => { if (prog) { prog.textContent = t; prog.classList.toggle('hidden', !t); } };
    // 输入框里已写的文字当作附件说明（note）
    const noteBox = $('#imText');
    const note = noteBox ? (noteBox.value || '').trim() : '';
    if (note && noteBox) noteBox.value = '';
    setProg('上传中 ' + f.name + ' …');

    let seq = 0;
    const sendChunk = () => new Promise((resolve, reject) => {
      if (seq >= total) return resolve();
      const blob = f.slice(seq * CHUNK, (seq + 1) * CHUNK);
      const fd = new FormData();
      fd.append('file', blob, f.name);
      const url = '/api/room/file/chunk?room=' + encodeURIComponent(rc) + '&fid=' + encodeURIComponent(fid) + '&seq=' + seq;
      fetch(url, { method: 'POST', credentials: 'same-origin', body: fd })
        .then(r => r.json().then(j => { if (!r.ok) throw new Error(j.error || ('HTTP ' + r.status)); return j; }))
        .then(() => { seq++; setProg('上传中 ' + Math.round(seq / total * 100) + '% · ' + f.name); resolve(sendChunk()); })
        .catch(reject);
    });

    sendChunk()
      .then(() => fetch('/api/room/file/commit', {
        method: 'POST', credentials: 'same-origin',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ room_code: rc, fid: fid, filename: f.name, note: note })
      }).then(r => r.json().then(j => { if (!r.ok) throw new Error(j.error || ('HTTP ' + r.status)); return j; })))
      .then(() => { setProg(''); poll(); })
      .catch(e => {
        setProg('');
        if (note && noteBox) noteBox.value = note;
        if (window.NP && NP.toast) { try { NP.toast('上传失败：' + e.message, 'danger'); } catch (x) { } }
      });
  }

  /* ── 绑定 ───────────────────────────────────────────── */
  function bind() {
    const sendBtn = $('#imSend');
    if (sendBtn) sendBtn.addEventListener('click', send);
    const box = $('#imText');
    if (box) box.addEventListener('keydown', e => {
      if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); send(); }
    });
    const pick = $('#imPick');
    if (pick) pick.addEventListener('click', () => { const i = $('#imFileInput'); if (i) i.click(); });
    const fi = $('#imFileInput');
    if (fi) fi.addEventListener('change', () => { uploadFiles(fi.files); fi.value = ''; });
    const drop = $('#imDrop');
    if (drop) {
      ['dragenter', 'dragover'].forEach(ev => drop.addEventListener(ev, e => { e.preventDefault(); drop.classList.add('on'); }));
      ['dragleave', 'drop'].forEach(ev => drop.addEventListener(ev, e => { e.preventDefault(); drop.classList.remove('on'); }));
      drop.addEventListener('drop', e => { if (e.dataTransfer && e.dataTransfer.files) uploadFiles(e.dataTransfer.files); });
      // 粘贴图片
      drop.addEventListener('paste', e => {
        const items = (e.clipboardData && e.clipboardData.items) || [];
        const imgs = [];
        for (const it of items) if (it.kind === 'file') { const f = it.getAsFile(); if (f) imgs.push(f); }
        if (imgs.length) { e.preventDefault(); uploadFiles(imgs); }
      });
    }
    // 文件面板
    const fb = $('#imFilesBtn'), panel = $('#imFilesPanel'), mask = $('#imFilesMask'), close = $('#imFilesClose');
    const openPanel = () => {
      if (!panel) return;
      panel.classList.add('on'); if (mask) mask.classList.add('on');
      try { if (window.NP && NP.rfLoad) NP.rfLoad(); } catch (e) { }
    };
    const closePanel = () => { if (panel) panel.classList.remove('on'); if (mask) mask.classList.remove('on'); };
    if (fb) fb.addEventListener('click', openPanel);
    if (close) close.addEventListener('click', closePanel);
    if (mask) mask.addEventListener('click', closePanel);
    document.addEventListener('keydown', e => { if (e.key === 'Escape') closePanel(); });
  }

  function start() {
    if (S.started) return;
    if (!room()) { setTimeout(start, 1200); return; }
    S.started = true;
    bind();
    loadHistory().then(() => { if (!S.timer) S.timer = setInterval(poll, POLL_MS); });
    // 房间切换后重置
    try {
      if (window.NP && NP.subscribe) NP.subscribe(kind => {
        if (kind === 'room') { S.msgs = []; S.lastId = 0; paint(); loadHistory(); }
      });
    } catch (e) { }
  }

  window.IM = { start: start, reload: loadHistory, send: send };
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', start);
  else start();
})();

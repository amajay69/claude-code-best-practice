'use strict';

// BizConnect frontend — a tiny dependency-free SPA.
// State lives in memory; every view re-fetches from the REST API so data stays
// fresh after creates. Rendering is plain template strings injected into #app.

const app = document.getElementById('app');
let currentView = 'feed';
let searchKind = '';
let searchTimer = null;

// --- API helpers -----------------------------------------------------------

async function api(path, opts) {
  const res = await fetch(path, {
    headers: { 'Content-Type': 'application/json' },
    ...opts,
  });
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(body.error || `Request failed: ${res.status}`);
  }
  return res.json();
}

const esc = (s) =>
  String(s ?? '').replace(/[&<>"']/g, (c) =>
    ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c])
  );

const tagPills = (tags) =>
  !tags
    ? ''
    : `<div class="tags">${tags
        .split(',')
        .map((t) => t.trim())
        .filter(Boolean)
        .map((t) => `<span class="tag">${esc(t)}</span>`)
        .join('')}</div>`;

// --- Views -----------------------------------------------------------------

async function renderFeed() {
  const posts = await api('/api/posts');
  app.innerHTML =
    `<div class="section-title">Business talk from the network</div>` +
    (posts.length
      ? posts
          .map(
            (p) => `
        <div class="card">
          <div class="row">
            <h4>${esc(p.member_name)} <span class="meta">· ${esc(p.business_name || '')}</span></h4>
            <span class="badge post">${esc(p.group_name || 'No group')}</span>
          </div>
          <p>${esc(p.content)}</p>
          <div class="meta">${esc(p.created_at)}</div>
        </div>`
          )
          .join('')
      : `<div class="empty">No posts yet. Tap ＋ to share something.</div>`);
}

async function renderListings(kind) {
  const rows = await api(`/api/listings?kind=${kind}`);
  const label = kind === 'ask' ? 'Asks — what members need' : 'Gives — what members offer';
  app.innerHTML =
    `<div class="section-title">${label}</div>` +
    (rows.length
      ? rows.map(listingCard).join('')
      : `<div class="empty">No ${kind}s yet. Tap ＋ to add one.</div>`);
  wireListingButtons();
}

function listingCard(l) {
  return `
    <div class="card">
      <div class="row">
        <h4>${esc(l.title)}</h4>
        <span class="badge ${l.kind}">${l.kind}</span>
      </div>
      <div class="meta">${esc(l.member_name)} · ${esc(l.business_name || '')} · ${esc(l.group_name || 'No group')}</div>
      ${l.description ? `<p>${esc(l.description)}</p>` : ''}
      ${tagPills(l.tags)}
      <div style="margin-top:10px; display:flex; gap:8px; align-items:center;">
        <span class="badge ${l.status === 'closed' ? 'closed' : l.kind}">${esc(l.status)}</span>
        <button class="btn secondary small toggle-status" data-id="${l.id}" data-status="${l.status === 'open' ? 'closed' : 'open'}">
          Mark ${l.status === 'open' ? 'closed' : 'open'}
        </button>
      </div>
    </div>`;
}

function wireListingButtons() {
  document.querySelectorAll('.toggle-status').forEach((btn) => {
    btn.addEventListener('click', async () => {
      await api(`/api/listings/${btn.dataset.id}`, {
        method: 'PATCH',
        body: JSON.stringify({ status: btn.dataset.status }),
      });
      renderView();
    });
  });
}

async function renderGroups() {
  const groups = await api('/api/groups');
  app.innerHTML =
    `<div class="section-title">Networking groups</div>` +
    (groups.length
      ? groups
          .map(
            (g) => `
        <div class="card">
          <div class="row">
            <h4>${esc(g.name)}</h4>
            <span class="badge member">${g.member_count} member${g.member_count === 1 ? '' : 's'}</span>
          </div>
          ${g.description ? `<p>${esc(g.description)}</p>` : ''}
        </div>`
          )
          .join('')
      : `<div class="empty">No groups yet. Tap ＋ to create one.</div>`);
}

async function renderMembers() {
  const members = await api('/api/members');
  app.innerHTML =
    `<div class="section-title">Members directory</div>` +
    (members.length
      ? members
          .map(
            (m) => `
        <div class="card">
          <div class="row">
            <h4>${esc(m.name)}</h4>
            <span class="badge member">${esc(m.group_name || 'No group')}</span>
          </div>
          <div class="meta">${esc(m.business_name || '—')}${m.category ? ' · ' + esc(m.category) : ''}</div>
          ${m.email ? `<div class="meta">${esc(m.email)}</div>` : ''}
        </div>`
          )
          .join('')
      : `<div class="empty">No members yet. Tap ＋ to add one.</div>`);
}

// --- Cross-app search ------------------------------------------------------

async function renderSearch(q) {
  const data = await api(`/api/search?q=${encodeURIComponent(q)}&kind=${searchKind}`);
  if (!data.results.length) {
    app.innerHTML = `<div class="section-title">Search</div><div class="empty">No matches for “${esc(q)}”.</div>`;
    return;
  }
  app.innerHTML =
    `<div class="section-title">${data.count} result${data.count === 1 ? '' : 's'} for “${esc(q)}”</div>` +
    data.results
      .map((r) => {
        const who =
          r.type === 'ask' || r.type === 'give'
            ? `${esc(r.member_name)} · ${esc(r.business_name || '')}`
            : '';
        return `
        <div class="card search-result">
          <div class="row">
            <h4>${esc(r.title)}</h4>
            <span class="badge ${r.type}">${r.type}</span>
          </div>
          ${r.subtitle ? `<p>${esc(r.subtitle)}</p>` : ''}
          ${who ? `<div class="meta">${who}</div>` : ''}
          ${tagPills(r.tags)}
          <div class="type-line">${esc(r.group_name || '')}</div>
        </div>`;
      })
      .join('');
}

// --- Router ----------------------------------------------------------------

function renderView() {
  const q = document.getElementById('globalSearch').value.trim();
  if (q) return renderSearch(q);
  if (currentView === 'feed') return renderFeed();
  if (currentView === 'asks') return renderListings('ask');
  if (currentView === 'gives') return renderListings('give');
  if (currentView === 'groups') return renderGroups();
  if (currentView === 'members') return renderMembers();
}

// --- Create forms (modal) --------------------------------------------------

const overlay = document.getElementById('modalOverlay');
const modalBody = document.getElementById('modalBody');
const modalTitle = document.getElementById('modalTitle');

function closeModal() {
  overlay.classList.add('hidden');
  modalBody.innerHTML = '';
}

document.getElementById('modalClose').addEventListener('click', closeModal);
overlay.addEventListener('click', (e) => {
  if (e.target === overlay) closeModal();
});

async function memberOptions() {
  const members = await api('/api/members');
  return members.map((m) => `<option value="${m.id}">${esc(m.name)} — ${esc(m.business_name || '')}</option>`).join('');
}

async function groupOptions() {
  const groups = await api('/api/groups');
  return (
    `<option value="">No group</option>` +
    groups.map((g) => `<option value="${g.id}">${esc(g.name)}</option>`).join('')
  );
}

// Opens the create modal appropriate to the current view.
async function openCreate() {
  let html = '';
  if (currentView === 'groups') {
    modalTitle.textContent = 'New group';
    html = `
      <div class="field"><label>Name</label><input id="f_name" /></div>
      <div class="field"><label>Description</label><textarea id="f_desc"></textarea></div>
      <button class="btn" id="f_submit">Create group</button>`;
  } else if (currentView === 'members') {
    modalTitle.textContent = 'New member';
    html = `
      <div class="field"><label>Name</label><input id="f_name" /></div>
      <div class="field"><label>Business name</label><input id="f_biz" /></div>
      <div class="field"><label>Category</label><input id="f_cat" placeholder="e.g. Accounting" /></div>
      <div class="field"><label>Email</label><input id="f_email" /></div>
      <div class="field"><label>Group</label><select id="f_group">${await groupOptions()}</select></div>
      <button class="btn" id="f_submit">Add member</button>`;
  } else if (currentView === 'feed') {
    modalTitle.textContent = 'New post';
    html = `
      <div class="field"><label>Member</label><select id="f_member">${await memberOptions()}</select></div>
      <div class="field"><label>What's on your mind?</label><textarea id="f_content"></textarea></div>
      <button class="btn" id="f_submit">Post</button>`;
  } else {
    // asks or gives
    const kind = currentView === 'asks' ? 'ask' : 'give';
    modalTitle.textContent = kind === 'ask' ? 'New Ask' : 'New Give';
    html = `
      <div class="field"><label>Member</label><select id="f_member">${await memberOptions()}</select></div>
      <div class="field"><label>Title</label><input id="f_title" placeholder="${kind === 'ask' ? 'What do you need?' : 'What can you offer?'}" /></div>
      <div class="field"><label>Description</label><textarea id="f_desc"></textarea></div>
      <div class="field"><label>Tags (comma separated)</label><input id="f_tags" placeholder="marketing, referrals" /></div>
      <button class="btn" id="f_submit">Create ${kind}</button>`;
  }
  modalBody.innerHTML = html;
  overlay.classList.remove('hidden');
  document.getElementById('f_submit').addEventListener('click', submitCreate);
}

async function submitCreate() {
  try {
    if (currentView === 'groups') {
      await api('/api/groups', {
        method: 'POST',
        body: JSON.stringify({
          name: val('f_name'),
          description: val('f_desc'),
        }),
      });
    } else if (currentView === 'members') {
      await api('/api/members', {
        method: 'POST',
        body: JSON.stringify({
          name: val('f_name'),
          business_name: val('f_biz'),
          category: val('f_cat'),
          email: val('f_email'),
          group_id: val('f_group') || null,
        }),
      });
    } else if (currentView === 'feed') {
      await api('/api/posts', {
        method: 'POST',
        body: JSON.stringify({
          member_id: val('f_member'),
          content: val('f_content'),
        }),
      });
    } else {
      const kind = currentView === 'asks' ? 'ask' : 'give';
      await api('/api/listings', {
        method: 'POST',
        body: JSON.stringify({
          member_id: val('f_member'),
          kind,
          title: val('f_title'),
          description: val('f_desc'),
          tags: val('f_tags'),
        }),
      });
    }
    closeModal();
    renderView();
  } catch (err) {
    alert(err.message);
  }
}

const val = (id) => {
  const el = document.getElementById(id);
  return el ? el.value.trim() : '';
};

// --- Wiring ----------------------------------------------------------------

document.querySelectorAll('.tab').forEach((tab) => {
  tab.addEventListener('click', () => {
    document.querySelectorAll('.tab').forEach((t) => t.classList.remove('active'));
    tab.classList.add('active');
    currentView = tab.dataset.view;
    document.getElementById('globalSearch').value = '';
    renderView();
  });
});

document.querySelectorAll('.chip').forEach((chip) => {
  chip.addEventListener('click', () => {
    document.querySelectorAll('.chip').forEach((c) => c.classList.remove('active'));
    chip.classList.add('active');
    searchKind = chip.dataset.kind;
    if (document.getElementById('globalSearch').value.trim()) renderView();
  });
});

document.getElementById('globalSearch').addEventListener('input', () => {
  clearTimeout(searchTimer);
  searchTimer = setTimeout(renderView, 200); // debounce
});

document.getElementById('fab').addEventListener('click', openCreate);

// Initial paint
renderView();

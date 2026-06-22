'use strict';

// BizConnect frontend — a tiny dependency-free SPA.
// The app has two modes: an auth screen when logged out, and the main app when
// logged in. `currentUser` is the logged-in member; their identity is used
// implicitly when creating posts and listings (no member dropdowns).

const app = document.getElementById('app');
const appRoot = document.getElementById('appRoot');
const authScreen = document.getElementById('authScreen');
const fab = document.getElementById('fab');

let currentUser = null;
let currentView = 'feed';
let searchKind = '';
let searchTimer = null;

// --- API helper ------------------------------------------------------------

async function api(path, opts) {
  const res = await fetch(path, {
    headers: { 'Content-Type': 'application/json' },
    credentials: 'same-origin', // send the session cookie
    ...opts,
  });
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(body.error || `Request failed: ${res.status}`);
  }
  return res.status === 204 ? null : res.json();
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

const val = (id) => {
  const el = document.getElementById(id);
  return el ? el.value.trim() : '';
};

// --- Auth flow -------------------------------------------------------------

async function boot() {
  currentUser = await api('/api/auth/me').catch(() => null);
  if (currentUser) showApp();
  else showAuth();
}

function showAuth() {
  appRoot.classList.add('hidden');
  fab.classList.add('hidden');
  authScreen.classList.remove('hidden');
  renderAuthForm('login');
}

function showApp() {
  authScreen.classList.add('hidden');
  appRoot.classList.remove('hidden');
  document.getElementById('userArea').innerHTML = `
    <span class="who">${esc(currentUser.name)}<small>${esc(currentUser.business_name || '')}</small></span>
    <button class="btn secondary small" id="logoutBtn">Log out</button>`;
  document.getElementById('logoutBtn').addEventListener('click', logout);
  renderView();
}

let authMode = 'login';
function renderAuthForm(mode) {
  authMode = mode;
  document.querySelectorAll('.auth-tab').forEach((t) =>
    t.classList.toggle('active', t.dataset.auth === mode)
  );
  document.getElementById('authHint').textContent = '';
  const body = document.getElementById('authBody');
  if (mode === 'login') {
    body.innerHTML = `
      <div class="field"><label>Email</label><input id="a_email" type="email" /></div>
      <div class="field"><label>Password</label><input id="a_password" type="password" /></div>
      <button class="btn" id="a_submit">Log in</button>`;
  } else {
    body.innerHTML = `
      <div class="field"><label>Your name</label><input id="a_name" /></div>
      <div class="field"><label>Business name</label><input id="a_biz" /></div>
      <div class="field"><label>Category</label><input id="a_cat" placeholder="e.g. Marketing" /></div>
      <div class="field"><label>Email</label><input id="a_email" type="email" /></div>
      <div class="field"><label>Password</label><input id="a_password" type="password" /></div>
      <button class="btn" id="a_submit">Create account</button>`;
  }
  document.getElementById('a_submit').addEventListener('click', submitAuth);
  body.querySelectorAll('input').forEach((inp) =>
    inp.addEventListener('keydown', (e) => {
      if (e.key === 'Enter') submitAuth();
    })
  );
}

async function submitAuth() {
  const hint = document.getElementById('authHint');
  hint.className = 'auth-hint';
  try {
    if (authMode === 'login') {
      currentUser = await api('/api/auth/login', {
        method: 'POST',
        body: JSON.stringify({ email: val('a_email'), password: val('a_password') }),
      });
    } else {
      currentUser = await api('/api/auth/register', {
        method: 'POST',
        body: JSON.stringify({
          name: val('a_name'),
          business_name: val('a_biz'),
          category: val('a_cat'),
          email: val('a_email'),
          password: val('a_password'),
        }),
      });
    }
    showApp();
  } catch (err) {
    hint.className = 'auth-hint error';
    hint.textContent = err.message;
  }
}

async function logout() {
  await api('/api/auth/logout', { method: 'POST' }).catch(() => {});
  currentUser = null;
  document.getElementById('globalSearch').value = '';
  showAuth();
}

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
  const isOwner = currentUser && l.member_id === currentUser.id;
  const ownerActions = isOwner
    ? `<button class="btn secondary small toggle-status" data-id="${l.id}" data-status="${l.status === 'open' ? 'closed' : 'open'}">
         Mark ${l.status === 'open' ? 'closed' : 'open'}
       </button>
       <button class="btn secondary small view-responses" data-id="${l.id}">View responses</button>`
    : `<button class="btn small respond" data-id="${l.id}" data-title="${esc(l.title)}">Respond / Connect</button>`;
  return `
    <div class="card" id="listing-${l.id}">
      <div class="row">
        <h4>${esc(l.title)}</h4>
        <span class="badge ${l.kind}">${l.kind}</span>
      </div>
      <div class="meta">${esc(l.member_name)} · ${esc(l.business_name || '')} · ${esc(l.group_name || 'No group')}</div>
      ${l.description ? `<p>${esc(l.description)}</p>` : ''}
      ${tagPills(l.tags)}
      <div class="listing-actions">
        <span class="badge ${l.status === 'closed' ? 'closed' : l.kind}">${esc(l.status)}</span>
        ${l.response_count ? `<span class="count-badge">${l.response_count} response${l.response_count === 1 ? '' : 's'}</span>` : ''}
        ${ownerActions}
      </div>
      <div class="responses-slot"></div>
    </div>`;
}

function wireListingButtons() {
  document.querySelectorAll('.toggle-status').forEach((btn) =>
    btn.addEventListener('click', async () => {
      await api(`/api/listings/${btn.dataset.id}`, {
        method: 'PATCH',
        body: JSON.stringify({ status: btn.dataset.status }),
      });
      renderView();
    })
  );
  document.querySelectorAll('.respond').forEach((btn) =>
    btn.addEventListener('click', () => openRespond(btn.dataset.id, btn.dataset.title))
  );
  document.querySelectorAll('.view-responses').forEach((btn) =>
    btn.addEventListener('click', () => loadResponses(btn.dataset.id))
  );
}

async function loadResponses(listingId) {
  const slot = document.querySelector(`#listing-${listingId} .responses-slot`);
  const data = await api(`/api/listings/${listingId}/responses`);
  if (!data.responses.length) {
    slot.innerHTML = `<div class="responses"><div class="meta">No responses yet.</div></div>`;
    return;
  }
  slot.innerHTML =
    `<div class="responses">` +
    data.responses
      .map(
        (r) => `
      <div class="response">
        <div class="who">${esc(r.member_name)} <small>· ${esc(r.business_name || '')} · ${esc(r.email)}</small></div>
        <p>${esc(r.message)}</p>
      </div>`
      )
      .join('') +
    `</div>`;
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
            <h4>${esc(m.name)}${m.id === currentUser.id ? ' <span class="meta">(you)</span>' : ''}</h4>
            <span class="badge member">${esc(m.group_name || 'No group')}</span>
          </div>
          <div class="meta">${esc(m.business_name || '—')}${m.category ? ' · ' + esc(m.category) : ''}</div>
          ${m.email ? `<div class="meta">${esc(m.email)}</div>` : ''}
        </div>`
          )
          .join('')
      : `<div class="empty">No members yet.</div>`);
}

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
  // The FAB makes no sense on the read-only members directory or in search.
  fab.classList.toggle('hidden', currentView === 'members' || !!q);
  if (q) return renderSearch(q);
  if (currentView === 'feed') return renderFeed();
  if (currentView === 'asks') return renderListings('ask');
  if (currentView === 'gives') return renderListings('give');
  if (currentView === 'groups') return renderGroups();
  if (currentView === 'members') return renderMembers();
}

// --- Modal create forms ----------------------------------------------------

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

// "Respond / Connect" modal — send a message to a listing owner.
function openRespond(listingId, title) {
  modalTitle.textContent = `Respond to “${title}”`;
  modalBody.innerHTML = `
    <div class="field"><label>Your message</label><textarea id="r_message" placeholder="Introduce yourself and how you can help / what you need…"></textarea></div>
    <button class="btn" id="r_submit">Send response</button>`;
  overlay.classList.remove('hidden');
  document.getElementById('r_submit').addEventListener('click', async () => {
    try {
      await api(`/api/listings/${listingId}/responses`, {
        method: 'POST',
        body: JSON.stringify({ message: val('r_message') }),
      });
      closeModal();
      renderView();
    } catch (err) {
      alert(err.message);
    }
  });
}

// Opens the create modal appropriate to the current view. Posts and listings
// use the logged-in member implicitly — no member selector needed.
function openCreate() {
  let html = '';
  if (currentView === 'groups') {
    modalTitle.textContent = 'New group';
    html = `
      <div class="field"><label>Name</label><input id="f_name" /></div>
      <div class="field"><label>Description</label><textarea id="f_desc"></textarea></div>
      <button class="btn" id="f_submit">Create group</button>`;
  } else if (currentView === 'feed') {
    modalTitle.textContent = 'New post';
    html = `
      <div class="field"><label>What's on your mind?</label><textarea id="f_content"></textarea></div>
      <button class="btn" id="f_submit">Post</button>`;
  } else {
    const kind = currentView === 'asks' ? 'ask' : 'give';
    modalTitle.textContent = kind === 'ask' ? 'New Ask' : 'New Give';
    html = `
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
        body: JSON.stringify({ name: val('f_name'), description: val('f_desc') }),
      });
    } else if (currentView === 'feed') {
      await api('/api/posts', {
        method: 'POST',
        body: JSON.stringify({ content: val('f_content') }),
      });
    } else {
      const kind = currentView === 'asks' ? 'ask' : 'give';
      await api('/api/listings', {
        method: 'POST',
        body: JSON.stringify({
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

// --- Wiring ----------------------------------------------------------------

document.querySelectorAll('.auth-tab').forEach((tab) =>
  tab.addEventListener('click', () => renderAuthForm(tab.dataset.auth))
);

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

fab.addEventListener('click', openCreate);

// Initial boot — decide auth vs app.
boot();

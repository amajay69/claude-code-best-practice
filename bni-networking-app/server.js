'use strict';

// BNI-style networking app — Express server.
//
// Exposes a small REST API over the SQLite data layer and serves the static
// single-page frontend from /public. The most interesting endpoint is
// `/api/search`, which scans members, business posts, and Asks/Gives in one go.
const express = require('express');
const path = require('node:path');
const { db, init } = require('./db');
const auth = require('./auth');

init();

const app = express();
app.use(express.json());
app.use(express.static(path.join(__dirname, 'public')));
// Resolve req.member from the session cookie on every request (null if none).
app.use(auth.attachMember);

// --- Small helpers ---------------------------------------------------------

// Wrap a handler so any thrown error becomes a clean 400/500 JSON response
// instead of crashing the process.
const wrap = (fn) => (req, res) => {
  try {
    fn(req, res);
  } catch (err) {
    const status = err.status || 500;
    if (status >= 500) console.error(err); // only log unexpected failures
    res.status(status).json({ error: err.message });
  }
};

function required(body, fields) {
  for (const f of fields) {
    if (!body[f] || String(body[f]).trim() === '') {
      const e = new Error(`Missing required field: ${f}`);
      e.status = 400;
      throw e;
    }
  }
}

// Explicit member columns — NEVER select m.* for members, since that would
// leak password_hash to clients.
const M_COLS = 'm.id, m.name, m.business_name, m.category, m.email, m.group_id, m.created_at';

// --- Auth ------------------------------------------------------------------

// Register creates a member account (the auth principal) and logs them in.
app.post('/api/auth/register', wrap((req, res) => {
  required(req.body, ['name', 'email', 'password']);
  const { name, email, password, business_name = '', category = '', group_id = null } = req.body;
  const existing = db.prepare('SELECT id FROM members WHERE lower(email) = lower(?)').get(email.trim());
  if (existing) return res.status(409).json({ error: 'That email is already registered' });

  const info = db.prepare(`
    INSERT INTO members (name, business_name, category, email, password_hash, group_id)
    VALUES (?, ?, ?, ?, ?, ?)
  `).run(
    name.trim(), business_name.trim(), category.trim(), email.trim(),
    auth.hashPassword(password), group_id || null
  );
  const token = auth.createSession(Number(info.lastInsertRowid));
  auth.setSessionCookie(res, token);
  res.status(201).json(publicMember(Number(info.lastInsertRowid)));
}));

app.post('/api/auth/login', wrap((req, res) => {
  required(req.body, ['email', 'password']);
  const row = db.prepare('SELECT * FROM members WHERE lower(email) = lower(?)').get(req.body.email.trim());
  if (!row || !auth.verifyPassword(req.body.password, row.password_hash)) {
    return res.status(401).json({ error: 'Invalid email or password' });
  }
  const token = auth.createSession(row.id);
  auth.setSessionCookie(res, token);
  res.json(publicMember(row.id));
}));

app.post('/api/auth/logout', wrap((req, res) => {
  auth.destroySession(req.sessionToken);
  auth.clearSessionCookie(res);
  res.json({ ok: true });
}));

app.get('/api/auth/me', wrap((req, res) => {
  res.json(req.member || null);
}));

// Returns a member without the password hash — safe to send to clients.
function publicMember(id) {
  return db.prepare(`
    SELECT m.id, m.name, m.business_name, m.category, m.email, m.group_id, g.name AS group_name
    FROM members m LEFT JOIN groups g ON g.id = m.group_id
    WHERE m.id = ?
  `).get(id);
}

// --- Groups ----------------------------------------------------------------

app.get('/api/groups', wrap((req, res) => {
  const rows = db.prepare(`
    SELECT g.*, COUNT(m.id) AS member_count
    FROM groups g
    LEFT JOIN members m ON m.group_id = g.id
    GROUP BY g.id
    ORDER BY g.name
  `).all();
  res.json(rows);
}));

app.post('/api/groups', auth.requireAuth, wrap((req, res) => {
  required(req.body, ['name']);
  const { name, description = '' } = req.body;
  const info = db
    .prepare('INSERT INTO groups (name, description) VALUES (?, ?)')
    .run(name.trim(), description.trim());
  res.status(201).json(db.prepare('SELECT * FROM groups WHERE id = ?').get(info.lastInsertRowid));
}));

app.get('/api/groups/:id', wrap((req, res) => {
  const group = db.prepare('SELECT * FROM groups WHERE id = ?').get(req.params.id);
  if (!group) return res.status(404).json({ error: 'Group not found' });
  group.members = db
    .prepare(`SELECT ${M_COLS} FROM members m WHERE m.group_id = ? ORDER BY m.name`)
    .all(group.id);
  res.json(group);
}));

// --- Members ---------------------------------------------------------------

app.get('/api/members', wrap((req, res) => {
  const rows = db.prepare(`
    SELECT ${M_COLS}, g.name AS group_name
    FROM members m
    LEFT JOIN groups g ON g.id = m.group_id
    ORDER BY m.name
  `).all();
  res.json(rows);
}));

app.get('/api/members/:id', wrap((req, res) => {
  const member = db.prepare(`
    SELECT ${M_COLS}, g.name AS group_name
    FROM members m
    LEFT JOIN groups g ON g.id = m.group_id
    WHERE m.id = ?
  `).get(req.params.id);
  if (!member) return res.status(404).json({ error: 'Member not found' });
  member.posts = db
    .prepare('SELECT * FROM posts WHERE member_id = ? ORDER BY created_at DESC')
    .all(member.id);
  member.listings = db
    .prepare('SELECT * FROM listings WHERE member_id = ? ORDER BY created_at DESC')
    .all(member.id);
  // Relationship history: when a logged-in member views someone else's profile,
  // include every response exchanged between the two (in either direction).
  if (req.member && req.member.id !== member.id) {
    member.history = db.prepare(`
      SELECT r.message, r.created_at,
             l.title AS listing_title, l.kind AS listing_kind,
             sender.id AS sender_id, sender.name AS sender_name
      FROM responses r
      JOIN listings l ON l.id = r.listing_id
      JOIN members sender ON sender.id = r.member_id
      WHERE (r.member_id = ? AND l.member_id = ?)
         OR (r.member_id = ? AND l.member_id = ?)
      ORDER BY r.created_at
    `).all(member.id, req.member.id, req.member.id, member.id);
  }
  res.json(member);
}));

// --- Matches (the heart of the new home screen) ------------------------------

// Answers "who should I talk to today?" by intersecting the logged-in member's
// open listings with everyone else's, on shared tags (+ a category bonus).
// direction 'they_can_help' = their Give matches one of your Asks;
// direction 'you_can_help'  = their Ask matches one of your Gives.
app.get('/api/matches', auth.requireAuth, wrap((req, res) => {
  const mine = db.prepare(
    "SELECT * FROM listings WHERE member_id = ? AND status = 'open'"
  ).all(req.member.id);
  const others = db.prepare(`
    SELECT l.*, m.name AS member_name, m.business_name, m.category, g.name AS group_name
    FROM listings l
    JOIN members m ON m.id = l.member_id
    LEFT JOIN groups g ON g.id = m.group_id
    WHERE l.member_id != ? AND l.status = 'open'
  `).all(req.member.id);

  const tagSet = (l) => new Set(
    String(l.tags || '').split(',').map((t) => t.trim().toLowerCase()).filter(Boolean)
  );

  const matches = [];
  for (const my of mine) {
    const wantKind = my.kind === 'ask' ? 'give' : 'ask';
    const myTags = tagSet(my);
    if (!myTags.size) continue;
    for (const their of others) {
      if (their.kind !== wantKind) continue;
      const shared = [...tagSet(their)].filter((t) => myTags.has(t));
      const categoryBonus = their.category && myTags.has(their.category.toLowerCase()) ? 1 : 0;
      const score = shared.length + categoryBonus;
      if (score === 0) continue;
      matches.push({
        direction: my.kind === 'ask' ? 'they_can_help' : 'you_can_help',
        score,
        shared_tags: shared,
        your_listing: { id: my.id, kind: my.kind, title: my.title },
        their_listing: {
          id: their.id, kind: their.kind, title: their.title,
          description: their.description, tags: their.tags,
          member_id: their.member_id, member_name: their.member_name,
          business_name: their.business_name, group_name: their.group_name,
        },
      });
    }
  }
  matches.sort((a, b) => b.score - a.score);
  res.json({ matches });
}));

// --- Posts (business talk) -------------------------------------------------

app.get('/api/posts', wrap((req, res) => {
  const rows = db.prepare(`
    SELECT p.*, m.name AS member_name, m.business_name, g.name AS group_name
    FROM posts p
    JOIN members m ON m.id = p.member_id
    LEFT JOIN groups g ON g.id = m.group_id
    ORDER BY p.created_at DESC
  `).all();
  res.json(rows);
}));

app.post('/api/posts', auth.requireAuth, wrap((req, res) => {
  required(req.body, ['content']);
  const info = db
    .prepare('INSERT INTO posts (member_id, content) VALUES (?, ?)')
    .run(req.member.id, req.body.content.trim());
  res.status(201).json(db.prepare('SELECT * FROM posts WHERE id = ?').get(info.lastInsertRowid));
}));

// --- Listings (Asks & Gives) -----------------------------------------------

app.get('/api/listings', wrap((req, res) => {
  const { kind } = req.query; // optional: 'ask' | 'give'
  const clause = kind ? 'WHERE l.kind = ?' : '';
  const args = kind ? [kind] : [];
  const rows = db.prepare(`
    SELECT l.*, m.name AS member_name, m.business_name, g.name AS group_name,
           (SELECT COUNT(*) FROM responses r WHERE r.listing_id = l.id) AS response_count
    FROM listings l
    JOIN members m ON m.id = l.member_id
    LEFT JOIN groups g ON g.id = m.group_id
    ${clause}
    ORDER BY l.created_at DESC
  `).all(...args);
  res.json(rows);
}));

app.post('/api/listings', auth.requireAuth, wrap((req, res) => {
  required(req.body, ['kind', 'title']);
  const { kind, title, description = '', tags = '' } = req.body;
  if (!['ask', 'give'].includes(kind)) {
    return res.status(400).json({ error: "kind must be 'ask' or 'give'" });
  }
  const info = db.prepare(`
    INSERT INTO listings (member_id, kind, title, description, tags)
    VALUES (?, ?, ?, ?, ?)
  `).run(req.member.id, kind, title.trim(), description.trim(), tags.trim());
  res.status(201).json(db.prepare('SELECT * FROM listings WHERE id = ?').get(info.lastInsertRowid));
}));

app.patch('/api/listings/:id', auth.requireAuth, wrap((req, res) => {
  const { status } = req.body;
  if (!['open', 'closed'].includes(status)) {
    return res.status(400).json({ error: "status must be 'open' or 'closed'" });
  }
  const listing = db.prepare('SELECT * FROM listings WHERE id = ?').get(req.params.id);
  if (!listing) return res.status(404).json({ error: 'Listing not found' });
  // Only the owner can open/close their own listing.
  if (listing.member_id !== req.member.id) {
    return res.status(403).json({ error: 'You can only change your own listings' });
  }
  db.prepare('UPDATE listings SET status = ? WHERE id = ?').run(status, req.params.id);
  res.json(db.prepare('SELECT * FROM listings WHERE id = ?').get(req.params.id));
}));

// --- Responses (the "Connect" action) --------------------------------------

// A logged-in member responds to someone's Ask/Give with a message. The listing
// owner reads these to follow up — this is the core networking interaction.
app.post('/api/listings/:id/responses', auth.requireAuth, wrap((req, res) => {
  required(req.body, ['message']);
  const listing = db.prepare('SELECT * FROM listings WHERE id = ?').get(req.params.id);
  if (!listing) return res.status(404).json({ error: 'Listing not found' });
  const info = db.prepare(`
    INSERT INTO responses (listing_id, member_id, message) VALUES (?, ?, ?)
  `).run(listing.id, req.member.id, req.body.message.trim());
  res.status(201).json(db.prepare('SELECT * FROM responses WHERE id = ?').get(info.lastInsertRowid));
}));

// List responses on a listing. Visible to the listing owner (to follow up) and
// to anyone who already responded (to see the thread they're part of).
app.get('/api/listings/:id/responses', auth.requireAuth, wrap((req, res) => {
  const listing = db.prepare('SELECT * FROM listings WHERE id = ?').get(req.params.id);
  if (!listing) return res.status(404).json({ error: 'Listing not found' });

  const isOwner = listing.member_id === req.member.id;
  const hasResponded = db
    .prepare('SELECT 1 FROM responses WHERE listing_id = ? AND member_id = ? LIMIT 1')
    .get(listing.id, req.member.id);
  if (!isOwner && !hasResponded) {
    return res.status(403).json({ error: 'Only the listing owner can view responses' });
  }
  const rows = db.prepare(`
    SELECT r.*, m.name AS member_name, m.business_name, m.email
    FROM responses r
    JOIN members m ON m.id = r.member_id
    WHERE r.listing_id = ?
    ORDER BY r.created_at
  `).all(listing.id);
  res.json({ owner: isOwner, responses: rows });
}));

// --- Contacts (personal CRM) -------------------------------------------------

// All contact data is private to its owner: every query below filters on
// owner_id = the logged-in member, so nobody can read anyone else's notes.

app.get('/api/contacts', auth.requireAuth, wrap((req, res) => {
  const rows = db.prepare(`
    SELECT c.*, (c.linked_member_id IS NOT NULL) AS linked
    FROM contacts c
    WHERE c.owner_id = ?
    ORDER BY (c.follow_up IS NULL), c.follow_up, c.name
  `).all(req.member.id);
  res.json(rows);
}));

// Create a contact two ways:
//  { member_id }  → pull a network member into your CRM (details copied, link kept)
//  { name, ... }  → external contact, someone not in the app
app.post('/api/contacts', auth.requireAuth, wrap((req, res) => {
  const { member_id } = req.body;
  let info;
  if (member_id) {
    if (Number(member_id) === req.member.id) {
      return res.status(400).json({ error: 'You are always in your own corner — no need to add yourself' });
    }
    const m = db.prepare('SELECT * FROM members WHERE id = ?').get(member_id);
    if (!m) return res.status(404).json({ error: 'Member not found' });
    const dup = db.prepare(
      'SELECT 1 FROM contacts WHERE owner_id = ? AND linked_member_id = ?'
    ).get(req.member.id, m.id);
    if (dup) return res.status(409).json({ error: `${m.name} is already in your contacts` });
    info = db.prepare(`
      INSERT INTO contacts (owner_id, linked_member_id, name, business_name, category, email, notes)
      VALUES (?, ?, ?, ?, ?, ?, ?)
    `).run(req.member.id, m.id, m.name, m.business_name, m.category, m.email, String(req.body.notes || '').trim());
  } else {
    required(req.body, ['name']);
    const { name, business_name = '', category = '', email = '', phone = '', notes = '', follow_up = null } = req.body;
    info = db.prepare(`
      INSERT INTO contacts (owner_id, name, business_name, category, email, phone, notes, follow_up)
      VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    `).run(req.member.id, name.trim(), business_name.trim(), category.trim(), email.trim(), phone.trim(), notes.trim(), follow_up || null);
  }
  res.status(201).json(db.prepare('SELECT * FROM contacts WHERE id = ?').get(info.lastInsertRowid));
}));

app.patch('/api/contacts/:id', auth.requireAuth, wrap((req, res) => {
  const contact = db.prepare(
    'SELECT * FROM contacts WHERE id = ? AND owner_id = ?'
  ).get(req.params.id, req.member.id);
  if (!contact) return res.status(404).json({ error: 'Contact not found' });
  const fields = ['name', 'business_name', 'category', 'email', 'phone', 'notes', 'follow_up'];
  for (const f of fields) {
    if (f in req.body) {
      const v = req.body[f];
      db.prepare(`UPDATE contacts SET ${f} = ? WHERE id = ?`)
        .run(v === null ? null : String(v).trim(), contact.id);
    }
  }
  res.json(db.prepare('SELECT * FROM contacts WHERE id = ?').get(contact.id));
}));

app.delete('/api/contacts/:id', auth.requireAuth, wrap((req, res) => {
  const info = db.prepare(
    'DELETE FROM contacts WHERE id = ? AND owner_id = ?'
  ).run(req.params.id, req.member.id);
  if (info.changes === 0) return res.status(404).json({ error: 'Contact not found' });
  res.json({ ok: true });
}));

// --- Cross-app search ------------------------------------------------------

// The headline feature: a single query that surfaces matching members,
// business posts, and Asks/Gives. Each result carries a `type` so the UI can
// render it appropriately. Matching is a simple case-insensitive LIKE across
// the most relevant text columns — good enough for an MVP and index-friendly.
app.get('/api/search', wrap((req, res) => {
  const q = String(req.query.q || '').trim();
  const kindFilter = req.query.kind; // optional: 'member' | 'post' | 'ask' | 'give'
  if (!q) return res.json({ query: '', results: [] });

  const like = `%${q.toLowerCase()}%`;
  const results = [];

  const wantsMember = !kindFilter || kindFilter === 'member';
  const wantsPost = !kindFilter || kindFilter === 'post';
  const wantsAsk = !kindFilter || kindFilter === 'ask';
  const wantsGive = !kindFilter || kindFilter === 'give';

  if (wantsMember) {
    const members = db.prepare(`
      SELECT m.id, m.name, m.business_name, m.category, g.name AS group_name
      FROM members m
      LEFT JOIN groups g ON g.id = m.group_id
      WHERE lower(m.name) LIKE ?
         OR lower(m.business_name) LIKE ?
         OR lower(m.category) LIKE ?
    `).all(like, like, like);
    for (const m of members) {
      results.push({
        type: 'member',
        id: m.id,
        title: m.name,
        subtitle: [m.business_name, m.category].filter(Boolean).join(' • '),
        group_name: m.group_name,
      });
    }
  }

  if (wantsPost) {
    const posts = db.prepare(`
      SELECT p.id, p.content, p.created_at, m.name AS member_name, g.name AS group_name
      FROM posts p
      JOIN members m ON m.id = p.member_id
      LEFT JOIN groups g ON g.id = m.group_id
      WHERE lower(p.content) LIKE ?
    `).all(like);
    for (const p of posts) {
      results.push({
        type: 'post',
        id: p.id,
        title: p.member_name,
        subtitle: p.content,
        group_name: p.group_name,
        created_at: p.created_at,
      });
    }
  }

  if (wantsAsk || wantsGive) {
    const kinds = [];
    if (wantsAsk) kinds.push('ask');
    if (wantsGive) kinds.push('give');
    const placeholders = kinds.map(() => '?').join(', ');
    const listings = db.prepare(`
      SELECT l.id, l.kind, l.title, l.description, l.tags, l.status, l.created_at,
             m.name AS member_name, m.business_name, g.name AS group_name
      FROM listings l
      JOIN members m ON m.id = l.member_id
      LEFT JOIN groups g ON g.id = m.group_id
      WHERE l.kind IN (${placeholders})
        AND (lower(l.title) LIKE ? OR lower(l.description) LIKE ? OR lower(l.tags) LIKE ?)
    `).all(...kinds, like, like, like);
    for (const l of listings) {
      results.push({
        type: l.kind,
        id: l.id,
        title: l.title,
        subtitle: l.description,
        tags: l.tags,
        status: l.status,
        member_name: l.member_name,
        business_name: l.business_name,
        group_name: l.group_name,
        created_at: l.created_at,
      });
    }
  }

  res.json({ query: q, count: results.length, results });
}));

// --- Boot ------------------------------------------------------------------

// First-deploy convenience: if SEED_ON_EMPTY=true and the database has no
// members yet, load the demo data. Never wipes existing data.
if (process.env.SEED_ON_EMPTY === 'true') {
  const { seedIfEmpty } = require('./seed');
  const counts = seedIfEmpty();
  if (counts) console.log(`Seeded demo data into empty database (${counts.members} members).`);
}

const PORT = process.env.PORT || 3000;
if (require.main === module) {
  // Bind to 0.0.0.0 so cloud platforms (Railway, Render, etc.) can route to it.
  app.listen(PORT, '0.0.0.0', () => {
    console.log(`BNI networking app running at http://localhost:${PORT}`);
  });
}

module.exports = app;

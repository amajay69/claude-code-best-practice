'use strict';

// BNI-style networking app — Express server.
//
// Exposes a small REST API over the SQLite data layer and serves the static
// single-page frontend from /public. The most interesting endpoint is
// `/api/search`, which scans members, business posts, and Asks/Gives in one go.
const express = require('express');
const path = require('node:path');
const { db, init } = require('./db');

init();

const app = express();
app.use(express.json());
app.use(express.static(path.join(__dirname, 'public')));

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

app.post('/api/groups', wrap((req, res) => {
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
    .prepare('SELECT * FROM members WHERE group_id = ? ORDER BY name')
    .all(group.id);
  res.json(group);
}));

// --- Members ---------------------------------------------------------------

app.get('/api/members', wrap((req, res) => {
  const rows = db.prepare(`
    SELECT m.*, g.name AS group_name
    FROM members m
    LEFT JOIN groups g ON g.id = m.group_id
    ORDER BY m.name
  `).all();
  res.json(rows);
}));

app.post('/api/members', wrap((req, res) => {
  required(req.body, ['name']);
  const { name, business_name = '', category = '', email = '', group_id = null } = req.body;
  const info = db.prepare(`
    INSERT INTO members (name, business_name, category, email, group_id)
    VALUES (?, ?, ?, ?, ?)
  `).run(name.trim(), business_name.trim(), category.trim(), email.trim(), group_id || null);
  res.status(201).json(db.prepare('SELECT * FROM members WHERE id = ?').get(info.lastInsertRowid));
}));

app.get('/api/members/:id', wrap((req, res) => {
  const member = db.prepare(`
    SELECT m.*, g.name AS group_name
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
  res.json(member);
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

app.post('/api/posts', wrap((req, res) => {
  required(req.body, ['member_id', 'content']);
  const { member_id, content } = req.body;
  const info = db
    .prepare('INSERT INTO posts (member_id, content) VALUES (?, ?)')
    .run(member_id, content.trim());
  res.status(201).json(db.prepare('SELECT * FROM posts WHERE id = ?').get(info.lastInsertRowid));
}));

// --- Listings (Asks & Gives) -----------------------------------------------

app.get('/api/listings', wrap((req, res) => {
  const { kind } = req.query; // optional: 'ask' | 'give'
  const clause = kind ? 'WHERE l.kind = ?' : '';
  const args = kind ? [kind] : [];
  const rows = db.prepare(`
    SELECT l.*, m.name AS member_name, m.business_name, g.name AS group_name
    FROM listings l
    JOIN members m ON m.id = l.member_id
    LEFT JOIN groups g ON g.id = m.group_id
    ${clause}
    ORDER BY l.created_at DESC
  `).all(...args);
  res.json(rows);
}));

app.post('/api/listings', wrap((req, res) => {
  required(req.body, ['member_id', 'kind', 'title']);
  const { member_id, kind, title, description = '', tags = '' } = req.body;
  if (!['ask', 'give'].includes(kind)) {
    return res.status(400).json({ error: "kind must be 'ask' or 'give'" });
  }
  const info = db.prepare(`
    INSERT INTO listings (member_id, kind, title, description, tags)
    VALUES (?, ?, ?, ?, ?)
  `).run(member_id, kind, title.trim(), description.trim(), tags.trim());
  res.status(201).json(db.prepare('SELECT * FROM listings WHERE id = ?').get(info.lastInsertRowid));
}));

app.patch('/api/listings/:id', wrap((req, res) => {
  const { status } = req.body;
  if (!['open', 'closed'].includes(status)) {
    return res.status(400).json({ error: "status must be 'open' or 'closed'" });
  }
  const info = db
    .prepare('UPDATE listings SET status = ? WHERE id = ?')
    .run(status, req.params.id);
  if (info.changes === 0) return res.status(404).json({ error: 'Listing not found' });
  res.json(db.prepare('SELECT * FROM listings WHERE id = ?').get(req.params.id));
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

const PORT = process.env.PORT || 3000;
if (require.main === module) {
  app.listen(PORT, () => {
    console.log(`BNI networking app running at http://localhost:${PORT}`);
  });
}

module.exports = app;

'use strict';

// Authentication helpers built entirely on Node's built-in `node:crypto` —
// no bcrypt/argon native deps, no cookie-parser. Members are the auth
// principal: their email is the login and password_hash stores the scrypt hash.
const crypto = require('node:crypto');
const { db } = require('./db');

// --- Password hashing (scrypt) ---------------------------------------------

// We store `salt:hash` (both hex). scrypt is deliberately slow/memory-hard,
// which is what we want for password storage.
function hashPassword(password) {
  const salt = crypto.randomBytes(16).toString('hex');
  const derived = crypto.scryptSync(password, salt, 64).toString('hex');
  return `${salt}:${derived}`;
}

function verifyPassword(password, stored) {
  if (!stored || !stored.includes(':')) return false;
  const [salt, hash] = stored.split(':');
  const derived = crypto.scryptSync(password, salt, 64).toString('hex');
  // Constant-time compare to avoid timing attacks.
  const a = Buffer.from(hash, 'hex');
  const b = Buffer.from(derived, 'hex');
  return a.length === b.length && crypto.timingSafeEqual(a, b);
}

// --- Sessions --------------------------------------------------------------

const COOKIE = 'bni_session';

function createSession(memberId) {
  const token = crypto.randomBytes(32).toString('hex');
  db.prepare('INSERT INTO sessions (token, member_id) VALUES (?, ?)').run(token, memberId);
  return token;
}

function destroySession(token) {
  if (token) db.prepare('DELETE FROM sessions WHERE token = ?').run(token);
}

// Parse the Cookie header by hand (a few lines beats another dependency).
function readCookie(req, name) {
  const header = req.headers.cookie;
  if (!header) return null;
  for (const part of header.split(';')) {
    const [k, ...v] = part.trim().split('=');
    if (k === name) return decodeURIComponent(v.join('='));
  }
  return null;
}

// Resolve the current member from the session cookie, or null. Attaches the
// raw token to req for logout. Run as global middleware.
function attachMember(req, res, next) {
  const token = readCookie(req, COOKIE);
  req.sessionToken = token;
  req.member = null;
  if (token) {
    req.member = db.prepare(`
      SELECT m.id, m.name, m.business_name, m.category, m.email, m.group_id, g.name AS group_name
      FROM sessions s
      JOIN members m ON m.id = s.member_id
      LEFT JOIN groups g ON g.id = m.group_id
      WHERE s.token = ?
    `).get(token) || null;
  }
  next();
}

// Gate that rejects unauthenticated requests with 401.
function requireAuth(req, res, next) {
  if (!req.member) return res.status(401).json({ error: 'Authentication required' });
  next();
}

function setSessionCookie(res, token) {
  // httpOnly so JS can't read it; SameSite=Lax is a sensible default for an MVP.
  res.setHeader('Set-Cookie', `${COOKIE}=${token}; HttpOnly; SameSite=Lax; Path=/; Max-Age=604800`);
}

function clearSessionCookie(res) {
  res.setHeader('Set-Cookie', `${COOKIE}=; HttpOnly; SameSite=Lax; Path=/; Max-Age=0`);
}

module.exports = {
  hashPassword,
  verifyPassword,
  createSession,
  destroySession,
  attachMember,
  requireAuth,
  setSessionCookie,
  clearSessionCookie,
};

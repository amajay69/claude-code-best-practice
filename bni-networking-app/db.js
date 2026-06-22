'use strict';

// Data layer for the BNI-style networking app.
//
// We use Node's built-in `node:sqlite` (stable in Node 22.5+) so there is no
// native compilation step — the database is a single file on disk (`bni.db`),
// which makes the app trivially portable and easy to reset.
const { DatabaseSync } = require('node:sqlite');
const path = require('node:path');

const DB_PATH = process.env.BNI_DB_PATH || path.join(__dirname, 'bni.db');

const db = new DatabaseSync(DB_PATH);

// Enforce foreign keys (off by default in SQLite) so member/group relationships
// stay consistent and cascading deletes work.
db.exec('PRAGMA foreign_keys = ON;');

/**
 * Create the schema if it does not already exist. Idempotent — safe to call on
 * every boot.
 */
function init() {
  db.exec(`
    CREATE TABLE IF NOT EXISTS groups (
      id          INTEGER PRIMARY KEY AUTOINCREMENT,
      name        TEXT NOT NULL UNIQUE,
      description TEXT NOT NULL DEFAULT '',
      created_at  TEXT NOT NULL DEFAULT (datetime('now'))
    );

    CREATE TABLE IF NOT EXISTS members (
      id            INTEGER PRIMARY KEY AUTOINCREMENT,
      name          TEXT NOT NULL,
      business_name TEXT NOT NULL DEFAULT '',
      category      TEXT NOT NULL DEFAULT '',
      email         TEXT NOT NULL DEFAULT '',
      group_id      INTEGER REFERENCES groups(id) ON DELETE SET NULL,
      created_at    TEXT NOT NULL DEFAULT (datetime('now'))
    );

    -- Business talk: free-form posts a member shares with their group.
    CREATE TABLE IF NOT EXISTS posts (
      id         INTEGER PRIMARY KEY AUTOINCREMENT,
      member_id  INTEGER NOT NULL REFERENCES members(id) ON DELETE CASCADE,
      content    TEXT NOT NULL,
      created_at TEXT NOT NULL DEFAULT (datetime('now'))
    );

    -- The heart of BNI: structured "Asks" (referrals a member needs) and
    -- "Gives" (referrals/help a member can offer). Stored in one table with a
    -- 'kind' discriminator so search can scan both in a single query.
    CREATE TABLE IF NOT EXISTS listings (
      id          INTEGER PRIMARY KEY AUTOINCREMENT,
      member_id   INTEGER NOT NULL REFERENCES members(id) ON DELETE CASCADE,
      kind        TEXT NOT NULL CHECK (kind IN ('ask', 'give')),
      title       TEXT NOT NULL,
      description TEXT NOT NULL DEFAULT '',
      tags        TEXT NOT NULL DEFAULT '',
      status      TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'closed')),
      created_at  TEXT NOT NULL DEFAULT (datetime('now'))
    );

    CREATE INDEX IF NOT EXISTS idx_members_group  ON members(group_id);
    CREATE INDEX IF NOT EXISTS idx_listings_member ON listings(member_id);
    CREATE INDEX IF NOT EXISTS idx_listings_kind   ON listings(kind);
  `);
}

module.exports = { db, init, DB_PATH };

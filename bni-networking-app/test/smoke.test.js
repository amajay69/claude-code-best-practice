'use strict';

// Dependency-free smoke test: boots the real Express app against a throwaway
// SQLite file and exercises the full flow — register/login, identity-aware
// creation, cross-app search, ownership enforcement, and the connect/respond
// feature. Run with `npm test`.
const assert = require('node:assert');
const http = require('node:http');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');

// Point the data layer at a temp DB BEFORE requiring the app.
const tmpDb = path.join(os.tmpdir(), `bni-test-${Date.now()}.db`);
process.env.BNI_DB_PATH = tmpDb;

const app = require('../server');

// Minimal cookie-aware HTTP client. Pass a `jar` object to capture and resend
// the session cookie across requests.
function request(server, method, urlPath, body, jar) {
  return new Promise((resolve, reject) => {
    const data = body ? JSON.stringify(body) : null;
    const { port } = server.address();
    const headers = { 'Content-Type': 'application/json' };
    if (jar && jar.cookie) headers.Cookie = jar.cookie;
    const req = http.request({ host: '127.0.0.1', port, path: urlPath, method, headers }, (res) => {
      const setCookie = res.headers['set-cookie'];
      if (jar && setCookie) jar.cookie = setCookie[0].split(';')[0];
      let raw = '';
      res.on('data', (c) => (raw += c));
      res.on('end', () => resolve({ status: res.statusCode, body: raw ? JSON.parse(raw) : null }));
    });
    req.on('error', reject);
    if (data) req.write(data);
    req.end();
  });
}

(async () => {
  const server = app.listen(0);
  let failed = false;
  try {
    const asha = {}; // cookie jar for member A
    const dan = {}; // cookie jar for member B

    // Register two members (each registration logs that member in).
    const reg1 = await request(server, 'POST', '/api/auth/register', {
      name: 'Asha', email: 'asha@test.com', password: 'pw123456', business_name: 'Web Studio',
    }, asha);
    assert.strictEqual(reg1.status, 201, 'registration should succeed');
    const ashaId = reg1.body.id;

    const reg2 = await request(server, 'POST', '/api/auth/register', {
      name: 'Dan', email: 'dan@test.com', password: 'pw123456', business_name: 'Tax Co',
    }, dan);
    assert.strictEqual(reg2.status, 201);

    // Duplicate email is rejected.
    const dup = await request(server, 'POST', '/api/auth/register', {
      name: 'X', email: 'asha@test.com', password: 'pw123456',
    });
    assert.strictEqual(dup.status, 409, 'duplicate email should 409');

    // /me reflects the session.
    const me = await request(server, 'GET', '/api/auth/me', null, asha);
    assert.strictEqual(me.body.id, ashaId, '/me should return the logged-in member');

    // Unauthenticated create is blocked.
    const noAuth = await request(server, 'POST', '/api/listings', { kind: 'ask', title: 'nope' });
    assert.strictEqual(noAuth.status, 401, 'creating without auth should 401');

    // Asha creates a post and an Ask — identity comes from the session.
    const post = await request(server, 'POST', '/api/posts', { content: 'Hello marketing world' }, asha);
    assert.strictEqual(post.status, 201);

    const ask = await request(server, 'POST', '/api/listings', {
      kind: 'ask', title: 'Need a marketing partner', description: 'branding help', tags: 'marketing',
    }, asha);
    assert.strictEqual(ask.status, 201);
    assert.strictEqual(ask.body.member_id, ashaId, 'listing should belong to the session member');

    // Cross-app search still works across types.
    const search = await request(server, 'GET', '/api/search?q=marketing');
    assert.ok(search.body.count >= 2, 'search should find post + ask');

    // Ownership: Dan cannot close Asha's listing.
    const forbidden = await request(server, 'PATCH', `/api/listings/${ask.body.id}`, { status: 'closed' }, dan);
    assert.strictEqual(forbidden.status, 403, 'non-owner cannot change listing');

    // Asha (owner) can.
    const closed = await request(server, 'PATCH', `/api/listings/${ask.body.id}`, { status: 'closed' }, asha);
    assert.strictEqual(closed.body.status, 'closed');

    // Connect: Dan responds to Asha's listing.
    const resp = await request(server, 'POST', `/api/listings/${ask.body.id}/responses`, {
      message: 'I can help with branding',
    }, dan);
    assert.strictEqual(resp.status, 201, 'response should be created');

    // Owner (Asha) can read responses.
    const ownerView = await request(server, 'GET', `/api/listings/${ask.body.id}/responses`, null, asha);
    assert.strictEqual(ownerView.body.owner, true);
    assert.strictEqual(ownerView.body.responses.length, 1, 'owner sees the response');

    // A logged-in member who has NOT responded and is NOT the owner is blocked.
    const eve = {};
    await request(server, 'POST', '/api/auth/register', { name: 'Eve', email: 'eve@test.com', password: 'pw123456' }, eve);
    const eveView = await request(server, 'GET', `/api/listings/${ask.body.id}/responses`, null, eve);
    assert.strictEqual(eveView.status, 403, 'unrelated member cannot view responses');

    // response_count surfaces on the listings collection.
    const listings = await request(server, 'GET', '/api/listings?kind=ask', null, asha);
    const theAsk = listings.body.find((l) => l.id === ask.body.id);
    assert.strictEqual(theAsk.response_count, 1, 'response_count should be reported');

    // Members endpoint must never leak password_hash.
    const members = await request(server, 'GET', '/api/members');
    assert.ok(members.body.every((m) => !('password_hash' in m)), 'password_hash must not leak');

    // Logout clears the session.
    await request(server, 'POST', '/api/auth/logout', null, asha);
    const afterLogout = await request(server, 'GET', '/api/auth/me', null, asha);
    assert.strictEqual(afterLogout.body, null, 'logout should clear the session');

    console.log('✓ All smoke tests passed');
  } catch (err) {
    failed = true;
    console.error('✗ Test failed:', err.message);
  } finally {
    server.close();
    fs.rmSync(tmpDb, { force: true });
    process.exit(failed ? 1 : 0);
  }
})();

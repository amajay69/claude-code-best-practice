'use strict';

// Dependency-free smoke test: boots the real Express app against a throwaway
// SQLite file, exercises the core flows (create group/member/post/listing) and
// the cross-app search, then asserts the results. Run with `npm test`.
const assert = require('node:assert');
const http = require('node:http');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');

// Point the data layer at a temp DB BEFORE requiring the app.
const tmpDb = path.join(os.tmpdir(), `bni-test-${Date.now()}.db`);
process.env.BNI_DB_PATH = tmpDb;

const app = require('../server');

function request(server, method, urlPath, body) {
  return new Promise((resolve, reject) => {
    const data = body ? JSON.stringify(body) : null;
    const { port } = server.address();
    const req = http.request(
      { host: '127.0.0.1', port, path: urlPath, method, headers: { 'Content-Type': 'application/json' } },
      (res) => {
        let raw = '';
        res.on('data', (c) => (raw += c));
        res.on('end', () => resolve({ status: res.statusCode, body: raw ? JSON.parse(raw) : null }));
      }
    );
    req.on('error', reject);
    if (data) req.write(data);
    req.end();
  });
}

(async () => {
  const server = app.listen(0);
  let failed = false;
  try {
    // Create a group
    const g = await request(server, 'POST', '/api/groups', { name: 'Test Chapter', description: 'hi' });
    assert.strictEqual(g.status, 201, 'group should be created');

    // Create a member in that group
    const m = await request(server, 'POST', '/api/members', {
      name: 'Jane Doe',
      business_name: 'Doe Designs',
      category: 'Design',
      group_id: g.body.id,
    });
    assert.strictEqual(m.status, 201, 'member should be created');

    // Post some business talk
    const p = await request(server, 'POST', '/api/posts', {
      member_id: m.body.id,
      content: 'Looking to connect with marketing folks!',
    });
    assert.strictEqual(p.status, 201, 'post should be created');

    // Create an Ask and a Give
    const ask = await request(server, 'POST', '/api/listings', {
      member_id: m.body.id,
      kind: 'ask',
      title: 'Need a marketing partner',
      description: 'Seeking referrals for branding work',
      tags: 'marketing,branding',
    });
    assert.strictEqual(ask.status, 201, 'ask should be created');

    const give = await request(server, 'POST', '/api/listings', {
      member_id: m.body.id,
      kind: 'give',
      title: 'Free logo review',
      tags: 'design',
    });
    assert.strictEqual(give.status, 201, 'give should be created');

    // Cross-app search should find the member, post, and ask for "marketing"
    const search = await request(server, 'GET', '/api/search?q=marketing');
    assert.strictEqual(search.status, 200);
    const types = search.body.results.map((r) => r.type).sort();
    assert.ok(search.body.count >= 2, 'search should return multiple results');
    assert.ok(types.includes('post'), 'search should match the post');
    assert.ok(types.includes('ask'), 'search should match the ask');

    // Filtered search (asks only)
    const askOnly = await request(server, 'GET', '/api/search?q=marketing&kind=ask');
    assert.ok(askOnly.body.results.every((r) => r.type === 'ask'), 'kind filter should restrict types');

    // Toggle listing status
    const patched = await request(server, 'PATCH', `/api/listings/${ask.body.id}`, { status: 'closed' });
    assert.strictEqual(patched.body.status, 'closed', 'listing status should update');

    // Validation: missing field returns 400
    const bad = await request(server, 'POST', '/api/groups', {});
    assert.strictEqual(bad.status, 400, 'missing name should 400');

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

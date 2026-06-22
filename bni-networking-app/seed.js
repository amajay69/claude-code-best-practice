'use strict';

// Populates the database with a few demo groups, members, business posts, and
// Asks/Gives so the app is immediately explorable. Run with: `npm run seed`.
// Safe to re-run: it clears existing rows first.
const { db, init } = require('./db');

init();

console.log('Clearing existing data...');
db.exec('DELETE FROM listings; DELETE FROM posts; DELETE FROM members; DELETE FROM groups;');

const insertGroup = db.prepare('INSERT INTO groups (name, description) VALUES (?, ?)');
const insertMember = db.prepare(
  'INSERT INTO members (name, business_name, category, email, group_id) VALUES (?, ?, ?, ?, ?)'
);
const insertPost = db.prepare('INSERT INTO posts (member_id, content) VALUES (?, ?)');
const insertListing = db.prepare(
  'INSERT INTO listings (member_id, kind, title, description, tags) VALUES (?, ?, ?, ?, ?)'
);

const groups = [
  ['Sunrise Chapter', 'Early-morning networking for founders and service pros.'],
  ['Metro Business Network', 'Downtown professionals across trades and consulting.'],
];
const groupIds = groups.map((g) => Number(insertGroup.run(g[0], g[1]).lastInsertRowid));

const members = [
  ['Asha Verma', 'Verma Web Studio', 'Web Development', 'asha@vermaweb.com', groupIds[0]],
  ['Daniel Cho', 'Cho Tax & Books', 'Accounting', 'dan@chotax.com', groupIds[0]],
  ['Priya Nair', 'Nair Interiors', 'Interior Design', 'priya@nairinteriors.com', groupIds[0]],
  ['Marcus Bell', 'Bell Legal', 'Law', 'marcus@belllegal.com', groupIds[1]],
  ['Sofia Ramos', 'Ramos Marketing', 'Marketing', 'sofia@ramosmktg.com', groupIds[1]],
  ['Tom Fisher', 'Fisher Plumbing', 'Trades', 'tom@fisherplumbing.com', groupIds[1]],
];
const memberIds = members.map((m) => Number(insertMember.run(...m).lastInsertRowid));

const posts = [
  [memberIds[0], 'Just launched a new e-commerce site for a local bakery — happy to share results!'],
  [memberIds[1], 'Tax season reminder: small businesses, get your quarterly filings in early.'],
  [memberIds[4], 'We helped a client triple their Instagram engagement in 60 days. Ask me how.'],
  [memberIds[5], 'Now offering emergency weekend plumbing call-outs across the metro area.'],
];
posts.forEach((p) => insertPost.run(...p));

const listings = [
  [memberIds[0], 'ask', 'Need an accountant for my growing studio', 'Looking for someone who handles freelancer/agency taxes.', 'accounting,tax,finance'],
  [memberIds[0], 'give', 'Free website audit for fellow members', 'I will review your site speed, SEO, and mobile UX at no cost.', 'web,seo,audit'],
  [memberIds[1], 'give', 'Bookkeeping setup for new businesses', 'Can get your QuickBooks or Xero configured properly.', 'accounting,bookkeeping,quickbooks'],
  [memberIds[2], 'ask', 'Seeking a marketing partner for showroom launch', 'Opening a new interior design showroom, need social + PR help.', 'marketing,pr,launch'],
  [memberIds[3], 'give', 'Free 30-min legal consult for members', 'Contracts, incorporation, IP basics — first call is on me.', 'law,contracts,legal'],
  [memberIds[4], 'ask', 'Referrals for B2B SaaS clients', 'We specialize in SaaS growth marketing and want intros.', 'marketing,saas,referrals'],
  [memberIds[5], 'give', 'Discounted plumbing for member offices', '15% off commercial plumbing for anyone in the network.', 'plumbing,trades,office'],
];
listings.forEach((l) => insertListing.run(...l));

console.log(
  `Seeded ${groups.length} groups, ${members.length} members, ${posts.length} posts, ${listings.length} listings.`
);

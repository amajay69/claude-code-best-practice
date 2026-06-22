# 🤝 BizConnect — BNI-style Networking App

A networking app for business groups, inspired by BNI. Members join **groups**,
share **business posts**, and publish structured **Asks** (referrals they need)
and **Gives** (help they can offer). A single search box scans the **entire
network** — members, posts, asks, and gives — so anyone can find the right
connection fast.

## Features

- **Groups / Chapters** — organize members into networking groups
- **Members directory** — name, business, category, email, group
- **Feed** — free-form business talk posts
- **Asks & Gives** — the heart of BNI: structured referral requests and offers, with tags and open/closed status
- **Cross-app search** — one query searches members, posts, asks, and gives, with an optional type filter
- **Zero-config persistence** — single-file SQLite database via Node's built-in `node:sqlite` (no native build step)

## Tech stack

| Layer    | Choice                                   |
|----------|------------------------------------------|
| Backend  | Node.js + Express                        |
| Database | SQLite (built-in `node:sqlite`)          |
| Frontend | Dependency-free vanilla HTML/CSS/JS SPA  |

## Getting started

```bash
cd bni-networking-app
npm install        # installs Express
npm run seed       # (optional) load demo groups, members, posts & listings
npm start          # serves the app at http://localhost:3000
```

Then open <http://localhost:3000>. Use the **＋** button to create groups,
members, posts, asks, and gives (the form adapts to the active tab), and the
top search bar to search across everything.

> Requires **Node 22.5+** (for the stable `node:sqlite` module).

## Project structure

```
bni-networking-app/
├── server.js          # Express app + REST API + cross-app search
├── db.js              # SQLite schema & connection (node:sqlite)
├── seed.js            # Demo data loader
├── public/
│   ├── index.html     # SPA shell
│   ├── styles.css     # Dark UI theme
│   └── app.js         # Client logic: views, search, create forms
└── test/
    └── smoke.test.js  # End-to-end API smoke test (no extra deps)
```

## Data model

- **groups** — `id, name, description, created_at`
- **members** — `id, name, business_name, category, email, group_id → groups`
- **posts** — `id, member_id → members, content, created_at`
- **listings** — `id, member_id → members, kind('ask'|'give'), title, description, tags, status('open'|'closed'), created_at`

Asks and Gives share one `listings` table with a `kind` discriminator, so the
search endpoint can scan both in a single query.

## API reference

| Method | Path                  | Description                                  |
|--------|-----------------------|----------------------------------------------|
| GET    | `/api/groups`         | List groups with member counts               |
| POST   | `/api/groups`         | Create a group                               |
| GET    | `/api/groups/:id`     | Group detail + its members                   |
| GET    | `/api/members`        | List members (with group name)               |
| POST   | `/api/members`        | Create a member                              |
| GET    | `/api/members/:id`    | Member detail + posts + listings             |
| GET    | `/api/posts`          | List business posts                          |
| POST   | `/api/posts`          | Create a post                                |
| GET    | `/api/listings`       | List asks/gives (`?kind=ask\|give`)          |
| POST   | `/api/listings`       | Create an ask or give                        |
| PATCH  | `/api/listings/:id`   | Update status (`open`/`closed`)              |
| GET    | `/api/search`         | Cross-app search (`?q=...&kind=...`)         |

### Search example

```bash
curl "http://localhost:3000/api/search?q=marketing"
# → matching members, posts, and asks/gives, each tagged with its `type`

curl "http://localhost:3000/api/search?q=accounting&kind=ask"
# → restrict results to Asks only
```

## Tests

```bash
npm test
```

Boots the real Express app against a throwaway SQLite file and exercises the
full create → search → update flow.

## Roadmap ideas

- User accounts & authentication, per-group membership permissions
- "Connect" / direct messaging between members on an Ask or Give
- Full-text search (SQLite FTS5) and tag-based filtering
- Notifications when a new Ask matches your Gives

# 🤝 BizConnect — BNI-style Networking App

A networking app for business groups, inspired by BNI. Members join **groups**,
share **business posts**, and publish structured **Asks** (referrals they need)
and **Gives** (help they can offer). A single search box scans the **entire
network** — members, posts, asks, and gives — so anyone can find the right
connection fast.

## Features

- **Groups / Chapters** — organize members into networking groups
- **Members directory** — name, business, category, email, group
- **Accounts & login** — members are the auth principal; passwords are scrypt-hashed and sessions are cookie-based (all via Node's built-in `node:crypto`)
- **Feed** — free-form business talk posts (attributed to the logged-in member)
- **Asks & Gives** — the heart of BNI: structured referral requests and offers, with tags and open/closed status
- **Connect** — respond to anyone's Ask/Give with a message; the listing owner sees responses to follow up
- **Cross-app search** — one query searches members, posts, asks, and gives, with an optional type filter
- **Zero-config persistence** — single-file SQLite database via Node's built-in `node:sqlite` (no native build step)

## Tech stack

| Layer    | Choice                                          |
|----------|-------------------------------------------------|
| Backend  | Node.js + Express                               |
| Auth     | `node:crypto` (scrypt hashing + cookie sessions)|
| Database | SQLite (built-in `node:sqlite`)                 |
| Frontend | Dependency-free vanilla HTML/CSS/JS SPA         |

## Getting started

```bash
cd bni-networking-app
npm install        # installs Express
npm run seed       # (optional) load demo data — groups, members, posts, asks/gives, responses
npm start          # serves the app at http://localhost:3000
```

Then open <http://localhost:3000>. You'll land on a **login / sign-up** screen.

**Demo login** (after `npm run seed`): any seeded member email — e.g.
`asha@vermaweb.com` — with password `password123`.

Once logged in, use the **＋** button to create groups, posts, asks, and gives
(the form adapts to the active tab and uses your identity automatically), the
**Respond / Connect** button on others' listings to reach out, and the top
search bar to search across everything.

> Requires **Node 22.5+** (for the stable `node:sqlite` module).

## Deploy to the cloud (Railway)

Host it so you can use it from your phone or any device at a public URL. These
steps are all doable from a browser — no terminal required.

### One-tap deploy

Once you've published this app as a Railway template (steps below), drop your
template code into this button and anyone can deploy it in a single tap:

```markdown
[![Deploy on Railway](https://railway.com/button.svg)](https://railway.com/new/template/YOUR_TEMPLATE_CODE?utm_medium=integration&utm_source=button&utm_campaign=bizconnect)
```

[![Deploy on Railway](https://railway.com/button.svg)](https://railway.com/new/template/YOUR_TEMPLATE_CODE)

> Replace `YOUR_TEMPLATE_CODE` with the code Railway gives you when you publish.

**Publish your template (≈2 minutes, captures root dir + volume + env vars so
the button is truly one-tap):**

1. Deploy the app once using the manual steps below.
2. In your Railway project, open the service → **⋯** menu → **Create Template**
   (or go to <https://railway.com/compose>).
3. Confirm the captured settings: **Root Directory** `bni-networking-app`, the
   **/data** volume, and the variables `BNI_DB_PATH`, `NODE_ENV`,
   `SEED_ON_EMPTY`.
4. **Publish** → Railway gives you a URL like
   `https://railway.com/new/template/abc123`. The part after `/template/` is
   your code — paste it into the button above.

That published button captures everything, so a one-tap deploy needs **zero**
manual configuration. The manual steps below are the first-time path.

### Manual deploy

1. **New project** → in the [Railway](https://railway.app) dashboard choose
   **Deploy from GitHub repo** and pick `claude-code-best-practice`.
2. **Pick the branch** `claude/bni-networking-app-qoyr5h` in the service settings.
3. **Set the Root Directory** to `bni-networking-app` (Settings → *Root
   Directory*). This app is a subfolder, so Railway must build from there.
   Build/start are auto-detected from `package.json` (`npm install` / `npm start`).
4. **Add a Volume** for persistent data (Settings → *Volumes*) and mount it at
   `/data`. Without a volume the SQLite file is wiped on every redeploy.
5. **Set environment variables** (Settings → *Variables*):

   | Variable        | Value         | Why |
   |-----------------|---------------|-----|
   | `BNI_DB_PATH`   | `/data/bni.db`| Store the database on the persistent volume |
   | `NODE_ENV`      | `production`  | Enables the `Secure` session cookie (HTTPS) |
   | `SEED_ON_EMPTY` | `true`        | Loads demo data on first boot only (optional) |

6. **Generate a domain** (Settings → *Networking* → *Generate Domain*). Railway
   sets `PORT` automatically and the app already binds to it. Open the URL on
   your phone — done.

> **Tip:** once you've created your own real account and data, remove the
> `SEED_ON_EMPTY` variable so it never reseeds. (It only ever seeds an *empty*
> database, but removing it makes the intent clear.)

The same env vars work on Render, Fly.io, or any Node host — only the
volume/disk setup differs per platform.

## Project structure

```
bni-networking-app/
├── server.js          # Express app + REST API + cross-app search
├── auth.js            # scrypt hashing, cookie sessions, auth middleware
├── db.js              # SQLite schema, migration & connection (node:sqlite)
├── seed.js            # Demo data loader (seed / seedIfEmpty)
├── railway.json       # Railway build & deploy config
├── .nvmrc             # Pins Node 22 for the platform builder
├── public/
│   ├── index.html     # SPA shell (auth screen + app)
│   ├── styles.css     # Dark UI theme
│   └── app.js         # Client logic: auth, views, search, connect
└── test/
    └── smoke.test.js  # End-to-end API smoke test (no extra deps)
```

## Data model

- **groups** — `id, name, description, created_at`
- **members** — `id, name, business_name, category, email, password_hash, group_id → groups`
- **posts** — `id, member_id → members, content, created_at`
- **listings** — `id, member_id → members, kind('ask'|'give'), title, description, tags, status('open'|'closed'), created_at`
- **responses** — `id, listing_id → listings, member_id → members, message, created_at`
- **sessions** — `token, member_id → members, created_at`

Asks and Gives share one `listings` table with a `kind` discriminator, so the
search endpoint can scan both in a single query. Members double as user
accounts — `password_hash` is never returned by any endpoint.

## API reference

Endpoints marked 🔒 require an authenticated session cookie.

| Method | Path                          | Description                                  |
|--------|-------------------------------|----------------------------------------------|
| POST   | `/api/auth/register`          | Create an account (member) and log in        |
| POST   | `/api/auth/login`             | Log in, set session cookie                   |
| POST   | `/api/auth/logout`            | Destroy the session                          |
| GET    | `/api/auth/me`                | Current member, or `null`                    |
| GET    | `/api/groups`                 | List groups with member counts               |
| POST   | `/api/groups` 🔒              | Create a group                               |
| GET    | `/api/groups/:id`             | Group detail + its members                   |
| GET    | `/api/members`                | List members (no password hashes)            |
| GET    | `/api/members/:id`            | Member detail + posts + listings             |
| GET    | `/api/posts`                  | List business posts                          |
| POST   | `/api/posts` 🔒              | Create a post (as the logged-in member)      |
| GET    | `/api/listings`               | List asks/gives (`?kind=ask\|give`) + counts |
| POST   | `/api/listings` 🔒          | Create an ask or give                        |
| PATCH  | `/api/listings/:id` 🔒      | Owner-only: update status (`open`/`closed`)  |
| POST   | `/api/listings/:id/responses` 🔒 | Respond / connect to a listing           |
| GET    | `/api/listings/:id/responses` 🔒 | Owner/responder: view responses          |
| GET    | `/api/search`                 | Cross-app search (`?q=...&kind=...`)         |

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
full flow: register/login, identity-aware creation, cross-app search,
ownership enforcement, and the connect/respond feature.

## Roadmap ideas

- Per-group membership requests & approvals (gate listings to your group)
- Two-way threads on a response (reply back to a connection)
- Full-text search (SQLite FTS5) and tag-based filtering
- Notifications when a new Ask matches your Gives
- Rate limiting & CSRF token on top of the SameSite cookie

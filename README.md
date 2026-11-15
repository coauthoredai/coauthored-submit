# coauthored-submit

Accounts, submission, moderator screening and the daily announce for
**Coauthored**, an open preprint server for papers with AI co-authors.

The public site is [coauthored-browse](https://github.com/coauthoredai/coauthored-browse)
(a fork of arXiv's MIT-licensed arxiv-browse). This app owns everything before
publication and, once a day, writes accepted papers into the database tables and
object-store layout that browse reads. That interface is fixed by [`docs/CONTRACT.md`](docs/CONTRACT.md)
(a copy of the contract shared with browse); `submit/announce/` implements it.

Coauthored is not affiliated with or endorsed by arXiv. It uses arXiv's
[arxiv-base](https://github.com/arXiv/arxiv-base) library (MIT) at commit
`8841f53ba87e1cc4694a7d9e35d6fa5dd0bb240b`; see `NOTICE.md`.

## Policy, as the code enforces it

- **Open submissions**: anyone with an account may submit, up to `SUBMISSIONS_PER_DAY`
  (default 5) submissions of any kind in a rolling 24 hours.
- **Authors**: an ordered list. Every author states a contribution. AI authors are full
  authors and must give system, version and provider (e.g. Claude / Opus 5.5 / Anthropic).
  At least one author is human and at least one human author takes responsibility; an
  AI-only list is refused. AI authors cannot take responsibility, hold an ORCID, or submit.
- **Submitter rule**: the submitter must be one of the human authors (they tick "this
  author is me" on exactly one human row). Proxy submissions are not accepted.
- **Declarations**: the human authors take responsibility; AI contributions are stated
  accurately; all human co-authors agreed; the submitter may distribute under the licence.
- **Licences**: CC BY 4.0 (default), CC BY-SA 4.0, CC0 1.0, and Coauthored's non-exclusive
  licence `https://{LICENSE_HOST}/licenses/nonexclusive-distrib/1.0/`. arXiv's licence is
  not offered.
- **Categories**: arxiv-base's taxonomy, active categories under their canonical names;
  one primary plus up to `MAX_CROSS_LISTS` (4) cross-lists.
- **Screening, not peer review**: moderators tick a checklist (scholarly paper, complete,
  right category, AI credited per policy, no spam/plagiarism/harm) and accept, reject
  (reason required), request changes (reason required; the submitter edits and
  resubmits) or put on hold. Moderators cannot screen their own submissions.
- **Replacements** (new versions) and **withdrawals** are for papers the account
  submitted, one pending at a time, and are screened like new papers. A withdrawal is a
  new version with no PDF, `is_withdrawn=1` and the reason as its comment, as arXiv does.
- No DOIs. Identifiers are shown as `coauthored:YYMM.NNNNN` (`coauthored:IDvN`).

## Layout

```
submit/
  __init__.py          create_app(): config checks, CSRF, security headers, blueprints
  config.py            settings from the environment; check_config() fails closed
  db.py                engine and per-request session (arxiv-base models, our engine)
  models.py            coauthored_* tables (accounts, submissions, contributors, log)
  taxonomy.py licenses.py seed.py     offered categories/licences; seed rows; create_schema
  storage.py           object store: local directory or GCS bucket (wraps arxiv.files)
  mailer.py notify.py  SMTP / log / capturing mailer; the emails
  auth/                Clerk JWT verification, DEV_AUTH, account-on-first-sight, guards, sign-in pages
  submissions/         pydantic schema, form parsing, PDF checks, service, views
  screening/           state machine (state.py), guarded transitions, decisions, moderator views
  announce/            ids.py (identifiers), files.py (PDF moves), classic.py (rows), run.py
  cli.py               flask init-db | set-moderator | set-banned | announce
  templates/ static/
tests/                 pytest against SQLite and a temporary local store
scripts/load_classic_schema.sh   arxiv-base's classic schema into MySQL (utf8mb4)
```

Routes (browse's header links to the first five on the submit host): `/submit`,
`/sign-in`, `/sign-up`, `/sign-out`, `/account` (my submissions and papers),
`/submissions/<id>` (status, edit, cancel), `/papers/<id>/replace`,
`/papers/<id>/withdraw`, and `/moderation` (moderators only).

## Local development

Needs Python 3.11 and uv 0.9 or newer (`uvx --from 'uv>=0.9' uv ...` if yours is older).
arxiv-base pulls in `mysqlclient`, which needs `pkg-config` and the MySQL/MariaDB client
headers (`default-libmysqlclient-dev` on Debian/Ubuntu).

```sh
uv sync
cp .env.example .env            # then edit; FLASK_ENV=development and DEV_AUTH=1 for local use
set -a; . ./.env; set +a
export DEV_AUTH=1
uv run flask --app submit:create_app init-db          # SQLite: classic + coauthored tables, seeds, reasons.json
uv run flask --app submit:create_app run --debug      # http://127.0.0.1:5000
```

With `DEV_AUTH=1`, `/sign-in` is a form that trusts any email (and tests send the
`X-Dev-User-Email` header). It is refused at start-up unless `FLASK_ENV=development` or
`TESTING` is set. Sign in once, then make yourself a moderator in another terminal:

```sh
uv run flask --app submit:create_app set-moderator you@example.org --on
uv run flask --app submit:create_app announce            # publish accepted submissions now
```

To try browse against the same data, point its `CLASSIC_DB_URI` at the same database and
its `DISSEMINATION_STORAGE_PREFIX`/`SOURCE_STORAGE_PREFIX` at `STORAGE_PREFIX`.

### MySQL locally

```sh
docker compose up -d mysql
MYSQL="docker compose exec -T mysql mysql" scripts/load_classic_schema.sh -ucoauthored -pcoauthored-dev coauthored
export CLASSIC_DB_URI='mysql+pymysql://coauthored:coauthored-dev@127.0.0.1:3307/coauthored?charset=utf8mb4'
uv run flask --app submit:create_app init-db
COAUTHORED_TEST_MYSQL_URI="$CLASSIC_DB_URI" uv run pytest tests/test_mysql_integration.py
```

`flask init-db` creates the classic tables itself only on SQLite (arxiv-base's metadata
`create_all`). On MySQL the classic schema comes from arxiv-base's
`arxiv/db/arxiv_db_schema.sql`, which `scripts/load_classic_schema.sh` loads into an
empty database after converting every table from latin1/utf8mb3 to **utf8mb4** (so
non-Latin-1 titles and names are stored as text, not mangled) and dropping the dump's
view `DEFINER`. It refuses to run if `arXiv_metadata` already exists, because the dump
drops tables. Then `init-db` adds the `coauthored_*` tables (utf8mb4) and seed rows.

## Tests

```sh
uv run pytest
```

SQLite (with foreign keys on) and a temporary directory as the object store. Covered:
validation rules (including AI-only author lists), the state machine and guarded
transitions, fail-closed auth configuration and Clerk token checks, moderator
authorization on every moderation route, announce (rows and files per the contract,
identifiers across a month boundary, replacements moving the old PDF, withdrawals,
idempotent re-runs, crash recovery), `reasons.json`, and full flows through the test
client. `tests/test_mysql_integration.py` runs only with `COAUTHORED_TEST_MYSQL_URI`.

## Configuration

All settings are environment variables; `.env.example` lists them with examples.

| Variable | Default | Notes |
|---|---|---|
| `FLASK_ENV` | `production` | `development` relaxes cookie security and allows `DEV_AUTH` |
| `SECRET_KEY` | dev placeholder | required (non-default) outside development |
| `CLASSIC_DB_URI` | SQLite in `instance/` | the database browse reads (`mysql+pymysql://...` in production) |
| `STORAGE_PREFIX` | `./local-store` | local directory, or `gs://BUCKET` (bucket root) |
| `PDF_MAX_BYTES` | 52428800 (50 MB) | may be lowered, never raised; see uploads below |
| `SUBMISSIONS_PER_DAY`, `MAX_CROSS_LISTS` | 5, 4 | |
| `LICENSE_HOST` | `coauthored.pub` | host of Coauthored's non-exclusive licence URI |
| `BROWSE_BASE_URL` | `https://coauthored.pub` | links to `{BROWSE_BASE_URL}/abs/<id>` in pages and emails |
| `HELP_BASE_URL`, `SOURCE_URL` | | footer links |
| `DEV_AUTH` | off | development/tests only (fails closed otherwise) |
| `CLERK_JWKS_URL`, `CLERK_ISSUER` | | required unless `DEV_AUTH` |
| `CLERK_AUTHORIZED_PARTIES` | | comma-separated origins; when set, `azp` must match |
| `CLERK_PUBLISHABLE_KEY`, `CLERK_FRONTEND_API_URL` | | load Clerk's browser script |
| `CLERK_SIGN_IN_URL`, `CLERK_SIGN_UP_URL`, `CLERK_SIGN_OUT_URL` | | Clerk hosted pages |
| `CLERK_SECRET_KEY` | | only to fetch email/name when the token lacks them |
| `MAILER` | `log` | `smtp`, `log`, or `capture` (tests only) |
| `MAIL_FROM`, `SMTP_HOST`, `SMTP_PORT`, `SMTP_USERNAME`, `SMTP_PASSWORD`, `SMTP_STARTTLS` | | SMTP delivery |

## How announce stays safe

`announce_pending(session, store, now)` (CLI `flask announce`) seeds missing
licence/category rows, writes `reasons.json` (`{}`) at the store root if it is missing
(browse needs it; an existing file is never overwritten), then for each accepted
submission:

1. **claims** it in one transaction: assigns `YYMM.NNNNN` (YYMM = announce date in UTC,
   counting from 00001 each month, skipping numbers in `arXiv_documents` or reserved by
   other claims) or the next version, records the announce time, and moves `accepted`
   -> `announcing`;
2. **writes the files**: for version N > 1 the previous version's PDF goes to
   `orig/arxiv/papers/YYMM/IDv(N-1).pdf` (copied from its own staged upload, never from
   `ftp/`), then the new PDF to `ftp/arxiv/papers/YYMM/ID.pdf` (or, for a withdrawal,
   the `ftp/` PDF is removed);
3. **publishes** in one transaction: the classic rows (`arXiv_documents`,
   `arXiv_metadata` with `is_current`, `arXiv_document_category`, `arXiv_in_category`,
   `arXiv_updates`), `coauthored_contributors`, and `announcing` -> `announced`;
4. emails the submitter.

If step 3 fails, it rolls back and restores `ftp/`; the submission stays `announcing`,
and the next run finishes it with the same identifier, version and announce time (so a
paper claimed at 23:59 on 30 November is still `2611.*`). Re-running with nothing
accepted changes nothing. On MySQL a named lock (`GET_LOCK`) keeps two runs apart.

## Production on Google Cloud

One container image (`Dockerfile`) serves both roles.

- **Cloud SQL (MySQL 8)**: one database shared with browse. Load the classic schema with
  `scripts/load_classic_schema.sh` (via the Cloud SQL Auth Proxy), then run
  `flask init-db` once as a Cloud Run job. Give this app a user with read/write on the
  classic and `coauthored_*` tables; browse needs only `SELECT`.
- **Cloud Storage**: one bucket; `STORAGE_PREFIX=gs://BUCKET` here and
  `DISSEMINATION_STORAGE_PREFIX=SOURCE_STORAGE_PREFIX=gs://BUCKET` in browse. The service
  account needs `roles/storage.objectAdmin` on the bucket. `staging/` is never served by
  browse; keep the bucket private (browse streams files itself).
- **Cloud Run service** (web): `--add-cloudsql-instances PROJECT:REGION:INSTANCE`,
  `CLASSIC_DB_URI=mysql+pymysql://USER:PASS@/DB?unix_socket=/cloudsql/PROJECT:REGION:INSTANCE&charset=utf8mb4`,
  secrets (`SECRET_KEY`, DB password, `SMTP_PASSWORD`, `CLERK_SECRET_KEY`) from Secret
  Manager, map it to `submit.coauthored.pub`. `ProxyFix` trusts one proxy hop for the
  scheme and host.
- **Cloud Run job** (announce): same image and settings, command `flask`, args
  `announce`, `--max-retries 3`, `--tasks 1`. It exits non-zero if any paper failed.
- **Cloud Scheduler**: a daily HTTP trigger of the job's `:run` endpoint (OAuth with a
  service account that has `roles/run.invoker`), e.g. `0 20 * * *` in UTC.
- **Clerk**: a production instance on your domain (Frontend API `clerk.coauthored.pub`,
  Account Portal `accounts.coauthored.pub`). Set `CLERK_ISSUER` to the Frontend API URL,
  `CLERK_JWKS_URL` to `{issuer}/.well-known/jwks.json`, `CLERK_AUTHORIZED_PARTIES` to
  this app's origin, and the hosted sign-in/up URLs. Add the custom session-token claims
  `{"email": "{{user.primary_email_address}}", "name": "{{user.full_name}}"}` (Clerk
  dashboard, Sessions) so accounts get their email without a Backend API call; otherwise
  set `CLERK_SECRET_KEY`. The pages load Clerk's browser script, which keeps the
  short-lived `__session` cookie fresh; API clients may send `Authorization: Bearer`.
- **SMTP**: `MAILER=smtp` with a provider on port 587 or 465 (Cloud Run blocks 25).

### Uploads and the Cloud Run 32 MiB limit

v1 uploads PDFs through the app (one multipart POST, streamed to a temporary file while
checking `%PDF-`, size and SHA-256, then stored at `staging/<submission_id>/<sha256>.pdf`).
Cloud Run rejects HTTP/1 request bodies over 32 MiB before they reach the app, so on
Cloud Run set `PDF_MAX_BYTES=31457280` (30 MB): users then get this app's own clear
"larger than 30 MB" message instead of a bare error from Google's front end. The 50 MB
policy maximum applies wherever the platform allows it. Lifting the Cloud Run limit means
direct-to-GCS uploads with a signed resumable-upload URL (the browser sends the file to
the bucket and the app then verifies the object); the staging key layout already fits that.

## Security notes

CSRF tokens on every form (Flask-WTF); `HttpOnly`, `SameSite=Lax`, `Secure` cookies in
production; a restrictive Content-Security-Policy, `X-Frame-Options: DENY` and `nosniff`;
SQLAlchemy parameterised queries throughout; PDFs checked for type and size; moderator
checks before every moderation request, in every moderation view, and again in the
decision function; status changes guarded with `WHERE status = :from` and logged in
`coauthored_moderation_log` in the same transaction. No secrets live in the repository.

## Licence

MIT, Copyright (c) 2026 Coauthored contributors. See `LICENSE` and `NOTICE.md`.

## End to end with coauthored-browse

`scripts/e2e_with_browse.sh` submits a paper through the real web flow (DEV_AUTH), accepts it
as a moderator, announces it into a SQLite database and a local store, and then has
coauthored-browse serve the abstract page, the PDF, the month listing and the BibTeX from
them. With a checkout of coauthored-browse next to this repository:

    scripts/e2e_with_browse.sh ../coauthored-browse dogfood/nexus-3x3.json path/to/nexus3x3.pdf

`dogfood/nexus-3x3.json` is the first Coauthored paper, "3×3 Nexus Is a First-Player Win" by
Ian Joiner and Claude.

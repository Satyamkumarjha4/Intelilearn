# Local setup

Everything runs locally with **Docker Compose**: Postgres, Redis, the Django API, the Celery worker, the Celery beat scheduler, and the Next.js app. The Python backend is managed with **uv** and the frontend with **bun**. Deployment is out of scope.

## Prerequisites

| Tool | Why |
|---|---|
| Docker + Docker Compose v2 (2.24+) | Runs the whole stack |
| uv and bun *(optional on the host)* | Only needed to add dependencies or run tools outside Docker |
| A Supabase project *(optional)* | Hosted Postgres. Without it, the docker Postgres is used. |

## 1. Configure: one `.env` for everything

```bash
make env          # copies .env.example → .env (keeps an existing one)
```

The root `.env` is the **single source of configuration**. Django reads it, `docker-compose.yml` interpolates it, and `next.config.ts` loads it. Every variable has a development default, so the stack and the tests also run with **no `.env`** (this is what CI relies on).

| Group | Variables | Default |
|---|---|---|
| Host ports | `BIND_ADDRESS`, `BACKEND_PORT`, `FRONTEND_PORT`, `POSTGRES_PORT`, `REDIS_PORT` | 127.0.0.1 (not reachable from your LAN), 8000, 3000, 5432, 6379 |
| Django | `DJANGO_SECRET_KEY`, `DJANGO_DEBUG`, `DJANGO_ALLOWED_HOSTS`, `DJANGO_CSRF_TRUSTED_ORIGINS`, `LOG_LEVEL`, `MEDIA_ROOT` | dev key, false, localhost…, derived from ports, INFO, `backend/media` |
| Auth | `JWT_ACCESS_MINUTES`, `JWT_REFRESH_DAYS`, `AUTH_COOKIE_SECURE` (also makes Django's session and CSRF cookies secure) | 30, 7, false |
| Rate limits | `AUTH_THROTTLE_RATE`, `AUTH_ACCOUNT_THROTTLE_RATE`, `AUTH_REFRESH_THROTTLE_RATE`, `TRUSTED_PROXY_COUNT` | 20/min, 10/min, 60/min, 1 |
| Local Postgres | `POSTGRES_HOST`, `POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD`, `DB_CONN_MAX_AGE` | localhost, lessoncrafter ×3, 60 |
| Supabase | `SUPABASE_DATABASE_URL`, `SYNC_LOCAL_TO_SUPABASE` | empty, true |
| Redis | `REDIS_HOST`, `REDIS_PASSWORD` | localhost, none |
| Frontend | `DJANGO_API_ORIGIN`, `NEXT_PUBLIC_BACKEND_URL` | `http://localhost:${BACKEND_PORT}` |
| Frontend | `NEXT_PUBLIC_DJANGO_ADMIN_URL` (the console's "Open in Django admin" links) | `http://localhost:${BACKEND_PORT}/admin` |
| LLM keys | `GEMINI_API_KEY`, `GROQ_API_KEY`, `OPENAI_API_KEY`, `ANTHROPIC_API_KEY` | empty. The default registry uses Gemini and Groq. |
| Reasoning budgets | `LLM_REASONING_BUDGET_LOW/MEDIUM/HIGH` | 2048 / 8192 / 24576 |
| Media sources | `WIKIMEDIA_API_URL`, `OPENVERSE_API_URL`, `GIPHY_API_URL`, `MEDIA_ALLOW_PRIVATE_HOSTS` | the public services, false |
| Console (staff API) | `CONSOLE_MONTHLY_BUDGET_USD`, `CONSOLE_THROTTLE_RATE` | 25, 120/min |
| Landing page | `PUBLIC_PAGES_THROTTLE_RATE` (testimonials and prices, per address) | 60/min |
| Onboarding | `TOPIC_SUGGESTIONS_THROTTLE_RATE`, `ONBOARDING_SUGGESTION_TTL_S` | 30/min, 30 days |
| Lesson flow | `FLOW_RUN_LOCK_TTL_S`, `LESSON_CREATE_THROTTLE_RATE`, `SSE_HEARTBEAT_S`, `SANDBOX_DIR`, `NODE_BINARY`, `SANDBOX_CHECK_TIMEOUT_S`, `SANDBOX_RENDER_TIMEOUT_S`, `SANDBOX_PAGE_TIMEOUT_MS`, `GIPHY_API_KEY`, `MEDIA_URL_TTL_S` | 600, 30/hour, 30/hour, 15, `<repo>/sandbox`, node, 30, 180, 8000, empty, 21600 (6 h) |
| Credits and payments (names are in `.env.example`, all commented) | `ACTION_GATE`, `ACTIVITY_SINK`, `PAYMENT_GATEWAYS_ENABLED`, `PAYMENT_DEFAULT_GATEWAY`, `STRIPE_PUBLISHABLE_KEY`, `STRIPE_SECRET_KEY`, `STRIPE_WEBHOOK_SECRET`, `RAZORPAY_KEY_ID`, `RAZORPAY_KEY_SECRET`, `RAZORPAY_WEBHOOK_SECRET`, `PAYMENT_RETURN_BASE_URL`, `PAYMENTS_LIVE_MODE`, `PAYMENT_ALLOW_FAKE_GATEWAY`, `PAYMENT_FAKE_GATEWAY_SECRET`, `USD_INR_RATE`, `CREDITS_QUOTE_THROTTLE_RATE`, `CREDITS_BALANCE_THROTTLE_RATE`, `PAYMENT_ORDER_THROTTLE_RATE`, `PAYMENT_STATUS_THROTTLE_RATE`, `PAYMENT_WEBHOOK_THROTTLE_RATE` | the credit gate, the credits sink, none enabled, stripe, empty keys (the Stripe test keys go in your `.env`, which is not committed), `http://localhost:${FRONTEND_PORT}`, false, false, a development value (used only where the fake gateway is allowed), 85, 120/min, 240/min, 10/hour, 60/min, 600/min |
| Offline walk-through | `FAKE_LLM_API_KEY` | empty (any value; not a secret) |

- The `POSTGRES_HOST`, `POSTGRES_PORT`, `REDIS_HOST`, and `REDIS_PORT` values in `.env` describe how the **host** reaches the services. Inside docker, compose overrides them with the service names and internal ports (`db:5432`, `redis:6379`).
- **Changing `POSTGRES_USER`, `POSTGRES_PASSWORD`, or `POSTGRES_DB` after the first start** has no effect on the existing `postgres-data` volume. Postgres only applies them when it initialises an empty volume. To apply new credentials to a volume holding nothing you need, run `docker compose down && docker volume rm lessoncrafter_postgres-data`. Otherwise, change them with SQL (`ALTER USER …`).

## 2. Run

```bash
make up            # = docker compose up --build
```

On start, `make up` also recreates the frontend's anonymous `node_modules` and `.next` volumes (removing the old ones), so new packages are picked up. On start, `backend` runs `manage.py bootstrap`: it migrates the active database, first syncing to Supabase when that's configured (see below), then creates the LangGraph checkpoint tables (`manage.py setup_checkpointer`, safe to repeat). Code changes reload automatically: uvicorn `--reload` for the API, `watchfiles` for the Celery worker, and Turbopack for Next.js. Postgres and Redis data persist in the `postgres-data` and `redis-data` volumes.

| URL | What |
|---|---|
| `http://localhost:${FRONTEND_PORT}` | App. `/` is the public landing page; health is only at `/api/health`. |
| `http://localhost:${BACKEND_PORT}/api/docs` | **Swagger UI** |
| `http://localhost:${BACKEND_PORT}/api/redoc` | ReDoc |
| `http://localhost:${BACKEND_PORT}/api/schema` | OpenAPI 3 schema (YAML; add `Accept: application/json` for JSON) |
| `http://localhost:${BACKEND_PORT}/api/health` | Health JSON (`200` ok, `503` degraded) |
| `http://localhost:${FRONTEND_PORT}/console` | The staff console (usage and cost, lesson runs, models and routing, learners, change log). Only a user with `is_staff` can open it; anyone else sees a not-found page. `make superuser` makes one. |
| `http://localhost:${BACKEND_PORT}/admin/` | Django admin (run `make superuser` first) |

### The scheduler (`beat`)

`beat` is a service beside `worker`: it wakes on the schedule in `CELERY_BEAT_SCHEDULE` (`backend/config/settings.py`) and queues each periodic task for the worker to run. It runs no task itself. The schedule runs **`credits.tick` every hour** (start the plan periods that are due and end those that are over, write off lapsed credits, release reserves nothing will settle, audit the credit ledger; a ledger break is logged as an error) and will gain a five-minute `payments.reconcile` with the payments phase. Rules:

- **Run exactly one.** A second `beat` queues every task twice. Every task is written to be harmless when it runs twice, but do not rely on that: `docker compose ps` should list one `beat`. Do not scale it (`--scale beat=2`).
- It keeps its schedule bookkeeping in `/tmp` inside the container, so a restart loses nothing that matters; a task that was due while it was down runs on the next tick, not in a burst.
- `make beat-log` follows its log. Like the worker, it restarts when a Python file changes (`watchfiles`).
- The browser-test stack (`make e2e`) starts its own `beat`, with the same blanked keys as its worker.

## 3. Databases: local Postgres and Supabase

Supabase is optional and off by default: leave `SUPABASE_DATABASE_URL` empty and everything uses the docker `db` Postgres. The rest of this section only matters if you set it.

| `SUPABASE_DATABASE_URL` | `default` database | What happens on backend start |
|---|---|---|
| empty | docker `db` | `migrate` |
| set | Supabase | Migrate the local `db`, migrate Supabase, then **copy local rows Supabase doesn't have** |

About the sync (`backend/core/sync.py`, also available as `make sync-supabase`):

- **Insert-only.** It copies rows whose primary key is missing on Supabase. It never updates or deletes, so data created directly in Supabase is never overwritten. It is safe to run on every start.
- Models are copied in dependency order. Links to content types, permissions, and other models with natural keys are resolved by natural key. Many-to-many links travel with each newly copied object.
- A row that clashes on a unique field (for example, the same email under another id) is skipped and reported as a conflict. It doesn't stop the sync.
- Primary-key sequences on Supabase are reset afterwards.
- Content types, permissions, sessions, and admin log entries are not copied: `migrate` creates the first two, and the last two are ephemeral.
- Set `SYNC_LOCAL_TO_SUPABASE=false` to skip it.

Getting the Supabase URL: in the dashboard, go to **Connect** and copy the **Session pooler** string (port 5432). Append `?sslmode=require`. Do **not** use the transaction pooler (6543): Django, and later the LangGraph checkpointer, need session features.

**The public Data API is not locked down yet.** The script that would enable row-level security with no policies on every table (the checkpoint tables too) is not written (see [roadmap.md](../process/roadmap.md)), so do it by hand in the Supabase SQL editor before using a real project: `ALTER TABLE <name> ENABLE ROW LEVEL SECURITY;` for each table. Django connects as `postgres` and bypasses RLS.

## 4. Model registry (once)

```bash
docker compose exec backend python manage.py seed_registry   # Gemini + Groq defaults; on a registry that has bindings it only binds nodes that have none
docker compose exec backend python manage.py seed_registry --profile cheap --force   # cheapest models only, to try the flow
docker compose exec backend python manage.py check           # warns about nodes without a usable model or API key
docker compose exec backend python manage.py probe_models    # real calls: every bound model, each declared capability
docker compose exec backend python manage.py probe_models --node learner.assess   # plus one call through a node's chain
```

`probe_models` exits non-zero when a check fails, and API keys never appear in its output.

To design the landing page against a full "What learners say" section, make three placeholder testimonials on your own machine (it refuses unless `DEBUG` is on, and what it makes are samples: unpublished, with no consent, and never shown on the public page, whatever `DEBUG` is; running it again adds nothing):

```bash
docker compose exec backend python manage.py seed_sample_testimonials
```

Real testimonials are added, published and ordered in the console (**Testimonials**); with none published, the landing page shows the maker's note.

Tune models, fallbacks, and parameters in the admin under **LLM model registry**. Share a tuned setup with `manage.py export_registry --output registry.json` and `seed_registry --file registry.json`. See [model-registry.md](../architecture/model-registry.md).

## 5. Run a lesson from the terminal

With models bound (section 4) and a user registered, `manage.py flow` drives the whole flow without a browser:

```bash
docker compose exec backend python manage.py flow start "Binary search" --email you@example.com --inline
docker compose exec backend python manage.py flow answer <lesson> diagnostic --correct 5 --inline   # first 5 right, rest wrong
docker compose exec backend python manage.py flow choose <lesson> cheat_sheet --inline    # after a perfect diagnostic
docker compose exec backend python manage.py flow sheet <lesson> revision_sheet --inline   # another sheet later
docker compose exec backend python manage.py flow show <lesson>        # stage, route, scores, assessment, runs (--json for rows)
docker compose exec backend python manage.py flow retry <lesson> --inline
docker compose exec backend python manage.py flow runs <lesson>
```

`--inline` runs each step in the command's own process; without it the step is queued for the Celery worker. A lesson can be named by the first characters of its id.

## 6. Walk through the app without API keys

`tests/e2e/fake_llm_server.py` is a fake OpenAI-compatible server that answers every structured-output call with canned, schema-valid content, so the real gateway, worker and graph run end to end at no cost. It is a development aid, not part of the product.

```bash
export FAKE_LLM_API_KEY=fake                    # or put it in .env
docker compose --profile e2e up -d fake-llm
docker compose exec backend python manage.py seed_registry --file /tests/e2e/fake_registry.json
```

**That replaces the bindings of every node in the registry of the database you run it against**, so do it on a throwaway stack. `make fake-llm` does exactly that for you:

```bash
make fake-llm      # a separate compose project (socra-e2e): http://localhost:7100, staff@example.com, no Supabase, no keys
make e2e-down      # when you are done: stops it and deletes its database
```

It is `docker-compose.e2e.yml` on top of the normal file (own ports, `SUPABASE_DATABASE_URL` and the provider keys blanked, trusted origins for its own two ports), with the registry loaded and a staff user made. `make e2e` runs the browser tests on it ([testing.md](../process/testing.md)). The fake is reached at `http://fake-llm.lan:9000/v1` (the registry insists on a domain-like host name, so the compose service has that alias). The fake also serves the media services the lesson flow searches (a Wikimedia-style API and generated PNGs), so run the stack with `WIKIMEDIA_API_URL=http://fake-llm.lan:9000/w/api.php` and `MEDIA_ALLOW_PRIVATE_HOSTS=true` for the media agent to find a picture. Add a builder to the fake whenever a phase adds an LLM output schema.

## Paying with Stripe's test mode (optional)

Stripe is the default way to pay once it is switched on. It needs three values from your Stripe dashboard **in test mode** (the "Test mode" or sandbox toggle; never a live key on a development machine). They go in `.env`, which git ignores:

```bash
STRIPE_SECRET_KEY=sk_test_...        # Developers > API keys
STRIPE_PUBLISHABLE_KEY=pk_test_...   # the same page (not secret; Stripe's page needs no browser key today)
STRIPE_WEBHOOK_SECRET=whsec_...      # see "Webhooks" below
PAYMENT_GATEWAYS_ENABLED=stripe
PAYMENT_DEFAULT_GATEWAY=stripe
```

The app refuses to start (`payments.E002`) if `stripe` is enabled without its secret key and webhook secret, and (`payments.E005`) if any key is a live one while `PAYMENTS_LIVE_MODE` is not `true`; the error names the setting, never the key. A test key can **expire** or be rolled in the dashboard: Stripe then answers `api_key_expired`, and the buy page says it could not reach the payment service (the backend log says why). Make a new one and replace it.

Pay on Stripe's page with the test card `4242 4242 4242 4242`, any future expiry, any CVC. Stripe sends the browser back to `PAYMENT_RETURN_BASE_URL/buy/return`, and that page asks our server, which asks Stripe, so credits arrive **without any webhook**, after the order is about half a minute old.

**Webhooks (optional, and what a real deployment relies on).** Stripe tells us of a payment, a refund and a dispute with a signed callback to `POST /api/payments/webhooks/stripe`. Send it **through the frontend's own address** (the Next proxy passes the raw body and the signature header on untouched, which is what the signature is computed over), with the Stripe CLI:

```bash
stripe login
stripe listen --forward-to localhost:3000/api/payments/webhooks/stripe     # 3000 is FRONTEND_PORT
```

It prints a signing secret (`whsec_...`); that one, not the dashboard's, is `STRIPE_WEBHOOK_SECRET` while you listen. Restart the backend after changing `.env`. For an endpoint made in the dashboard instead, give it these events and no others are needed: `checkout.session.completed`, `checkout.session.async_payment_succeeded`, `checkout.session.async_payment_failed`, `checkout.session.expired`, `refund.created`, `refund.updated`, `charge.dispute.created` (an unsubscribed event is simply never sent; one we do not know is ignored). A refund is counted from `refund.created`, never from `charge.refunded`, which only carries the running total. The admin's **Refund** action on a Stripe order refunds through Stripe, and the credits come back when `refund.created` arrives.

The API version is pinned in the code (`StripeApi.API_VERSION`, sent as `Stripe-Version` on every call); webhook bodies use the version of the endpoint or listener that sends them. The fields we read are in every recent version.

Two checks that use your test key and are never part of `make check`:

```bash
make payments-live   # creates a real test-mode Checkout Session, asks about it, expires it (no payment is made)
make e2e-payments    # a browser pays with the test card on a stack where Stripe is the only way to pay
```

`make e2e-payments` leaves that stack with Stripe as its only way to pay; `make fake-llm` or `make e2e` puts the fake gateway back. Both are skipped, or refuse to start, without a `sk_test_` key in `.env`.

## Paying with Razorpay's test mode (optional)

Razorpay's checkout opens on our own page, in a window of Razorpay's. It needs a key pair and a webhook secret from the Razorpay dashboard **in test mode** (the Test toggle; never live keys on a development machine). They go in `.env`:

```bash
RAZORPAY_KEY_ID=rzp_test_...        # Account & Settings > API keys. Public: it is handed to the browser.
RAZORPAY_KEY_SECRET=...             # shown once when the key is made. Never leaves the server.
RAZORPAY_WEBHOOK_SECRET=...         # any secret you choose when adding the webhook (not the key secret)
PAYMENT_GATEWAYS_ENABLED=stripe,razorpay     # or just razorpay
PAYMENT_DEFAULT_GATEWAY=razorpay
```

The app refuses to start (`payments.E002`) if `razorpay` is enabled without all three, and (`payments.E005`) if the key id is a live one (`rzp_live_...`) while `PAYMENTS_LIVE_MODE` is not `true`. With two gateways enabled the buy page asks how to pay; with one it does not. In the Razorpay dashboard leave **auto-capture** on (its default): `order.paid` is only sent once a payment is captured.

Pay in Razorpay's window with the test UPI id `success@razorpay` (`failure@razorpay` fails), or a test card from Razorpay's test-card page with any future expiry and CVV and, on its bank page, the Success button. The window brings the learner to `/buy/return`, which asks our server, which asks Razorpay, so credits arrive **without any webhook**, after the order is about half a minute old. A failed attempt can be tried again in the same window; closing the window leaves the learner on `/buy`; the order waits and is let go after a day.

**Webhooks (optional, and what a real deployment relies on).** Razorpay has no CLI and calls only a public address, so on localhost you need a tunnel (Razorpay's documentation suggests `zrok`; it refuses `ngrok.io` and some other tunnel domains). Send it through the frontend's address, as for Stripe: in the dashboard, Accounts & Settings > Webhooks > Add New Webhook (a test-mode webhook is its own), with the URL `https://<your public address>/api/payments/webhooks/razorpay`, your `RAZORPAY_WEBHOOK_SECRET` as the secret, and these events: `order.paid`, `payment.failed`, `refund.created`, `refund.processed`, `payment.dispute.created`. Razorpay signs no timestamp, so a repeated callback is stopped by its event id, which we keep once. It retries for 24 hours and then disables a failing webhook (turn it back on in the dashboard). The admin's **Refund** action on a Razorpay order refunds through Razorpay, once for each form shown (the form's token is Razorpay's idempotency key), and the credits come back when `refund.processed` arrives.

Razorpay's API is versioned by path (`/v1`), so there is no version to pin. Two checks that use your test keys and are never part of `make check`: `make payments-live` (creates a real test-mode order and asks about it; no payment) and `make e2e-payments` (a browser pays in Razorpay's window on a stack where Razorpay is the only way to pay). Both are skipped, or refuse to start, without the test keys.

## Switching credits on (and the day it goes live)

Credits are **on by default** since phase 10.9 (`ACTION_GATE=credits.gate.CreditGate`, `ACTIVITY_SINK=credits.activity.CreditsActivitySink`). To start a stack, in this order:

1. **Migrate** (`make migrate`, or let the backend start do it).
2. **Backfill the signup credits**: `docker compose run --rm backend python manage.py grant_signup_credits --dry-run` says how many accounts would get their 30 credits (which never expire); run it again without `--dry-run`. It is safe to repeat. Accounts made before credits existed are otherwise refused at their first paid action.
3. **Start the stack** (`make up`), with `beat` running exactly once: it expires credits, starts plan periods, releases reserves nothing will settle, and every five minutes asks the payment providers about payments and refunds whose callback never came.
4. A lesson or quiz that was already running when you restarted finishes free: it was never charged.

To keep credits off on a stack (a classroom, a demo), set `ACTION_GATE=lessons.metering.OpenGate` and `ACTIVITY_SINK=lessons.activity.NullActivity`.

**On a real host** (not covered by the test keys above): live provider keys need `PAYMENTS_LIVE_MODE=true`, which is refused anywhere else; the fake gateway is refused outside `DJANGO_DEBUG`; each provider needs a public HTTPS address to call, `https://<your address>/api/payments/webhooks/stripe` and `/razorpay` (through the frontend, which passes the raw body on untouched), with the webhook secret set in the environment and the events listed in the Stripe and Razorpay sections above; and `PAYMENT_RETURN_BASE_URL` set to the site's own address. Until a webhook is reachable, the return page and the five-minute sweep still settle payments by asking the provider, so a missing tunnel delays credits and never loses them. On a laptop, a tunnel (Razorpay suggests `zrok`) or the Stripe CLI is how a real callback arrives.

## Tracing and usage (optional)

- **Usage:** the staff console's *Usage & cost* page (`/console/usage`) shows calls, success rate, fallbacks, median and p95 latency, tokens and spend per model and per step over today, 7 days, 30 days or a custom range, and exports the calls as CSV. Spend stays at 0 until a model has a price (`input_cost_per_mtok` and `output_cost_per_mtok`) in the registry. The Django admin keeps its own *Model calls* pages with the same figures.
- **Tracing:** set `LLM_TRACING=langsmith` (with `LANGSMITH_API_KEY`, optionally `LANGSMITH_PROJECT`) or `LLM_TRACING=langfuse` (with `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY`, optionally `LANGFUSE_HOST`, and `uv add langfuse` plus a rebuild) in `.env`. It is off by default. **A trace contains the prompts and replies, which hold what the learner wrote**, so it goes to the service you choose. `manage.py check` warns when the setting cannot work (it names missing variables, never their values); a tracing problem never fails a model call.

## Everyday commands

```bash
make help            # list everything
make logs            # follow all logs
make migrate / makemigrations / superuser / shell
make sync-supabase   # run the local → Supabase copy manually
make test            # pytest (always the docker Postgres, never Supabase)
make lint            # ruff (backend + tests) + OpenAPI schema + eslint + tsc + bun test
make check           # lint + test: run before finishing any change
make down            # stop; volumes are kept
```

## Updating an install that has lessons in flight

A lesson can wait at a quiz for days, with its place saved in the LangGraph checkpoint. A release that **removes or
renames a graph node** leaves such a lesson pointing at nothing, and LangGraph does not say so: the lesson just never
moves. So before (or right after) starting a build that changed the graph, **drain the stranded threads**:

```bash
docker compose exec backend python manage.py stranded_threads                 # list them, change nothing
docker compose exec backend python manage.py stranded_threads --mark-failed   # end them
```

`--mark-failed` gives each lesson the message "This lesson was started before an update and cannot be carried on.
Please delete it and start a new lesson." Lessons that are ready are never touched. Adding a node never strands a
thread, so only releases that remove or rename one need this (9.2 removed `write_test`, so a deploy that crosses it needs this;
9.3 only adds nodes). The release notes of such a release say so.

### After migrating a release

Run these in order after `migrate` on every install that has lessons (they are safe to run again):

```bash
docker compose exec backend python manage.py migrate
docker compose exec backend python manage.py stranded_threads                 # list lessons stuck at a removed node
docker compose exec backend python manage.py backfill_concept_index --dry-run # what would be indexed
docker compose exec backend python manage.py backfill_concept_index           # write the concept index of older lessons
```

- `backfill_concept_index` (phase 9.7) places each concept of a lesson made before the index on the page that teaches it,
  from the stored plan and pages, so a quiz result can link to the right page. It fills only empty indexes, writes only
  that column and prints how many lessons and concepts it placed or could not place. A lesson it cannot place still
  works: its links open the lesson without a page. It is **not** run at start-up.
- `grant_signup_credits` (phase 10.3) gives the 30 signup credits, which never expire, to every active account that was
  made before credits existed. New accounts get them when they register. Run it with `--dry-run` first (it prints how many
  accounts it would give them to and writes nothing), then for real, **once before the credit gate is switched on**. It is
  safe to run again: an account that has them is left alone, and a closed account is skipped. Since phase 10.9 the credit gate
  and the earning sink are the defaults, so this is a **deploy step before the first start with credits on**: migrate, run
  it with `--dry-run`, run it, then start the stack. A lesson or quiz that was already running when the stack restarts
  finishes free (it carries no charge).
- Migration `0021` (phase 9.8) refuses to run while any lesson still waits at the old three-sheet choice. If it stops,
  let those learners choose with the previous release, then migrate again. Migration `0019` moved every lesson's test
  onto the record of questions; it can be undone, and it does not touch attempts.

### Erasing an account

A person can ask us to delete their account (the Privacy page says to write by email). In the staff console, open the learner (Learners → Wallet) and use **Delete this learner's data**: it shows what will go, and needs the account's email typed. From a terminal, use the command below; both do the same. The account cannot be deleted, because
the credit ledger is append-only and refers to it, so it is **erased in place**: run it with `--dry-run` first.

```bash
docker compose exec backend python manage.py erase_account someone@example.com --dry-run  # what would be erased
docker compose exec backend python manage.py erase_account someone@example.com            # do it (the id works too)
```

It also ends every sign-in (refresh tokens and admin sessions), deletes the admin's log rows about the account and takes the free text out of the change log entries about it. It releases any credits reserved for work under way, erases the learner's lessons and quizzes with their checkpoints and model
calls, writes off the credits they had left on the ledger, deletes their streak, empties their profile, and anonymises the user
(the email becomes `deleted-<id>@erased.invalid`, the name is blank, the password unusable, the account inactive). It cannot be
undone. It is safe to run again: an erased account is reported as such, and an attempt that stopped half way is finished.

## Tests

- Tests live in the repo-root `tests/` folder, **mirroring `backend/`**: `backend/core/sync.py` is tested in `tests/core/test_sync.py`.
- The pytest config is in `backend/pyproject.toml` (`testpaths = ["../tests"]`). In docker, `tests/` is mounted at `/tests`.
- Graph and runner tests run nodes on LangGraph's worker threads, which have their own database connection and see only committed rows, so those tests use `pytest.mark.django_db(transaction=True)` (slower: the tables are flushed after each). Shared doubles live in `tests/support/`.
- Under pytest, settings ignore `SUPABASE_DATABASE_URL`. Two test databases are created on the docker Postgres: `default` and `local`. The second one exists so the sync can be tested between two real databases.
- **CI:** `docker compose run --rm backend pytest` needs no `.env`. Everything falls back to defaults.

## The sandbox package

`sandbox/` is a small Node package (managed with bun) that the backend runs in a subprocess to check generated lesson code (`scripts/check.mjs`: syntax, security scan, scope contract, KaTeX). The **backend image has Node and installs its packages** (the `sandbox` build context in `docker-compose.yml`), and compose bind-mounts `./sandbox` with the image's `node_modules` kept visible. After pulling a change to `sandbox/package.json`, rebuild with `docker compose up --build --renew-anon-volumes`: without the last flag compose keeps the old container's `node_modules` volume, which hides the new image's packages (for example `playwright` missing at render-check time). Fixtures of known-malicious and known-good code are in `sandbox/fixtures/` and run by `tests/graph/test_sandbox.py`. To run a check by hand: `echo '{"mode":"latex","items":["x^2"]}' | docker compose run --rm -T backend node /sandbox/scripts/check.mjs`. The backend image also carries Playwright Chromium for the headless render check, and the `sandbox-build` service rebuilds the lesson runtime into `frontend/public/sandbox/` on every `docker compose up`.

## Adding dependencies

```bash
cd backend && uv add <package>     # updates pyproject.toml + uv.lock
cd frontend && bun add <package>   # updates package.json + bun.lock
docker compose up --build          # rebuild images
```

The backend image installs into `/opt/venv`, outside the bind-mounted `/app`. The frontend keeps `node_modules` in an anonymous volume. Host copies never clash with the container's.

## Troubleshooting

| Symptom | Fix |
|---|---|
| `Permission denied` on `/app` (Fedora and other SELinux hosts) | Bind mounts use the `:z` label. Keep it. |
| `port is already allocated` | Change the port in `.env`. |
| `password authentication failed` after editing `POSTGRES_*` | The volume keeps its original credentials. See section 1. |
| Health: `celery: no workers responded` | `docker compose logs worker`. It restarts on file changes, so check for a Python error. |
| New dependency not found | `docker compose up --build --renew-anon-volumes`. Without the last flag compose keeps the old container's `node_modules` volume, which hides the new image's packages (the frontend then fails with `Module not found`). |
| `no space left on device` from Docker while `df` shows free space (btrfs) | Metadata is full and there's no unallocated space for more. Run `sudo btrfs balance start -dusage=20 /` (then `-dusage=50`) to give empty data chunks back, and `docker volume prune` for old anonymous `node_modules` volumes. |

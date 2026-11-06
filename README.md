# StyleKart Return Support API

Mock e-commerce backend for the **StyleKart** voice agent built on Ringg AI.
A customer calls, the agent finds them by phone number, asks which item to
return, checks the return window, books a pickup slot and creates a return
record, all through this API.

StyleKart is a fictional brand. All customers and orders are dummy data.

## Design rules

- **The backend decides, the agent explains.** Eligibility, dates and slots are
  computed here, never by the LLM. Every response has a `say` field: a short
  Hinglish line the agent can read out as-is.
- **Critical gates are enforced server-side.** `POST /returns` re-checks
  eligibility (409 if not allowed), accepts only currently offered slots, and
  is idempotent per item, so a retry after a timeout never creates a second return.
- **Voice-ready responses.** Responses are flat, dates are already written out
  ("4 November ko deliver hua tha (2 din pehle)"), IDs are spelled out
  ("R T 4 8 2 0 1") and amounts are formatted ("1,299 rupaye").
- **Phone numbers are normalised** (`+91 98765 43210`, `09876543210` and
  `9876543210` all match), so lookups don't depend on how Ringg sends the number.

## Endpoints

No authentication: this is a dummy backend, so every endpoint is open.
Interactive docs are served at `/docs`.

| # | Endpoint | Ringg mechanism | Purpose |
|---|---|---|---|
| 1 | `GET /customers/by-phone/{phone}` | Action node after greeting | Caller's name and up to 5 recent items. Returns `found: false` (HTTP 200) for an unknown number |
| 2 | `POST /returns/eligibility` | Action node after item confirmed | `eligible`, `reason_code`, `days_left` / `days_past`, `say` |
| 3 | `GET /pickup-slots/{order_id}` | Action node after reason captured | Up to 6 slots with `slot_id` and `slot_text` |
| 4 | `POST /returns` | On-call tool on booking agent, after "haan" | Creates the return; returns spelled-out ID, pickup text, refund ETA |
| 5 | `POST /callbacks` | On-call tool on callback agent | Books a callback |
| 6 | `GET /refunds/{order_id}` | On-call tool on order agent | Read-only refund status |
| 7 | `POST /quality-tickets` | On-call tool on ineligible agent | Damaged or wrong item that can't be returned; sends photo link |

Admin endpoints, for tests and evals:

| Endpoint | Use |
|---|---|
| `POST /admin/reset` | Restore all seed data (run between eval calls) |
| `GET /admin/state/{phone}` | Everything for one customer: orders, returns, tickets. Before/after evidence |
| `POST /admin/map-phone` | `{"phone": "+91...", "customer_id": "C04"}` points your real number at any seed customer |
| `POST /admin/clock` | `{"now": "2026-11-06T23:50:00"}` freezes India time; `{"now": null}` unfreezes. Call `/admin/reset` after freezing so seed dates follow |
| `GET /admin/events?limit=50` | Log of every business API call, for checking "correct API calls" in evals |

### Errors

Errors return `{"detail": {"code": "...", "say": "..."}}`:

| Status | Code | When |
|---|---|---|
| 403 | `NOT_OWNER` | `phone` was sent and doesn't own the order |
| 404 | `ITEM_NOT_FOUND`, `ORDER_NOT_FOUND` | Unknown order or item |
| 409 | `WINDOW_EXPIRED`, `NON_RETURNABLE`, `NOT_DELIVERED` | Create attempted for an ineligible item |
| 422 | `SLOT_UNAVAILABLE` | Slot not currently offered; `available_slots` lists valid ones |
| 500 | `UPSTREAM_ERROR` | Simulated failure (Tanya's order) |

## Return policy

Checked in this order; the first failing rule wins.

1. `NOT_DELIVERED`: item not delivered yet
2. `ALREADY_RETURNED`: a return already exists for the item (existing ID is read back)
3. `NON_RETURNABLE`: innerwear, beauty or personalised
4. `WINDOW_EXPIRED`: more than 14 days since delivery (day 14 is still eligible)
5. `OK`

Pickup slots cover today, tomorrow and the day after, in three windows
(9–12, 12–4, 4–7). A slot is offered only if it starts at least 2 hours from now.

## Seed customers

Delivery dates are relative to today (India time), recomputed on every reset.

| ID | Customer | Phone | Orders | Scenario |
|---|---|---|---|---|
| C01 | Ananya | `DEMO_PHONE` (default +919000000001) | SK1001 kurta, 3 days ago | Happy path |
| C02 | Rohan | +919000000002 | SK1002 sneakers 2d, SK1003 jeans 6d, SK1004 shirt 10d, SK1005 hoodie (refunded) | Choosing between orders; refund status |
| C03 | Priya | +919000000003 | SK1006: top + jeans, 5 days ago | One item of a multi-item order |
| C04 | Meera | +919000000004 | SK1007 dress, 17 days ago | Window expired by 3 days |
| C05 | Arjun | +919000000005 | SK1008 jacket, exactly 14 days ago | Last eligible day |
| C06 | Kabir | +919000000006 | SK1009 innerwear pack | Non-returnable |
| C07 | Isha | +919000000007 | SK1010 saree, in transit | Not delivered |
| C08 | Dev | +919000000008 | SK1011 shirt, return RT40011 booked | Already returned |
| C09 | Neha | +919000000009 | SK1012 kurta, cash on delivery | SMS link for bank details |
| C10 | Sahil | +919000000010 | SK1013 jeans, pincode 194101 | No pickup slots |
| C11 | Tanya | +919000000011 | SK1014 dupatta | Eligibility API returns 500 |
| C12 | Vikram | +919000000012 | SK1015 polo | Create-return is slow (looks like a timeout) but saves; retry must not duplicate |
| C13 | Upendra Singh | +91 75050 62257 | SK1016 sneakers 2d, SK1017 denim jacket 19d, SK1018 boxer briefs | Real calls: choose between orders; one returnable, one expired, one non-returnable |
| C14 | Anant Jakhmola | +91 99532 60051 | SK1019 linen kurta (COD) 4d, SK1020 shirt in transit | Real calls: COD refund via SMS link; not delivered |
| C15 | Rishabh Thakur | +91 91492 62211 | SK1021: chinos + henley 6d, SK1022 puffer (refunded) | Real calls: return one item of two; refund status |
| — | — | any other number | — | Unregistered number |

C13–C15 are real numbers. Keep the GitHub repository **private**. To test any
other scenario from a real phone, point it at that customer with
`POST /admin/map-phone`, then `POST /admin/reset` afterwards to restore it.

Item IDs are `<order_id>-<n>`, e.g. `SK1006-2`.

## Run locally

```bash
python -m venv .venv
.venv\Scripts\activate            # Windows (macOS/Linux: source .venv/bin/activate)
pip install -r requirements-dev.txt
pytest -q                          # 36 tests
uvicorn app.main:app --reload      # http://127.0.0.1:8000/docs
```

## Deploy

### Render

1. Push this folder to a GitHub repository.
2. Render dashboard → **New → Blueprint** → pick the repository. `render.yaml` sets everything up.
3. Open `https://<service>.onrender.com/health`.

Free-tier note: the service sleeps after 15 minutes idle, and the first request
then takes about a minute. The SQLite file is also wiped on restart, and the
seed data reloads automatically. Before a demo or eval session, open `/health`
once to wake it. For the reviewer period, a paid instance (or Railway) avoids the cold start.

### Railway

1. **New Project → Deploy from GitHub repo**. The `Procfile` sets the start command.
2. Settings → Networking → **Generate Domain**.

## Environment variables

| Variable | Default | Purpose |
|---|---|---|
| `DEMO_PHONE` | `+919000000001` | Optional: number for Ananya (C01) |
| `DB_PATH` | `stylekart.db` | SQLite file location |
| `SLOW_CREATE_SECONDS` | `5` | Delay for Vikram's slow create-return scenario |

## Example calls

```bash
BASE=http://127.0.0.1:8000

curl $BASE/customers/by-phone/9000000002
curl -H "Content-Type: application/json" -X POST $BASE/returns/eligibility \
     -d '{"order_id":"SK1001","item_id":"SK1001-1"}'
curl $BASE/pickup-slots/SK1001
curl -H "Content-Type: application/json" -X POST $BASE/returns \
     -d '{"order_id":"SK1001","item_id":"SK1001-1","reason":"size issue","slot_id":"<slot_id from above>"}'
curl $BASE/admin/state/9000000001
```

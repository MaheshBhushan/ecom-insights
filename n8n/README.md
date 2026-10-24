# Scheduled sales and marketing briefings

The FastAPI service serves the existing `reports/kpis.json` and
`reports/executive_briefing.json`. It validates KPI consistency and numeric
grounding on each new snapshot. It never calls a model or reloads the warehouse.
Both audiences receive the same validated executive report with an audience
label. Each audience has its own destination, schedule, and delivery key.

## Local self-hosted setup

1. Install API dependencies with `pip install -r requirements-api.txt` for a
   local Python run. Docker installs these dependencies during its build.
2. Copy `.env.example` to `.env` if that file does not exist. Set
   `BRIEFING_API_TOKEN` to a newly generated private token. Set
   `SALES_BRIEFING_WEBHOOK_URL` and `MARKETING_BRIEFING_WEBHOOK_URL` to authorized
   HTTP receivers. Receivers must accept the JSON envelope described below and
   deduplicate the `Idempotency-Key` header. Use HTTPS outside the local network.
   The API accepts only configured destinations; callers cannot submit a URL.
3. Run `docker compose -f docker-compose.briefings.yml up -d --build`. This
   separate stack leaves the warehouse service alone. The API listens on
   `127.0.0.1:8000`; n8n listens on `127.0.0.1:5678`. Both services retain their
   SQLite state in named Docker volumes. Protect and back up those volumes.
4. Open `http://localhost:5678` and create the local n8n owner account. Create
   a **Header Auth** credential named `Briefing API bearer token`, with header
   name `Authorization` and value `Bearer <your private token>`.
5. Import `sales-briefing.json` and `marketing-briefing.json` in the editor.
   Select that credential in each **Deliver validated briefing** node. The
   exported credential reference is a placeholder; no secret is in the export.
6. Test against a local receiver that you control, then publish/activate each
   workflow. Imports are inactive. Sales runs weekdays at 08:00; marketing runs
   weekdays at 09:00 in `Europe/Berlin`. Change the Schedule Trigger to change
   delivery times. The workflows use the internal URL `http://briefing-api:8000`.

For Python development, set the same environment variables and run
`uvicorn src.delivery_api:create_app --factory --host 127.0.0.1 --port 8000`.
`DELIVERY_DB` overrides the default `var/deliveries.sqlite3` ledger path.
The factory requires a nonempty API token. A missing destination fails closed
and creates a failed-delivery record when a delivery is requested.

The Compose configuration supports local HTTP access. A public installation
requires a TLS reverse proxy, secure cookies, and restricted network access.
It uses the pinned n8n image `2.42.4`. Consult the official
[Docker setup](https://docs.n8n.io/hosting/installation/docker/) before upgrading.

## API contract

All business endpoints require `Authorization: Bearer <token>`.

| Request | Result |
| --- | --- |
| `GET /briefings/sales` or `/briefings/marketing` | Validated JSON report envelope; 503 if source files are missing or invalid |
| `POST /deliveries/sales` or `/deliveries/marketing` | Deliver the report using the required `Idempotency-Key` header; no request body |
| `GET /deliveries/{key}` | Persisted delivery receipt, or 404 |
| `GET /deliveries?status=failed&limit=100` | Most recent failed-delivery receipts; maximum 100 per response |

The outgoing envelope includes `audience`, `delivery_key`, KPI and briefing
SHA-256 hashes, the source period, unchanged `kpis` and `briefing` objects, and
rendered `markdown`. Its period always describes the source data, even when
the delivery date is newer. The committed report uses synthetic sample data.
Update both source JSON artifacts together before scheduling a new snapshot.
The service does not infer freshness or silently substitute another report.

## Retries and failed deliveries

The **Delivery identity** node creates `ecom-sales-YYYY-MM-DD` or
`ecom-marketing-YYYY-MM-DD` before the HTTP request. The HTTP node retries three
times with five seconds between attempts and a 20-second request timeout.
Its [Retry on Fail](https://docs.n8n.io/integrations/builtin/core-nodes/n8n-nodes-base.httprequest/common-issues/)
setting uses the same input key on every attempt. Exhaustion fails the n8n
execution. The API retains its failed-delivery record independently of n8n's
execution history.

The API commits a claim and the validated report snapshot before sending.
Each attempt has a 10-second HTTP I/O timeout. Only a 2xx receiver response
marks delivery as `delivered`. Redirects are rejected. Failures return 502
with a durable receipt. Configuration or validation failures return 503 and
also remain in the ledger. Receipts include audience, key, attempt count,
timestamps (Unix seconds), source hashes, status, and a sanitized error code.
They never include a destination URL, receiver response body, or exception text.

A successful key returns its stored receipt without sending again. A failed
key retries its saved snapshot. A different audience or a changed destination
for an existing failed snapshot returns 409. Restore the original destination
before retrying that key. Concurrent calls return 409 while a claim is active.
An interrupted claim expires after 60 seconds. Ledger reads and subsequent
delivery requests mark expired claims as `failed` with `delivery_interrupted`.
The next request can retry the saved snapshot.

For manual recovery, read `GET /deliveries?status=failed`, inspect the n8n
execution, fix the receiver, and repeat the POST with the **original key**.
Use that key when replaying an execution on another day. A fresh execution
computes a fresh date. Creating a new key intentionally creates a new delivery.

The receiver must persistently deduplicate keys. If it accepts a request and
the API crashes before saving the acknowledgement, a retry sends the same
payload and key. This protocol provides at-least-once delivery attempts and
prevents repeated successful API calls from sending again. It cannot promise
exactly-once effects at a receiver that ignores idempotency. A 2xx response
means the receiver accepted the report; downstream forwarding requires the
receiver's own delivery tracking.

SQLite claims support a single Docker host. Run a single API instance with its
persistent ledger. Retain keys as long as old executions can be replayed.
No emails or external deliveries are required for the offline test suite.

## Verification

```bash
pip install -r requirements.txt -r requirements-api.txt
python -m pytest -q tests/test_delivery_api.py tests/test_delivery_config.py tests/test_grounding.py tests/test_comparison.py
```

The tests exercise validation, authentication, persistence across restarts,
deduplication, failed HTTP responses, timeouts, connection errors, interrupted
claims, concurrent requests, snapshot pinning, both audiences, and a real
loopback HTTP receiver. Workflow checks verify schedules, retry settings,
credential placeholders, and Compose configuration. For a native offline
n8n import check, run:

```bash
docker run --rm --network none \
  --tmpfs /home/node/.n8n:uid=1000,gid=1000,mode=0700 \
  -v "$PWD/n8n:/workflows:ro" -e N8N_DIAGNOSTICS_ENABLED=false \
  docker.n8n.io/n8nio/n8n:2.42.4 import:workflow --separate --input=/workflows
```

To check both the API image's nonroot runtime and native n8n imports, build
`docker build -f Dockerfile.briefings -t ecom-briefings:d8cb693 .`, then run
`python tests/check_delivery_containers.py`. The check uses no network and
stores all container state in temporary container filesystems.

Live destination setup and workflow activation require the operator's private
token and authorized receivers. Offline verification does not send to those
receivers or activate a schedule.

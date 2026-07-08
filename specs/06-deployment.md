# 06 — Deployment & Access Spec

## Purpose

Defines how the trip agent is shared with the two companion families: hosting
topology, the password/identity mechanism, the secret inventory, and the
operational runbook. Goal: any family opens a browser URL, logs in with their
family password, and chats with an agent that already knows who they are —
with **no secrets or private addresses in the public GitHub repo, in logs, or
in the served pages**.

## Topology

- **Cloud Run** service `yellowstone-trip-agent`, region `us-west1` (same as
  the trip-data GCS bucket), deployed from source (`Dockerfile`).
- **Exactly one instance** (`--max-instances 1`): ADK sessions are in-memory,
  so a second instance would split conversations. `--min-instances 0` normally
  (idle ≈ $0; a conversation idle >~15 min may be forgotten); bumped to 1 for
  the trip week (Jul 18–25).
- Cloud Run ingress is `--allow-unauthenticated` **by design**: authentication
  is enforced by the app's own login gate (below), because the families use
  plain passwords, not Google accounts (which IAP would require).
- The ADK **dev-ui is disabled in production** (`SERVE_DEV_UI=0`); the only UI
  is the custom one at `/ui/`.

## Authentication & family identity

- One password per family: `FAMILY1_PASSWORD`, `FAMILY2_PASSWORD`,
  `FAMILY3_PASSWORD` (values live in Secret Manager; never in code, repo, or
  logs). Which password matches determines **who is prompting** — the agent
  never needs to ask a logged-in user.
- `POST /login {password}` compares against all three with
  `hmac.compare_digest` and on success sets a signed cookie:
  `trip_auth=<family>.<expires_unix>.<hmac_sha256(family.expires, COOKIE_SECRET)>`
  (httpOnly, `Secure`, `SameSite=Lax`, 14-day expiry). `GET /login` serves the
  login page. Passwords are never echoed back or logged.
- Middleware protects **everything** except `/login` and `/api/health`
  (`/healthz` is unusable: Google's frontend reserves it on run.app) — that
  includes `/run_sse`, all ADK session APIs, `/api/*`, `/ui`, `/tmp`, and the
  dev-ui when enabled locally. Browser requests get 302→`/login`; API
  requests get 401.
- `GET /api/me` → `{"family": "family-2", "label": "Family 2"}`.
- The frontend uses the family as the ADK `user_id` and prepends a visible
  marker to the first message of each session: `[Prompting family: Family 2]`.
  The root agent grounds vehicle/lodging context from the marker; when the
  marker is absent (local `adk web` dev-ui), it **asks** who's prompting.

## Private data vs public repo

- `specs/01-trip-context.md` (committed, public) carries **city-level**
  locations only; every accommodation has a stable `id`.
- `specs/trip-context-overrides.yaml` (**gitignored**, never on GitHub) maps
  accommodation `id` → exact street address. `tools._parse_context()` merges
  it when present. The deploy source upload includes it (`.gcloudignore`
  does not exclude it), so the hosted agent uses real addresses.
- Format:

  ```yaml
  # specs/trip-context-overrides.yaml — DO NOT COMMIT
  accommodations:
    airbnb-driggs:
      address: "123 Example St, Driggs, ID 83422"
  ```

## Secret inventory (names only — values in Secret Manager / local .env)

| Name | Purpose |
|---|---|
| `MAPS_API_KEY` | Routes v2 / Elevation / Places REST + Maps MCP (API-restricted in console) |
| `GEMINI_API_KEY` | Agent + eval models |
| `FAMILY1_PASSWORD` / `FAMILY2_PASSWORD` / `FAMILY3_PASSWORD` | Login |
| `COOKIE_SECRET` | HMAC key for the auth cookie |
| `NPS_API_KEY` (optional) | Live park alerts; absent → mock alerts with disclosure |

Log hygiene: the flow log truncates tool args/results and **masks** the GCS
signed URL returned by `save_and_upload_trip_plan`; passwords and keys never
transit tool args. `.env` / `.env.*` are gitignored and excluded from the
deploy upload.

## Signed URLs on Cloud Run

`generate_signed_url` needs a signing key; the Cloud Run runtime SA has none.
The service runs as a dedicated SA (`trip-agent-run`) with
`roles/iam.serviceAccountTokenCreator` **on itself**, and
`save_and_upload_trip_plan` signs via the IAM signBlob API when no local key
is available (local dev with user ADC continues to work via the existing path
or falls back to the local file link).

## Runbook

```bash
# One-time: secrets (repeat per name; -n = no trailing newline)
echo -n "<value>" | gcloud secrets create FAMILY1_PASSWORD --data-file=-

# One-time: runtime service account + roles
gcloud iam service-accounts create trip-agent-run
#   roles/secretmanager.secretAccessor (project)
#   roles/storage.objectAdmin (bucket yellowstone-trip-data-<project>)
#   roles/iam.serviceAccountTokenCreator (on itself)

# Deploy / redeploy
gcloud run deploy yellowstone-trip-agent --source . --region us-west1 \
  --service-account trip-agent-run@<project>.iam.gserviceaccount.com \
  --set-secrets MAPS_API_KEY=MAPS_API_KEY:latest,GEMINI_API_KEY=GEMINI_API_KEY:latest,FAMILY1_PASSWORD=FAMILY1_PASSWORD:latest,FAMILY2_PASSWORD=FAMILY2_PASSWORD:latest,FAMILY3_PASSWORD=FAMILY3_PASSWORD:latest,COOKIE_SECRET=COOKIE_SECRET:latest \
  --set-env-vars GOOGLE_CLOUD_PROJECT=<project>,SERVE_DEV_UI=0,FLOW_LOG=1 \
  --min-instances 0 --max-instances 1 --memory 1Gi --allow-unauthenticated

# Trip week (Jul 18-25): keep conversations warm
gcloud run services update yellowstone-trip-agent --region us-west1 --min-instances 1
# ... and back to 0 afterwards.

# Rotate a family password
echo -n "<new>" | gcloud secrets versions add FAMILY2_PASSWORD --data-file=- \
  && gcloud run services update yellowstone-trip-agent --region us-west1  # restart picks up :latest

# Check logs (never contains secrets; flow log lines describe hops)
gcloud logging read "resource.type=cloud_run_revision AND resource.labels.service_name=yellowstone-trip-agent" --limit 50
```

## Non-goals (Phase 2+)

- Google-account SSO / IAP, per-user accounts within a family.
- Persistent session store (Cloud SQL) — single instance + trip-week warm
  instance is enough for 3 families.
- Rate limiting beyond Cloud Run's single-instance concurrency.

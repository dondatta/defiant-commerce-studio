# API and frontend routes

All API routes use Django session login and CSRF protection. Obtain the normal session via `/login/` and send `X-CSRFToken` for mutations. JSON bodies must be objects. Brand authorization is checked before ID lookup. Unknown or unauthorized brand/record IDs return 404; unauthorized roles return 403; validation errors return 400. List resources return at most the newest 500 records; paginated APIs are future work.

## JSON API

| Method | Route | Behavior |
|---|---|---|
| GET / POST | `/api/brands/` | Accessible brands / platform-admin brand creation |
| GET / PATCH | `/api/brands/{brand}/` | Brand detail / brand-admin update; deactivate with status INACTIVE |
| GET | `/api/brands/{brand}/{resource}/` | Brand-scoped list |
| GET | `/api/brands/{brand}/{resource}/{id}/` | Brand-scoped record |
| POST / PATCH | `/api/brands/{brand}/{resource}/[id/]` | Forms-backed characters/concepts creation/update; admin settings/provider/shopify configuration |
| POST | `/api/brands/{brand}/actions/import/` | Shopify-style JSON upsert, body `{"products": [...]}` |
| POST | `/api/brands/{brand}/actions/sync/` | Admin live Shopify sync |
| POST | `/api/brands/{brand}/actions/daily/` | Enqueue/reuse today's batch; additional batch requires `{"confirm_additional": true}` |
| POST | `/api/brands/{brand}/actions/prompt/{concept}/` | Compose prompt without provider submission |
| POST | `/api/brands/{brand}/actions/generate/{concept}/` | Idempotent initial generation; returns 202 |
| POST | `/api/brands/{brand}/actions/review/{generation}/` | `{"decision":"APPROVED","notes":"..."}`; REJECTED/READY_TO_POST also supported |
| POST | `/api/brands/{brand}/actions/regenerate/{generation}/` | `{"mode":"new_seed","changes":{"location":"...","character":123}}`; returns new generation, 202 |

Resources: `products`, `characters`, `concepts`, `generations`, `categories`, `assets`, `calendar`, `audit`, `batches`, `settings`, `provider`, `shopify`. Read-only resources mutate through dedicated workflow/form routes, not arbitrary updates. Product preferences, references, prompt components/templates, calendar planning, membership, downloads/exports and manual retries have web form endpoints below. A POST result for a generation means queued, never generated or approved. Use `Generation.status` and its output asset ID to inspect completion.

## Frontend and form endpoints

`/login/`, POST `/logout/`, platform-only `/admin/`, `/brands/`, `/brands/new/`.

Under `/brands/{brand}/`: workspace root; `products/`, `characters/`, `concepts/`, `queue/`, `calendar/`, `assets/`, `settings/`, `history/`.

Create/update forms: `edit/{kind}/` and `edit/{kind}/{record}/`, for `brand`, `settings`, `provider`, `shopify`, `character`, `product`, `concept`, `component`, `template`, `category`, `calendar`, `social`.

POST actions: `products/import/`, `products/sync/`, `characters/{character}/references/` (multipart), `concepts/{concept}/generate/`, `daily/`, `members/`.

Generation detail/review: `generations/{uuid}/`; regeneration form: `generations/{uuid}/regenerate/`; POST export: `generations/{uuid}/export/`; POST retry: `generations/{uuid}/retry/` with `confirm=yes` after inspecting remote state.

Private authenticated file: `assets/{asset}/file/`, optionally `?download=1`. Asset metadata never grants an unauthenticated storage URL.

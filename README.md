# defiant-commerce-studio

Independent, multi-brand ecommerce creative studio for Defiant. Infatuation Apparel is the first **seeded tenant**, not a hard-coded application mode. No CMM runtime imports, shared database or deployment dependencies.

The local milestone provides login, brand administration, Shopify-style catalog import, character/reference management, editable prompts, asynchronous OpenAI/ComfyUI jobs, daily candidate planning, review/regeneration, a date-grouped calendar, private assets and Instagram derivatives. Generated content is never automatically approved or published.

## Docker development (recommended when using a Docker server)

```bash
python3 scripts/init_docker_env.py
docker compose up --build -d
docker compose exec web python manage.py createsuperuser
```

Python 3.12, PostgreSQL, web, worker and scheduler run in containers. Host Python 3.14 is supported for the configuration helper. Database/private assets persist in separate volumes. See [Docker commands and access](docs/DOCKER.md). This is a development stack; production deployment is separate.

## Run locally

Python 3.12+, Chromium only for optional browser tests. Run these exact commands:

```bash
cd /workspace/defiant-commerce-studio
./scripts/setup.sh
.venv/bin/python manage.py createsuperuser
.venv/bin/python manage.py runserver 127.0.0.1:8000
```

Start two additional terminals with the same exported environment variables:

```bash
cd /workspace/defiant-commerce-studio
.venv/bin/python manage.py worker
```

```bash
cd /workspace/defiant-commerce-studio
.venv/bin/python manage.py scheduler
```

Open the application locally at `http://127.0.0.1:8000/`, sign in using the superuser you created, and select the seeded brand. No default password or permanent test account is included. `createsuperuser` prompts securely for your password. All three processes need the same database, private storage and provider credential bindings.

The seed command is repeatable and preserves existing edits. Tenant-specific data lives in [studio/seed_data/default-brand.json](studio/seed_data/default-brand.json). Additional brands can be created in the interface without code changes; populate categories, locations, poses, templates and a provider for each one. An alternate tenant config can be loaded with `manage.py seed_studio --file path/to/brand.json`.

[Architecture and operational limits](docs/ARCHITECTURE.md) · [API routes](docs/API.md) · [First real daily batch](docs/FIRST_IMAGES.md) · [Implementation report](docs/IMPLEMENTATION_REPORT.md)

## Configuration

[.env.example](.env.example) lists variable names. Django intentionally does not load `.env` automatically: inject variables securely into the web, worker and scheduler processes. Never commit secrets.

| Variable | Purpose |
|---|---|
| `DJANGO_SECRET_KEY` | Required with `DEBUG=0`; independent secret for this application |
| `DEBUG`, `ALLOWED_HOSTS` | Development/production and accepted hostnames |
| `DEFIANT_IMAGE_API_KEY` | OpenAI Images credential, when selected; configurable per-brand binding name |
| `SHOPIFY_INFATUATION_TOKEN` | Example per-store Admin API access-token binding |
| `COMFYUI_API_KEY` | Optional authenticated ComfyUI/RunPod endpoint binding |
| `COMFYUI_ALLOWED_HOSTS` | Explicit trusted private ComfyUI hosts; empty by default |
| `POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_HOST`, `POSTGRES_PORT` | Optional standalone PostgreSQL database; absent DB name selects SQLite |
| `STORAGE_BACKEND` | `local` (default) or `s3` |
| `PRIVATE_STORAGE_ROOT` | Optional local private storage root |
| `S3_BUCKET`, `S3_REGION`, `S3_ENDPOINT_URL` | Optional private object storage configuration |
| AWS SDK credential chain | S3 authentication via environment, workload role or configured SDK profile |

The app stores provider/store binding names, not API keys. No image-provider or Shopify credential binding was present during implementation. Configure keys securely outside chat and the repository. Each brand can reference a separate binding, provider/model and store. External requests preserve TLS verification.

## Validation

```bash
cd /workspace/defiant-commerce-studio
.venv/bin/python manage.py test studio --verbosity 1
.venv/bin/python manage.py check
.venv/bin/python manage.py makemigrations --check --dry-run
```

Optional real-browser smoke check, with the development web server already running:

```bash
.venv/bin/python -m pip install -r requirements-dev.txt
.venv/bin/python scripts/browser_smoke.py
```

It uses `/usr/bin/chromium`, creates/removes a temporary account, verifies real login plus 12 routes, checks mobile overflow and JavaScript exceptions, and saves screenshots under `/tmp`. Provider/Shopify integration tests mock the external network boundary; live provider generation, real-store sync and S3 have not been exercised without credentials/infrastructure. PostgreSQL migrations, tenant/history triggers and all 48 tests have also passed in Docker. No test-generated files or images are seeded as live brand content.

## First milestone boundaries

No automatic social posting, production deployment, real-creator system, analytics engine or video generation. ComfyUI supports installed image workflows with references/LoRA/conditioning; RunPod serverless APIs and Shopify OAuth installation are future work. Original image files are kept; optional exports proportionally pad to 1080×1350 without cropping or watermarking. Character and garment accuracy always need human review.

Use a single worker/scheduler with SQLite. PostgreSQL enables concurrent worker locking. Failures, bounded retries, remote job IDs, reviews and regeneration lineage are retained in audit/history. Publishing a cloud snapshot does not keep live processes running. See architecture documentation before production deployment.

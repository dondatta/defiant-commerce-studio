# Docker development environment

This Compose stack runs Python 3.12, PostgreSQL 17, a development web server, the generation worker and the scheduler. It is independent from CMM. The host only needs Docker Compose and Python 3.10+ for a one-time standard-library configuration helper; Ubuntu's Python 3.14 works for that helper. Application code and dependencies run in Python 3.12 containers.

## First start

From the cloned repository:

```bash
git pull --ff-only
python3 scripts/init_docker_env.py
docker compose up --build -d
docker compose ps -a
docker compose exec web python manage.py createsuperuser
```

Open `http://127.0.0.1:8000` in a browser on this development machine. Sign in with the account you just created. Setup automatically migrates the standalone PostgreSQL database and idempotently seeds the first brand. `setup` exiting with code 0 is expected; the other four services remain running. No default login/password is created.

The app port is bound to the development machine's loopback address. For access from another computer, use an SSH tunnel (`ssh -L 8000:127.0.0.1:8000 user@development-host`) and browse your computer's local port. Production/public hosting requires a separate production configuration with a WSGI server, HTTPS proxy, DEBUG disabled, secure cookies and production secrets; this Compose file is development-only and does not deploy anything to production.

If a previous `.env` exists, the helper preserves it. Add nonempty `DJANGO_SECRET_KEY` and `POSTGRES_PASSWORD` values privately and set `POSTGRES_DB=defiant_studio`, `POSTGRES_USER=defiant` as needed. Generate each secret locally with `python3 -c 'import secrets; print(secrets.token_urlsafe(64))'` and save it only to the untracked file. Do not post keys in chat or commit .env. The Compose stack explicitly uses PostgreSQL and development mode regardless of local Python/SQLite settings. Change `APP_PORT` if port 8000 is already occupied.

## Everyday commands

```bash
# Logs / readiness
docker compose logs --tail=100 setup web worker scheduler
docker compose ps -a

# Verify the application and tenant/database protections
docker compose exec web python manage.py check
docker compose exec web python manage.py test studio --verbosity 1

# Apply new source changes (source is copied into the image, not bind-mounted)
docker compose up --build -d --force-recreate setup web worker scheduler

# Stop; both data volumes are preserved
docker compose down

# Restart
docker compose up -d
```

Do not use `docker compose down -v` unless you intentionally want to erase the development database and private assets. Containers run application processes as UID 10001, share the private asset volume, and use a read-only root filesystem with a temporary /tmp. PostgreSQL has its own persistent volume and no host-exposed database port. This database is separate from any earlier native SQLite database; existing SQLite content is not migrated automatically. Database passwords are initialized when the PostgreSQL volume is first created; editing `.env` later does not rotate the existing database role's password.

## Providers and Shopify

The default .env contains optional empty bindings for `DEFIANT_IMAGE_API_KEY`, `SHOPIFY_INFATUATION_TOKEN`, and `COMFYUI_API_KEY`. Add credentials securely when ready, then recreate the application containers to inject changed environment variables:

```bash
docker compose up -d --force-recreate setup web worker scheduler
```

Configure the brand's provider/store to use the matching binding names. Other brand-specific binding names can also be added to .env; the app services load the full file. `COMFYUI_ALLOWED_HOSTS` can explicitly permit trusted private ComfyUI destinations. Inside a container, `127.0.0.1` refers to that container; use a reachable server hostname/IP for an external ComfyUI instance. See FIRST_IMAGES.md for real catalog/reference/provider prerequisites. Daily automation remains disabled until enabled in the brand settings; no automatic publishing exists.

## Troubleshooting

If Docker reports access denied to its socket, use your organization's approved Docker access method. If setup fails, inspect `docker compose logs setup db` before creating users. If the login page does not respond, inspect `docker compose logs web` and check for a port conflict. Check service health and actual HTTP response rather than relying only on a running-container status.

For a build behind a trusted corporate proxy, the Dockerfile accepts an optional BuildKit CA bundle without disabling TLS verification or retaining that bundle in the image:

```bash
docker build --secret id=build_ca_bundle,src=/path/to/trusted-ca-bundle.pem -t defiant-commerce-studio:dev .
docker compose up -d --no-build
```

Use a CA supplied by your environment/IT administrator. The default build uses the image's normal trust store. This build-time option does not configure runtime HTTPS trust for image providers.

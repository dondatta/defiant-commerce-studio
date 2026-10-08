FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /app

COPY requirements.lock /app/requirements.lock
RUN --mount=type=secret,id=build_ca_bundle,required=false \
    if [ -f /run/secrets/build_ca_bundle ]; then export PIP_CERT=/run/secrets/build_ca_bundle; fi; \
    python -m pip install --no-cache-dir -r requirements.lock \
    && groupadd --gid 10001 studio \
    && useradd --uid 10001 --gid studio --create-home studio \
    && mkdir -p /app/.private \
    && chown -R studio:studio /app

COPY --chown=studio:studio . /app
USER studio
EXPOSE 8000
CMD ["python", "manage.py", "runserver", "0.0.0.0:8000", "--noreload"]

FROM python:3.13.13-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PROPOSAL_APP_ENV=production \
    PROPOSAL_PROJECT_ROOT=/app \
    DJANGO_SETTINGS_MODULE=proposal_app.settings

RUN apt-get update \
    && apt-get install --no-install-recommends -y libpq5 \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --system app \
    && useradd --system --gid app --home-dir /app app

WORKDIR /app
COPY pyproject.toml README.md ./
COPY requirements-prod.lock ./
COPY config ./config
COPY prompts ./prompts
COPY src ./src
COPY scripts/app_recovery.py /app/scripts/app_recovery.py
RUN pip install --no-cache-dir -r requirements-prod.lock . \
    && mkdir -p /var/lib/proposal-ingest /app/staticfiles \
    && chown -R app:app /app /var/lib/proposal-ingest

USER app
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=3 \
    CMD python -c "import os,urllib.request; host=os.environ['PROPOSAL_ALLOWED_HOSTS'].split(',')[0]; req=urllib.request.Request('http://127.0.0.1:8000/login/',headers={'Host':host,'X-Forwarded-Proto':'https'}); urllib.request.urlopen(req,timeout=3)"

CMD ["sh", "-c", "python -m django collectstatic --noinput && exec gunicorn proposal_app.wsgi:application --bind=0.0.0.0:8000 --workers=2 --timeout=120 --error-logfile=-"]

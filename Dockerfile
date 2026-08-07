FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

RUN groupadd -g 10001 cloud \
    && useradd -u 10001 -g cloud -m -d /home/cloud -s /usr/sbin/nologin cloud

COPY requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt

COPY config /app/config
COPY app /app/app
COPY migrations /app/migrations
COPY alembic.ini /app/alembic.ini

RUN chown -R cloud:cloud /app

# Same reasoning as UrraHosting-WebPanel: no root->non-root drop at
# runtime because the compose hardening (cap_drop: ALL) removes the
# capabilities that would need. app.main:create_app() / webdav_app.py /
# worker/worker_main.py all create their own subdirectories under
# ${DATA_DIR} on first run.
USER cloud

# One image, three entrypoints selected by CMD override in compose.yml:
#   app    -> gunicorn app.main:app
#   webdav -> gunicorn app.webdav_app:app
#   worker -> python -m app.worker.worker_main
CMD ["sh", "-c", "exec gunicorn --bind 0.0.0.0:${APP_PORT:-5000} --workers 1 --threads 8 --timeout 1900 app.main:app"]

# coauthored-submit: one image for the Cloud Run service (web) and the Cloud Run job
# (`flask announce`, run daily by Cloud Scheduler).
FROM python:3.11-slim-bookworm AS build
# arxiv-base depends on mysqlclient, which compiles against the MySQL client library;
# git fetches arxiv-base at its pinned commit.
RUN apt-get update \
 && apt-get install -y --no-install-recommends build-essential pkg-config default-libmysqlclient-dev git \
 && rm -rf /var/lib/apt/lists/*
RUN pip install --no-cache-dir "uv>=0.9,<1"
WORKDIR /app
ENV UV_PROJECT_ENVIRONMENT=/opt/venv UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --no-dev

FROM python:3.11-slim-bookworm
RUN apt-get update \
 && apt-get install -y --no-install-recommends libmariadb3 \
 && rm -rf /var/lib/apt/lists/* \
 && useradd --system --uid 10001 --home /app app
COPY --from=build /opt/venv /opt/venv
WORKDIR /app
COPY submit ./submit
COPY scripts ./scripts
COPY wsgi.py ./
ENV PATH=/opt/venv/bin:$PATH PYTHONUNBUFFERED=1 FLASK_APP=submit:create_app PORT=8080
USER app
EXPOSE 8080
# The job overrides this with: flask announce
CMD ["sh", "-c", "exec gunicorn --bind \":${PORT}\" --workers 2 --threads 8 --timeout 120 wsgi:app"]

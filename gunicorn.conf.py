"""Gunicorn config — auto-loaded from the working directory.

Why each value:
- timeout=120: default 30s kills a worker whose event loop is blocked by a
  slow DB call under load, dropping in-flight payment requests. Gate/POS
  requests are fast; 120s only trips on genuine wedges.
- graceful_timeout: gives in-flight payments time to finish on reload.
- keepalive=75: default 5s churns connections behind nginx; nginx upstream
  keepalive needs a matching server-side value.
- max_requests/max_requests_jitter: recycle workers to cap RSS growth on
  long-running deployments (no --preload, no memory management before).
"""

bind = "127.0.0.1:8000"
workers = 4
worker_class = "uvicorn.workers.UvicornWorker"

timeout = 120
graceful_timeout = 60
keepalive = 75

max_requests = 1000
max_requests_jitter = 100

accesslog = "-"
errorlog = "-"

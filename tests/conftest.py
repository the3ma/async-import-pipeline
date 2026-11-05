import os

# Must match docker-compose.yml, so end-to-end tests can sign webhooks.
os.environ.setdefault("IMPORT_SECRET", "local-dev-secret")

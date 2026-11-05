FROM python:3.12-slim
COPY --from=ghcr.io/astral-sh/uv:0.5 /uv /bin/uv
WORKDIR /app
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --no-dev --no-install-project
COPY src ./src
RUN uv sync --frozen --no-dev
ENV PATH="/app/.venv/bin:$PATH"
RUN useradd --create-home app
USER app
CMD ["uvicorn", "importer.api:app", "--host", "0.0.0.0", "--port", "8000"]

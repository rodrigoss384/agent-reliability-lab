FROM python:3.12-slim

WORKDIR /app

RUN pip install uv

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen

COPY app/ ./app/
COPY openapi/ ./openapi/
COPY migrations/ ./migrations/
COPY scripts/ ./scripts/
COPY alembic.ini ./

EXPOSE 8000

CMD ["sh", "-c", "uv run python scripts/bootstrap.py && exec uv run uvicorn app.main:app --host 0.0.0.0 --port 8000"]

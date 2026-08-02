FROM python:3.12-slim AS builder
WORKDIR /app
RUN pip install --no-cache-dir uv
COPY pyproject.toml uv.lock* ./
RUN uv venv /venv && VIRTUAL_ENV=/venv uv pip install --no-cache .

FROM python:3.12-slim
RUN useradd -r -u 10001 app
COPY --from=builder /venv /venv
COPY src/ /app/src/
COPY migrations/ /app/migrations/
ENV PATH="/venv/bin:$PATH" PYTHONPATH=/app/src
# numeric UID so Kubernetes runAsNonRoot can verify it
USER 10001
EXPOSE 8003
CMD ["uvicorn", "rag_api.main:app", "--host", "0.0.0.0", "--port", "8003"]

.PHONY: sync run test test-db lint

sync:
	uv sync

run:
	uv run uvicorn rag_api.main:app --reload --port 8003

test:
	uv run pytest -v

test-db:  ## spins a throwaway pgvector and runs the integration tests
	docker run -d --rm -p 5433:5432 -e POSTGRES_PASSWORD=test --name ragpg pgvector/pgvector:pg17
	sleep 3
	TEST_DATABASE_URL=postgresql://postgres:test@localhost:5433/postgres uv run pytest -v; \
	  docker stop ragpg

lint:
	uv run ruff check src tests scripts && uv run mypy src

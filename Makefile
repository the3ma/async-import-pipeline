.PHONY: help up down logs lint test e2e bench

help:  ## list targets
	@grep -E '^[a-z0-9-]+:.*##' $(MAKEFILE_LIST) | sed 's/:.*## /\t/'

up:    ## build and start the local stack
	docker compose up -d --build --wait

down:  ## stop and remove containers and volumes
	docker compose down -v

logs:  ## follow the API and edge logs
	docker compose logs -f api api-replica edge

lint:  ## lint and format check
	uv run ruff check . && uv run ruff format --check .

test:  ## unit tests, no Docker needed
	uv run pytest -q

e2e:   ## end-to-end acceptance tests against the running stack
	uv run pytest -q -m e2e

bench: ## API cost and latency on this machine
	uv run python scripts/bench.py

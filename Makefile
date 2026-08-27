.PHONY: install dev up down test test-e2e test-golden lint verify frontend-build proto fetch-cadc smoke-4k

install:
	uv sync --all-groups
	cd frontend && pnpm install
	$(MAKE) proto

proto:
	uv run python -m grpc_tools.protoc -I schemas/protobuf --python_out=backend/src/most_sprite/schemas/generated --pyi_out=backend/src/most_sprite/schemas/generated --grpc_python_out=backend/src/most_sprite/schemas/generated schemas/protobuf/device_agent.proto
	uv run python tools/fix_proto_imports.py

dev:
	SPRITE_EMBEDDED_WORKERS=true uv run sprite-api

up:
	docker compose up --build

down:
	docker compose down

test:
	uv run pytest -m "not golden and not slow"
	cd frontend && pnpm exec vitest run
	cd frontend && pnpm build

test-e2e:
	cd frontend && pnpm e2e

test-golden:
	uv run pytest -m golden

lint:
	uv run ruff check backend tests tools
	uv run mypy backend/src
	uv run python tools/check_gamse_manifest.py
	cd frontend && pnpm lint
	@if rg -n '(^|[[:space:]])(from|import)[[:space:]]+gamse' backend tests tools; then echo 'Runtime GAMSE import is forbidden'; exit 1; fi

verify: lint test test-e2e
	docker compose config --quiet

frontend-build:
	cd frontend && pnpm build

fetch-cadc:
	uv run python tools/testdata/fetch_cadc.py

smoke-4k:
	uv run sprite-smoke-l0 --full-frame

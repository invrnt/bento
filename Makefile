.PHONY: dev up watch down logs doctor seed test setup backend-install frontend-install desktop-install backend-test frontend-test desktop-test desktop-build desktop-package desktop-make desktop-smoke desktop-verify desktop-release-artifacts smoke e2e two-devices pre-commit-install pre-commit pre-push

dev: up

up: setup
	docker compose up --build

watch: setup
	docker compose watch

down:
	docker compose down

logs:
	docker compose logs -f

setup: backend-install frontend-install
	uv run --project apps/api python scripts/setup/main.py

doctor:
	uv run --project apps/api python scripts/doctor/main.py

seed: backend-install
	uv run --project apps/api python scripts/seed/main.py

test: backend-test frontend-test desktop-test

backend-install:
	uv sync --project apps/api --extra dev

frontend-install:
	npm --prefix apps/web install

desktop-install:
	npm --prefix apps/desktop ci

backend-test: backend-install
	cd apps/api && uv run pytest

frontend-test: frontend-install
	npm --prefix apps/web test

desktop-test: desktop-install
	npm --prefix apps/desktop test

desktop-build: desktop-install frontend-install
	npm --prefix apps/desktop run build

desktop-package: desktop-install frontend-install backend-install
	npm --prefix apps/desktop run package

desktop-make: desktop-install frontend-install backend-install
	npm --prefix apps/desktop run make

desktop-smoke: desktop-package
	npm --prefix apps/desktop run smoke:packaged

desktop-verify:
	npm --prefix apps/desktop run verify:artifacts

desktop-release-artifacts: desktop-make
	npm --prefix apps/desktop run smoke:packaged
	npm --prefix apps/desktop run verify:artifacts
	npm --prefix apps/desktop run sbom
	npm --prefix apps/desktop run release:stage
	npm --prefix apps/desktop run checksums

smoke: backend-install
	cd apps/api && uv run pytest tests/smoke

e2e: backend-install
	cd apps/api && uv run pytest -m e2e

two-devices: backend-install
	uv run --project apps/api python scripts/smoke/two_devices.py

pre-commit-install: backend-install
	uv run --project apps/api pre-commit install --install-hooks

pre-commit: backend-install
	uv run --project apps/api pre-commit run --all-files

pre-push: backend-install frontend-install
	uv run --project apps/api pre-commit run --all-files --hook-stage pre-push

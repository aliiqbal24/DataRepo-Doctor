.PHONY: demo down seed test test-integration lint web-test build

demo:
	docker compose up --build

down:
	docker compose down

seed:
	docker compose run --rm configure

test:
	pytest tests/unit

test-integration:
	docker compose --profile test run --rm --build test

lint:
	ruff check .
	mypy src
	cd web && npm run lint && npm run typecheck

web-test:
	cd web && npm test -- --run

build:
	cd web && npm run build

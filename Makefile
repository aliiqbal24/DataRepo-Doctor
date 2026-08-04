.PHONY: demo down seed test test-integration lint web-test build

demo:
	docker compose up --build

down:
	docker compose down

seed:
	docker compose run --rm seed

test:
	pytest tests/unit

test-integration:
	pytest -m integration

lint:
	ruff check src demo_catalog tests
	mypy src/datarepo_doctor
	cd web && npm run lint && npm run typecheck

web-test:
	cd web && npm test -- --run

build:
	cd web && npm run build


.PHONY: demo down seed test test-integration lint build

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

build:
	docker compose build app

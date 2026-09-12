.PHONY: lint test ci

lint:
	python3 -m ruff check .
	python3 -m ruff format --check .

test:
	python3 -m pytest

ci: lint test

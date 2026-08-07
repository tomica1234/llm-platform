PYTHON ?= .venv/bin/python

.PHONY: bootstrap format lint typecheck test test-integration test-security test-hardware coverage check

bootstrap:
	./scripts/bootstrap-dev.sh

format:
	$(PYTHON) -m ruff format .
	$(PYTHON) -m ruff check --fix .

lint:
	$(PYTHON) -m ruff format --check .
	$(PYTHON) -m ruff check .

typecheck:
	$(PYTHON) -m mypy src

test:
	$(PYTHON) -m pytest -m "not integration and not security and not hardware"

test-integration:
	$(PYTHON) -m pytest -m integration

test-security:
	$(PYTHON) -m pytest -m security
	./scripts/check-secrets.sh

test-hardware:
	LLM_PLATFORM_HARDWARE_TESTS=1 $(PYTHON) -m pytest -m hardware

coverage:
	$(PYTHON) -m coverage erase
	$(PYTHON) -m pytest -m "not hardware" --cov --cov-report=term-missing

check: lint typecheck test test-integration test-security coverage

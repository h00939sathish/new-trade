.PHONY: install dev lint test run db-up db-down clean

install:
	pip install -e .
	pip install -e ".[dev,kite]"

dev:
	pip install -e ".[dev,kite,ml]"

lint:
	ruff check src/
	ruff format --check src/ tests/
	mypy src/

test:
	pytest tests/ -v --cov=src

db-up:
	docker compose up -d postgres redis

db-down:
	docker compose down

run-market-intel:
	python -m src.agents.market_intel

run-strategy-gen:
	python -m src.agents.strategy_gen

run-risk-mgmt:
	python -m src.agents.risk_mgmt

run-execution:
	python -m src.agents.execution

replay:
	python scripts/replay_events.py

clean:
	rm -rf __pycache__ .pytest_cache *.egg-info
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true

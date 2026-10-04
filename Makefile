.PHONY: install fixtures test demo app

install:
	python -m venv .venv && .venv\Scripts\pip install -e ".[dev]"

fixtures:
	python scripts\build_fixtures.py

test:
	pytest -q

demo:
	python scripts\run_demo.py

app:
	streamlit run policyfuzz\ui\app.py

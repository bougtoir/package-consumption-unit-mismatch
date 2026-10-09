PYTHON ?= python3
VENV ?= .venv
VENV_PYTHON := $(VENV)/bin/python

.PHONY: all setup sources data reproduce analysis figures tables manuscript audits verification reports package test lint clean

all: package

setup:
	$(PYTHON) -m venv $(VENV)
	$(VENV_PYTHON) -m pip install --upgrade pip
	$(VENV_PYTHON) -m pip install -e ".[dev]"

sources:
	PYTHONPATH=src $(VENV_PYTHON) analysis/verify_sources.py

data: sources
	PYTHONPATH=src $(VENV_PYTHON) analysis/prepare_data.py

reproduce:
	PYTHONPATH=src $(VENV_PYTHON) analysis/prepare_data.py
	PYTHONPATH=src $(VENV_PYTHON) analysis/run_analysis.py
	PYTHONPATH=src $(VENV_PYTHON) analysis/run_revision_analyses.py
	PYTHONPATH=src $(VENV_PYTHON) analysis/build_figures.py
	PYTHONPATH=src $(VENV_PYTHON) analysis/build_tables.py

analysis: data
	PYTHONPATH=src $(VENV_PYTHON) analysis/run_analysis.py
	PYTHONPATH=src $(VENV_PYTHON) analysis/run_revision_analyses.py

figures: analysis
	PYTHONPATH=src $(VENV_PYTHON) analysis/build_figures.py

tables: analysis
	PYTHONPATH=src $(VENV_PYTHON) analysis/build_tables.py

manuscript: figures tables
	PYTHONPATH=src $(VENV_PYTHON) analysis/build_manuscript.py

audits: manuscript
	PYTHONPATH=src $(VENV_PYTHON) analysis/run_audits.py

verification: audits test lint

reports: verification
	PYTHONPATH=src $(VENV_PYTHON) analysis/build_reports.py

package: reports
	PYTHONPATH=src $(VENV_PYTHON) analysis/build_submission.py

test:
	mkdir -p reports
	PYTHONPATH=src $(VENV_PYTHON) -m pytest -q > reports/test_log.txt
	cat reports/test_log.txt

lint:
	mkdir -p reports
	$(VENV_PYTHON) -m ruff check src analysis tests > reports/lint_log.txt
	cat reports/lint_log.txt

clean:
	rm -rf data/interim/* data/processed/* figures/* tables/* output/*
	rm -rf manuscript/*.docx manuscript/*.txt
	find reports -maxdepth 1 -type f \
		! -name PRE_REVISION_FREEZE.md \
		! -name FINAL_ANALYSIS_FREEZE.md \
		! -name FINAL_LITERATURE_POSITIONING_AUDIT.md \
		-delete
	rm -rf reports/rendered
	rm -rf submission/* release/*
	rm -rf .pytest_cache .ruff_cache src/pcum.egg-info

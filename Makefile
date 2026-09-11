PYTHON ?= python3
PYTHON_DIR := $(dir $(shell $(PYTHON) -c 'import sys; print(sys.executable)'))
export PATH := $(PYTHON_DIR):$(PATH)

.PHONY: setup pytest selftest regression verify test benchmark evidence demo

setup:
	$(PYTHON) dev_set/basic/build_dbs.py

pytest: setup
	$(PYTHON) -m pytest

selftest:
	$(PYTHON) skills/code-author-loweiwei/scripts/selftest.py
	$(PYTHON) skills/bug-hunter-loweiwei/scripts/selftest.py
	$(PYTHON) skills/open-test-killer-loweiwei/scripts/selftest.py

regression:
	$(PYTHON) skills/code-author-loweiwei/scripts/regression.py
	$(PYTHON) skills/bug-hunter-loweiwei/scripts/regression.py
	$(PYTHON) skills/open-test-killer-loweiwei/scripts/regression.py

verify:
	$(PYTHON) verify_repo.py --github-id loweiwei

test: pytest selftest regression verify

benchmark:
	$(PYTHON) scripts/run_benchmarks.py
	$(PYTHON) scripts/run_component_ablations.py
	$(PYTHON) scripts/summarize_dev_runs.py
	$(PYTHON) scripts/summarize_controlled_experiment.py experiments/gemma4_validated_3x.json
	$(PYTHON) scripts/evaluate_matched_baseline.py

evidence: setup
	$(PYTHON) scripts/run_verification.py

demo: selftest benchmark

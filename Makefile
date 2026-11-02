# Thin wrappers over the release tooling. Every target runs the project venv
# interpreter, so nothing depends on a system python having the deps.
#
#   make test                  full pytest suite (parallel, pytest-xdist)
#   make test-fast             suite without the slow and SEP-fixture tests
#   make test-sep              only the SEP regression-fixture tests
#   make gates                 every CI gate except the test suite
#   make preflight             every CI gate, then the test suite
#   make examples              regenerate every example + re-export stale rasters
#   make examples-check        write nothing; fail if an example or raster is stale
#   make bump VERSION=X.Y.Z    rewrite every version pin, date the CHANGELOG
#   make publish               push, PR, wait for checks, merge, tag the merge commit

PYTHON ?= $(if $(wildcard .venv/bin/python),.venv/bin/python,python3)
export PYTHONPATH := src

.PHONY: test test-fast test-sep gates preflight examples examples-check bump bump-dry publish publish-dry

test:
	$(PYTHON) -m pytest -q -n auto

test-fast:
	$(PYTHON) -m pytest -q -n auto -m "not slow and not sep"

test-sep:
	$(PYTHON) -m pytest -q -n auto -m sep

gates:
	$(PYTHON) scripts/release.py preflight --fast

preflight:
	$(PYTHON) scripts/release.py preflight

examples:
	$(PYTHON) scripts/regen_examples.py

examples-check:
	$(PYTHON) scripts/regen_examples.py --check

bump:
	@test -n "$(VERSION)" || { echo "usage: make bump VERSION=X.Y.Z"; exit 2; }
	$(PYTHON) scripts/release.py bump $(VERSION)

bump-dry:
	@test -n "$(VERSION)" || { echo "usage: make bump-dry VERSION=X.Y.Z"; exit 2; }
	$(PYTHON) scripts/release.py bump $(VERSION) --dry-run

publish:
	$(PYTHON) scripts/release.py publish

publish-dry:
	$(PYTHON) scripts/release.py publish --dry-run

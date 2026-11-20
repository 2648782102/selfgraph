PYTHON ?= python3
BASE ?= origin/main

.PHONY: precheck probes

precheck:
	$(PYTHON) scripts/precheck.py --base $(BASE)

probes:
	@fail=0; for p in parity_table plan_apply secret_echo unmerge_order; do \
		echo "===== $$p ====="; \
		$(PYTHON) scripts/probes/$$p.py || fail=1; \
		echo; \
	done; \
	exit $$fail

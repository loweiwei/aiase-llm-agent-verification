#!/usr/bin/env python3
"""Offline regression entry point for open-test-killer-loweiwei.

The detailed checks live in selftest.py: public scenarios, stdout/result-file
contract, perturbations for task_id/order/id changes, irrelevant candidates, and
smaller max_tests. This wrapper gives graders and maintainers a stable
regression command without duplicating evaluator logic.
"""

from __future__ import annotations

import selftest


if __name__ == "__main__":
    raise SystemExit(selftest.main())

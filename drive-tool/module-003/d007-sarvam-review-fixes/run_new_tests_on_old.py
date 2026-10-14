"""Run the NEW committed tests against the OLD adapter to prove they fail there.

A minimal shim supplies the two helper names the new tests import (the old
module predates them); nothing else about the old adapter is changed.
"""
import drive_tool.local as L
if not hasattr(L, "_no_follow_semantics_available"):
    L._no_follow_semantics_available = lambda: True
import unittest
loader = unittest.TestLoader()
suite = loader.loadTestsFromName("tests.test_local")
res = unittest.TextTestRunner(verbosity=1).run(suite)
raise SystemExit(0 if res.wasSuccessful() else 1)

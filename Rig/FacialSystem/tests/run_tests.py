"""Run stdlib tests. Actual Maya API evaluation is outside this test suite."""
from pathlib import Path
import sys
import unittest

here = Path(__file__).resolve().parent
sys.path.insert(0, str(here.parent))
sys.path.insert(0, str(here / 'attachments'))
loader = unittest.TestLoader()
suite = unittest.TestSuite()
suite.addTests(loader.discover(str(here / 'attachments'), pattern='test_*.py'))
# Use a fresh loader because discover's top-level import root changes here.
suite.addTests(unittest.TestLoader().discover(str(here), pattern='test_*.py'))
result = unittest.TextTestRunner(verbosity=2).run(suite)
raise SystemExit(0 if result.wasSuccessful() else 1)

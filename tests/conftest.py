import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ.setdefault("YAHMI_DB", os.path.join(tempfile.mkdtemp(), "test.db"))
os.environ.setdefault("YAHMI_KEY", "test-key-not-secret")
FIXTURES = os.path.join(ROOT, "tests", "fixtures")

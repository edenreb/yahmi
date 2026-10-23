import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ.setdefault("YAHMI_DB", os.path.join(tempfile.mkdtemp(), "test.db"))
os.environ.setdefault("YAHMI_KEY", "test-key-not-secret")
os.environ["YAHMI_ENABLE_WHATSAPP"] = "1"   # the WhatsApp tests need the routes (they are off by default)
os.environ["YAHMI_ACCESS_CODES"] = "c-biz=Test Interiors LLC,c-new=Brand New Co,c-meta=meta-test,c-sim-wrong=sim-test-wrong,c-sim-ok=sim-test-ok"
os.environ["YAHMI_DOMAIN_AGE"] = "0"  # the tests never contact a domain registry
FIXTURES = os.path.join(ROOT, "tests", "fixtures")

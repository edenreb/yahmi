"""One command for the demo: starts the SIMULATED FTA gateway on :8010 and Yahmi on :8000, wired together.

    python3 tools/run_simulated_demo.py

Every TRN result in this mode is labelled "SIMULATION" and cites a simulated registry, never the FTA.
To use the real service later, drop this script and set the YAHMI_FTA_* variables from the README instead.
"""
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
from fake_fta_gateway import DEMO_API_KEY, DEMO_CLIENT  # noqa: E402

GW = "http://127.0.0.1:8010"
os.environ.update({
    "YAHMI_FTA_BASE_URL": f"{GW}/gateway/validateTRNDetails_FTAX/1.0",
    "YAHMI_FTA_TOKEN_URL": f"{GW}/invoke/pub.apigateway.oauth2/getAccessToken",
    "YAHMI_FTA_API_KEY": DEMO_API_KEY,
    "YAHMI_FTA_CLIENT_ID": DEMO_CLIENT[0],
    "YAHMI_FTA_CLIENT_SECRET": DEMO_CLIENT[1],
})
gateway = subprocess.Popen([sys.executable, "-m", "uvicorn", "fake_fta_gateway:app", "--app-dir", HERE, "--port", "8010", "--log-level", "warning"])
try:
    print("SIMULATED FTA gateway on", GW, "| Yahmi on http://127.0.0.1:8000 (try tests/fixtures/wrong_trn.pdf)")
    os.chdir(ROOT)
    sys.path.insert(0, ROOT)
    import uvicorn
    uvicorn.run("yahmi.app:app", port=8000)
finally:
    gateway.terminate()

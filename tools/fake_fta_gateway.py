"""SIMULATED FTA gateway for demos and tests. It is NOT the Federal Tax Authority and holds NO real registrations.

It mimics the published shape of the validateTRNDetails_FTAX service on the UAE API Marketplace (OAuth client-credentials
token, `GW-APIKey` header, POST /api/prc/trn/v1/gsbvalidatetrn, response `[{"NameEn", "NameAr"}]`, the sample 400 and 401
bodies) so Yahmi's real client code runs end to end before official access exists. Every company and TRN below is invented.

Run: uvicorn fake_fta_gateway:app --app-dir tools --port 8010
"""
from fastapi import FastAPI, Form, Header, Request
from fastapi.responses import JSONResponse

DEMO_CLIENT = ("demo-client", "demo-secret")
DEMO_API_KEY = "demo-api-key"
DEMO_TOKEN = "demo-token"

# Invented TRNs and companies (synthetic demo data).
REGISTRY = {
    "100384920571003": ("Falcon Building Materials LLC", "شركة فالكون لمواد البناء ذ.م.م"),
    "100555512340003": ("Blue Creek Logistics LLC", "شركة بلو كريك للخدمات اللوجستية ذ.م.م"),
    "100771234560003": ("Sample Customer LLC", "شركة العميل النموذجية ذ.م.م"),
    "100222233340003": ("Al Noor Trading Co LLC", "شركة النور للتجارة ذ.م.م"),
}

app = FastAPI(title="SIMULATED FTA gateway (demo data)")


@app.get("/")
def banner():
    return {"notice": "SIMULATED FTA gateway for demos and tests. Not the Federal Tax Authority. All data is invented.", "trns": len(REGISTRY)}


@app.post("/invoke/pub.apigateway.oauth2/getAccessToken")
async def token(request: Request, grant_type: str = Form("")):
    import base64
    auth = request.headers.get("authorization", "")
    try:
        user, _, pw = base64.b64decode(auth.split(" ", 1)[1]).decode().partition(":")
    except Exception:
        user = pw = ""
    if grant_type != "client_credentials" or (user, pw) != DEMO_CLIENT:
        return JSONResponse({"error": "invalid_client"}, status_code=401)
    return {"access_token": DEMO_TOKEN, "token_type": "Bearer", "expires_in": 300}


@app.post("/gateway/validateTRNDetails_FTAX/1.0/api/prc/trn/v1/gsbvalidatetrn")
async def validate(request: Request, gw_apikey: str = Header(""), authorization: str = Header("")):
    if gw_apikey != DEMO_API_KEY or authorization != f"Bearer {DEMO_TOKEN}":
        return JSONResponse({"Exception": "API Gateway encountered an error. Error Message:  Unauthorized application request."}, status_code=401)
    trn = request.query_params.get("TRN")
    if trn is None:
        try:
            trn = (await request.json()).get("TRN")
        except Exception:
            trn = None
    trn = trn or ""
    if len(trn) != 15:
        return JSONResponse({"errorCode": "400", "errorMessage": "Bad request",
                             "description": f"Invalid value '{trn}' for query parameter TRN. expected minLength: 15, actual: {len(trn)}"}, status_code=400)
    if trn not in REGISTRY:
        return JSONResponse({"errorCode": "404", "errorMessage": "Not found", "description": "No registration for this TRN (simulated)"}, status_code=404)
    en, ar = REGISTRY[trn]
    return [{"NameEn": en, "NameAr": ar}]

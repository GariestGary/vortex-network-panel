from __future__ import annotations

import hmac
import os

from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse

from .adapter import ProductionAdapter


app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
app.router.redirect_slashes = False
adapter = ProductionAdapter()


@app.get("/s/{token}")
def subscription(token: str):
    expected_token = os.getenv("VORTEX_SUBSCRIPTION_TOKEN")
    device_name = os.getenv("VORTEX_SUBSCRIPTION_DEVICE")
    if not expected_token or not device_name or not hmac.compare_digest(token, expected_token):
        raise HTTPException(status_code=404)

    try:
        config = adapter.client_config(device_name)
    except (ConnectionError, KeyError, OSError, ValueError):
        raise HTTPException(status_code=404) from None

    return JSONResponse(content=config, headers={"Cache-Control": "no-store"})

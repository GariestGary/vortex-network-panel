from __future__ import annotations

from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse

from .adapter import ProductionSubscriptionAdapter


app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
app.router.redirect_slashes = False
adapter = ProductionSubscriptionAdapter()


@app.get("/s/{token}")
def subscription(token: str):
    try:
        config = adapter.client_config(token)
    except (ConnectionError, KeyError, OSError, ValueError):
        raise HTTPException(status_code=404) from None
    return JSONResponse(content=config, headers={"Cache-Control": "no-store"})
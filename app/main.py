from __future__ import annotations
import os, json
from fastapi import FastAPI, Request, Form, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware
from .adapter import MockAdapter, ProductionAdapter
from .models import Device, is_preferred_device_name


MODE = os.getenv("VORTEX_MODE", "mock")
SESSION_SECRET = os.getenv("VORTEX_SESSION_SECRET")
if MODE not in {"mock", "production"}:
    raise RuntimeError("VORTEX_MODE must be mock or production")
if MODE == "production" and (not SESSION_SECRET or SESSION_SECRET.startswith("unsafe-") or SESSION_SECRET.startswith("replace-")):
    raise RuntimeError("Production requires a non-placeholder VORTEX_SESSION_SECRET")
if not SESSION_SECRET:
    SESSION_SECRET = "unsafe-development-secret-change-me"

app=FastAPI(title="VORTEX Network Panel")
app.mount("/static",StaticFiles(directory="static"),name="static")
templates=Jinja2Templates(directory="templates")
adapter = MockAdapter() if MODE == "mock" else ProductionAdapter()
def ctx(request, **kwargs):
    return {"request":request,"mode":MODE,"is_preferred_device_name":is_preferred_device_name,"flash":request.session.pop("flash",None),**kwargs}
def set_flash(request, message):
    request.session["flash"] = message
def csrf(request):
    token=request.headers.get("x-csrf-token") or request.query_params.get("csrf")
    if token != request.session.get("csrf"): raise HTTPException(403,"CSRF validation failed")
@app.middleware("http")
async def local_host(request, call_next):
    host=request.headers.get("host","").split(":")[0]
    if host not in {"localhost","127.0.0.1","testserver"}: return Response("Invalid Host",400)
    if "csrf" not in request.session:
        import secrets; request.session["csrf"]=secrets.token_urlsafe(24)
    return await call_next(request)
app.add_middleware(SessionMiddleware, secret_key=SESSION_SECRET, https_only=False, same_site="strict")
@app.exception_handler(ValueError)
async def invalid_request(request: Request, exc: ValueError):
    return Response(f"Request rejected: {exc}", status_code=400, media_type="text/plain")
@app.exception_handler(OSError)
async def unavailable(request: Request, exc: OSError):
    return Response("VORTEX control service is unavailable. Check the host-agent socket and service status.", status_code=503, media_type="text/plain")
@app.exception_handler(KeyError)
async def invalid_state(request: Request, exc: KeyError):
    return Response("Panel state is incomplete or invalid.", status_code=503, media_type="text/plain")
@app.exception_handler(json.JSONDecodeError)
async def invalid_json(request: Request, exc: json.JSONDecodeError):
    return Response("Panel state JSON is invalid.", status_code=503, media_type="text/plain")
@app.get("/",response_class=HTMLResponse)
def overview(request:Request): return templates.TemplateResponse(request,"overview.html",ctx(request,status=adapter.status(),csrf=request.session["csrf"]))
@app.get("/devices",response_class=HTMLResponse)
def devices(request:Request): return templates.TemplateResponse(request,"devices.html",ctx(request,devices=adapter.devices(),can_toggle=adapter.can_toggle_devices,csrf=request.session["csrf"]))
@app.post("/devices")
def add_device(request:Request,name:str=Form(...)):
    csrf(request)
    try:
        adapter.add_device(name)
    except ValueError as exc:
        return templates.TemplateResponse(request,"devices.html",ctx(request,devices=adapter.devices(),can_toggle=adapter.can_toggle_devices,csrf=request.session["csrf"],error=str(exc)),status_code=422)
    return RedirectResponse("/devices",303)
@app.post("/devices/{name}/{action}")
def device_action(request:Request,name:str,action:str):
    csrf(request)
    if action not in {"enable","disable","delete","rotate"}: raise HTTPException(404)
    try:
        adapter.change_device(name,action)
    except ValueError as exc:
        return templates.TemplateResponse(request,"devices.html",ctx(request,devices=adapter.devices(),can_toggle=adapter.can_toggle_devices,csrf=request.session["csrf"],error=str(exc)),status_code=404)
    return RedirectResponse("/devices",303)
@app.get("/devices/{name}/config")
def config(request:Request,name:str):
    try:
        payload=adapter.client_config(name)
    except ValueError: raise HTTPException(404)
    return Response(json.dumps(payload,indent=2),media_type="application/json",headers={"Content-Disposition":"attachment; filename=\"vortex-client.json\""})
@app.get("/devices/{name}/subscription-token")
def subscription_token(name: str):
    try:
        token = adapter.subscription_token(name)
    except (ConnectionError, ValueError):
        raise HTTPException(404) from None
    return Response(json.dumps({"token": token}), media_type="application/json", headers={"Cache-Control": "no-store"})

@app.post("/devices/{name}/subscription-token/rotate")
def rotate_subscription_token(request: Request, name: str):
    csrf(request)
    try:
        token = adapter.rotate_subscription_token(name)
    except (ConnectionError, ValueError):
        raise HTTPException(404) from None
    return Response(json.dumps({"token": token}), media_type="application/json", headers={"Cache-Control": "no-store"})

@app.post("/devices/{name}/subscription-token/revoke", status_code=204)
def revoke_subscription_token(request: Request, name: str):
    csrf(request)
    try:
        adapter.revoke_subscription_token(name)
    except (ConnectionError, ValueError):
        raise HTTPException(404) from None
@app.get("/routing",response_class=HTMLResponse)
def routing(request:Request): return templates.TemplateResponse(request,"routing.html",ctx(request,routes=adapter.routing(),csrf=request.session["csrf"]))
def routing_flash(target, domain, remove, result):
    action = "removed from" if remove else "added to"
    label = "Force Direct" if target == "direct" else "Force VPN"
    outcome = result.get("result", "SUCCESS") if isinstance(result, dict) else "SUCCESS"
    if outcome == "SUCCESS":
        return f"{domain} {action} {label}"
    if outcome == "APPLY_FAILED_ROLLED_BACK":
        verb = "remove" if remove else "add"
        return f"Failed to {verb} {domain}. Previous configuration was restored."
    if outcome == "APPLY_FAILED_ROLLBACK_FAILED":
        return "CRITICAL: apply failed and automatic rollback also failed."
    return "Rule was not applied: validation failed."

@app.post("/routing/{target}")
def change_route(request:Request,target:str,domain:str=Form(...),remove:bool=Form(False)):
    csrf(request)
    if target not in {"vpn","direct"}: raise HTTPException(404)
    normalized = domain.strip().lower()
    try:
        result = adapter.route_change(target,normalized,remove)
        set_flash(request, routing_flash(target, normalized, remove, result))
    except ValueError:
        set_flash(request, "Rule was not applied: validation failed.")
    return RedirectResponse("/routing",303)
@app.get("/ingress",response_class=HTMLResponse)
def ingress(request:Request): return templates.TemplateResponse(request,"ingress.html",ctx(request,status=adapter.status(),csrf=request.session["csrf"]))
@app.get("/diagnostics",response_class=HTMLResponse)
def diagnostics(request:Request): return templates.TemplateResponse(request,"diagnostics.html",ctx(request,diagnostics=adapter.diagnostics(),csrf=request.session["csrf"]))
@app.get("/backups",response_class=HTMLResponse)
def backups(request:Request): return templates.TemplateResponse(request,"backups.html",ctx(request,backups=adapter.backups_view(),can_restore=adapter.can_restore_backups,csrf=request.session["csrf"]))
@app.post("/backups/{backup_id}/restore")
def restore_backup(request:Request,backup_id:str):
    csrf(request)
    if not adapter.can_restore_backups: raise HTTPException(404)
    adapter.restore_backup(backup_id)
    return RedirectResponse("/backups",303)
@app.get("/settings",response_class=HTMLResponse)
def settings(request:Request): return templates.TemplateResponse(request,"settings.html",ctx(request,status=adapter.status(),csrf=request.session["csrf"]))

from __future__ import annotations
import os, json
from pathlib import Path
from urllib.parse import urlsplit
from fastapi import FastAPI, Request, Form, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware
from .adapter import MockAdapter, ProductionAdapter
from .models import Device, RouteEntry, is_preferred_device_name
from .routing_folders import RoutingFolders


MODE = os.getenv("VORTEX_MODE", "mock")
SESSION_SECRET = os.getenv("VORTEX_SESSION_SECRET")
if MODE not in {"mock", "production"}:
    raise RuntimeError("VORTEX_MODE must be mock or production")
if MODE == "production" and (not SESSION_SECRET or SESSION_SECRET.startswith("unsafe-") or SESSION_SECRET.startswith("replace-")):
    raise RuntimeError("Production requires a non-placeholder VORTEX_SESSION_SECRET")
PUBLIC_SUBSCRIPTION_URL = os.getenv("VORTEX_PUBLIC_SUBSCRIPTION_URL", "").rstrip("/")
if MODE == "production" and not PUBLIC_SUBSCRIPTION_URL:
    raise RuntimeError("Production requires VORTEX_PUBLIC_SUBSCRIPTION_URL")
if PUBLIC_SUBSCRIPTION_URL:
    parsed_subscription_url = urlsplit(PUBLIC_SUBSCRIPTION_URL)
    if parsed_subscription_url.scheme != "https" or not parsed_subscription_url.netloc or parsed_subscription_url.path or parsed_subscription_url.query or parsed_subscription_url.fragment or parsed_subscription_url.username or parsed_subscription_url.password:
        raise RuntimeError("VORTEX_PUBLIC_SUBSCRIPTION_URL must be an HTTPS origin without a path, query, fragment, or credentials")
if not SESSION_SECRET:
    SESSION_SECRET = "unsafe-development-secret-change-me"

app=FastAPI(title="VORTEX Network Panel")
app.mount("/static",StaticFiles(directory="static"),name="static")
templates=Jinja2Templates(directory="templates")
adapter = MockAdapter() if MODE == "mock" else ProductionAdapter()
routing_folders = RoutingFolders(Path(os.getenv("VORTEX_PANEL_DATA_DIR", "mock" if MODE == "mock" else "/var/lib/vortex-panel")) / "routing-folders.json")
def ctx(request, **kwargs):
    return {"request":request,"mode":MODE,"is_preferred_device_name":is_preferred_device_name,"flash":request.session.pop("flash",None),"public_subscription_url":PUBLIC_SUBSCRIPTION_URL,**kwargs}
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

@app.post("/devices/{name}/subscription/rotate")
def rotate_subscription_token(request: Request, name: str):
    csrf(request)
    try:
        adapter.rotate_subscription_token(name)
    except (ConnectionError, ValueError):
        raise HTTPException(404) from None
    return RedirectResponse("/devices", 303)

@app.post("/devices/{name}/subscription/revoke")
def revoke_subscription_token(request: Request, name: str):
    csrf(request)
    try:
        adapter.revoke_subscription_token(name)
    except (ConnectionError, ValueError):
        raise HTTPException(404) from None
    return RedirectResponse("/devices", 303)

@app.get("/routing/state")
def routing_state(request: Request):
    return JSONResponse({"routes": routing_folders.state(adapter.routing())}, headers={"Cache-Control":"no-store"})
def folder_response(fn):
    try: return JSONResponse({"ok":True,"routes":routing_folders.state(adapter.routing()),"result":fn()})
    except ValueError as exc: raise HTTPException(400,str(exc)) from None
@app.post("/routing/folders/{target}")
def create_folder(request:Request,target:str,name:str=Form(...)):
    csrf(request)
    if target not in {"vpn","direct"}: raise HTTPException(404)
    return folder_response(lambda:routing_folders.create(target,name))
@app.post("/routing/folders/{target}/{folder_id}/rename")
def rename_folder(request:Request,target:str,folder_id:str,name:str=Form(...)):
    csrf(request)
    return folder_response(lambda:routing_folders.rename(target,folder_id,name))
@app.post("/routing/folders/{target}/{folder_id}/move")
def move_folder_domain(request:Request,target:str,folder_id:str,domain:str=Form(...)):
    csrf(request); domain=RouteEntry(domain=domain).domain
    if domain not in adapter.routing().get(target,[]): raise HTTPException(404,"Routing domain not found")
    return folder_response(lambda:routing_folders.move(target,domain,folder_id))
@app.post("/routing/folders/{target}/{folder_id}/delete")
def delete_folder(request:Request,target:str,folder_id:str,mode:str=Form(...)):
    csrf(request); routes=routing_folders.state(adapter.routing())[target]; domains=[d for d,f in routes["assignments"].items() if f==folder_id]
    if mode=="common": return folder_response(lambda:routing_folders.delete(target,folder_id))
    if mode!="domains": raise HTTPException(400,"Unknown delete mode")
    failed=[]
    for domain in domains:
        try:
            result=adapter.route_change(target,domain,True)
            if isinstance(result,dict) and result.get("result") not in {None,"SUCCESS"}: failed.append(domain)
        except (ValueError,OSError): failed.append(domain)
    if failed: raise HTTPException(409,"Could not remove: "+", ".join(failed))
    return folder_response(lambda:routing_folders.delete(target,folder_id))
@app.post("/routing/mutate/{target}")
def routing_mutate(request:Request,target:str,domain:str=Form(...),remove:bool=Form(False),folder_id:str=Form("common")):
    csrf(request); domain=RouteEntry(domain=domain).domain
    try: result=adapter.route_change(target,domain,remove)
    except ValueError as exc: raise HTTPException(400,str(exc)) from None
    if isinstance(result,dict) and result.get("result") not in {None,"SUCCESS"}: raise HTTPException(409,routing_flash(target,domain,remove,result))
    if remove: routing_folders.move(target,domain,"common")
    else: routing_folders.move(target,domain,folder_id)
    return JSONResponse({"ok":True,"routes":routing_folders.state(adapter.routing())})
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
@app.get("/settings/client-config", response_class=HTMLResponse)
def client_config_settings(request: Request):
    current = adapter.client_template()
    return templates.TemplateResponse(request, "client_config.html", ctx(request, template=current["template"], revision=current["revision"], versions=adapter.client_template_versions(), csrf=request.session["csrf"]))

@app.post("/settings/client-config/validate")
def validate_client_config(request: Request, template: str = Form(...)):
    csrf(request)
    return JSONResponse(adapter.validate_client_template(template), headers={"Cache-Control": "no-store"})

@app.post("/settings/client-config/save")
def save_client_config(request: Request, template: str = Form(...), expected_revision: str = Form(...)):
    csrf(request)
    try:
        result = adapter.save_client_template(template, expected_revision)
    except ValueError as exc:
        if "changed; reload" in str(exc): raise HTTPException(409, "Client template changed; reload before saving") from None
        raise HTTPException(400, "Client template was not saved") from None
    return JSONResponse(result, status_code=200 if result.get("valid") else 422, headers={"Cache-Control": "no-store"})

@app.post("/settings/client-config/restore/{version_id}")
def restore_client_config(request: Request, version_id: str, expected_revision: str = Form(...)):
    csrf(request)
    try:
        result = adapter.restore_client_template_version(version_id, expected_revision)
    except ValueError as exc:
        if "changed; reload" in str(exc): raise HTTPException(409, "Client template changed; reload before restoring") from None
        raise HTTPException(404, "Client template version not found") from None
    return JSONResponse(result, status_code=200 if result.get("valid") else 422, headers={"Cache-Control": "no-store"})
@app.get("/settings",response_class=HTMLResponse)
def settings(request:Request): return templates.TemplateResponse(request,"settings.html",ctx(request,status=adapter.status(),csrf=request.session["csrf"]))

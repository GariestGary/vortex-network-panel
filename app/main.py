from __future__ import annotations
import os, json
from fastapi import FastAPI, Request, Form, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware
from .adapter import MockAdapter, ProductionAdapter
from .models import Device


app=FastAPI(title="VORTEX Network Panel")
app.mount("/static",StaticFiles(directory="static"),name="static")
templates=Jinja2Templates(directory="templates")
adapter = MockAdapter() if os.getenv("VORTEX_MODE", "mock") == "mock" else ProductionAdapter()
def ctx(request, **kwargs): return {"request":request,"mode":os.getenv("VORTEX_MODE","mock"),**kwargs}
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
app.add_middleware(SessionMiddleware, secret_key=os.getenv("VORTEX_SESSION_SECRET","unsafe-development-secret-change-me"), https_only=False, same_site="strict")
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
def devices(request:Request): return templates.TemplateResponse(request,"devices.html",ctx(request,devices=adapter.devices(),csrf=request.session["csrf"]))
@app.post("/devices")
def add_device(request:Request,name:str=Form(...)):
    csrf(request)
    name = "-".join(name.strip().upper().split())
    try:
        adapter.add_device(name)
    except ValueError as exc:
        return templates.TemplateResponse(request,"devices.html",ctx(request,devices=adapter.devices(),csrf=request.session["csrf"],error=str(exc)),status_code=422)
    return RedirectResponse("/devices",303)
@app.post("/devices/{name}/{action}")
def device_action(request:Request,name:str,action:str):
    csrf(request)
    if action not in {"enable","disable","delete","rotate"}: raise HTTPException(404)
    try:
        adapter.change_device(name,action)
    except ValueError as exc:
        return templates.TemplateResponse(request,"devices.html",ctx(request,devices=adapter.devices(),csrf=request.session["csrf"],error=str(exc)),status_code=404)
    return RedirectResponse("/devices",303)
@app.get("/devices/{name}/config")
def config(request:Request,name:str):
    try:
        payload=adapter.client_config(name)
    except ValueError: raise HTTPException(404)
    return Response(json.dumps(payload,indent=2),media_type="application/json",headers={"Content-Disposition":f'attachment; filename="vortex-{name.lower()}.json"'})
@app.get("/routing",response_class=HTMLResponse)
def routing(request:Request): return templates.TemplateResponse(request,"routing.html",ctx(request,routes=adapter.routing(),csrf=request.session["csrf"]))
@app.post("/routing/{target}")
def change_route(request:Request,target:str,domain:str=Form(...),remove:bool=Form(False)):
    csrf(request)
    if target not in {"vpn","direct"}: raise HTTPException(404)
    try:
        adapter.route_change(target,domain.strip().lower(),remove)
    except ValueError as exc:
        return templates.TemplateResponse(request,"routing.html",ctx(request,routes=adapter.routing(),csrf=request.session["csrf"],error=str(exc)),status_code=422)
    return RedirectResponse("/routing",303)
@app.get("/ingress",response_class=HTMLResponse)
def ingress(request:Request): return templates.TemplateResponse(request,"ingress.html",ctx(request,status=adapter.status(),csrf=request.session["csrf"]))
@app.get("/diagnostics",response_class=HTMLResponse)
def diagnostics(request:Request): return templates.TemplateResponse(request,"diagnostics.html",ctx(request,logs=adapter.logs(),csrf=request.session["csrf"]))
@app.get("/backups",response_class=HTMLResponse)
def backups(request:Request): return templates.TemplateResponse(request,"backups.html",ctx(request,backups=adapter.backups(),csrf=request.session["csrf"]))
@app.get("/settings",response_class=HTMLResponse)
def settings(request:Request): return templates.TemplateResponse(request,"settings.html",ctx(request,status=adapter.status(),csrf=request.session["csrf"]))

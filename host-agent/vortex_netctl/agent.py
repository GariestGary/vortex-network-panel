from __future__ import annotations
import asyncio, grp, logging, os
from .config import load_config
from .controller import Controller
from .protocol import parse_request,response
from .system import System

async def make_handler(controller):
    async def handle(reader,writer):
        request_id="unknown"
        try:
            line=await reader.readuntil(b"\n")
            request,params=parse_request(line); request_id=request.request_id; method=request.method
            if method=="get_status": result=controller.get_status()
            elif method=="get_devices": result=controller.get_devices(getattr(params,"device_name",None))
            elif method in {"add_device","enable_device","disable_device","delete_device","rotate_device_uuid"}:
                result=controller.mutate_device({"add_device":"add","enable_device":"enable","disable_device":"disable","delete_device":"delete","rotate_device_uuid":"rotate"}[method],params.name)
            elif method=="get_routing": result=controller.get_routing()
            elif method in {"add_force_vpn","remove_force_vpn","add_force_direct","remove_force_direct"}:
                result=controller.mutate_routing("vpn" if method.endswith("vpn") else "direct",params.domain,method.startswith("remove"))
            elif method=="get_ingress": result=controller.get_ingress()
            elif method=="test_direct": result={"ip":controller.test_ip(False)}
            elif method=="test_vpn": result={"ip":controller.test_ip(True)}
            elif method=="test_destination": result=controller.test_destination(params.destination)
            elif method=="get_recent_logs": result=controller.logs()
            elif method=="list_backups": result=controller.backups()
            elif method=="restore_backup": result=controller.restore(params.backup_id)
            else: raise ValueError("Unknown method")
            writer.write(response(request_id,result=result))
        except asyncio.LimitOverrunError: writer.write(response(request_id,error=("REQUEST_TOO_LARGE","Request exceeds size limit")))
        except ValueError as exc: writer.write(response(request_id,error=("INVALID_REQUEST",str(exc))))
        except OSError: writer.write(response(request_id,error=("UNAVAILABLE","Host operation unavailable")))
        except Exception: writer.write(response(request_id,error=("INTERNAL_ERROR","Host agent operation failed")))
        await writer.drain(); writer.close(); await writer.wait_closed()
    return handle
async def main():
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    config=load_config(); os.makedirs(os.path.dirname(config.socket_path),mode=0o750,exist_ok=True)
    if os.path.exists(config.socket_path): os.unlink(config.socket_path)
    server=await asyncio.start_unix_server(await make_handler(Controller(config,System())),path=config.socket_path,limit=8193)
    os.chmod(config.socket_path,0o660)
    async with server: await server.serve_forever()
if __name__=="__main__": asyncio.run(main())
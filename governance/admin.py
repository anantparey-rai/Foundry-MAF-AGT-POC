"""POC administration. Never expose publicly without independent network controls."""
import hmac
import os
from starlette.requests import Request
from starlette.responses import JSONResponse
from governance.persistence.kill_repository import get_kill_state, is_agent_killed, recover_agent

def _authorized(request: Request) -> bool:
    secret = os.getenv("AGT_ADMIN_SECRET", "")
    supplied = request.headers.get("x-agt-admin-secret", "")
    return bool(secret and supplied and hmac.compare_digest(supplied, secret))

def _guard(request: Request):
    if os.getenv("AGT_ADMIN_API_ENABLED", "").lower() != "true":
        return JSONResponse({"error": "Admin API disabled"}, status_code=404)
    if not _authorized(request):
        return JSONResponse({"error": "Forbidden"}, status_code=403)
    return None

async def test_ring_breach_route(request: Request):
    blocked = _guard(request)
    if blocked is not None:
        return blocked
    if os.getenv("AGT_ALLOW_DESTRUCTIVE_TEST", "").lower() != "true":
        return JSONResponse({"error": "Destructive test disabled"}, status_code=403)
    if is_agent_killed():
        return JSONResponse({"error": "Agent already killed"}, status_code=409)
    from agent.hosted_adapter import create_hosted_agent
    governance = create_hosted_agent().governed.kill_switch_middleware
    try:
        governance.enforce_tool("delete_customer", approved_execution=True)
    except Exception:
        state = get_kill_state()
        if state and state.get("killed") is True:
            return JSONResponse({
                "status": "killed", "reason": state.get("reason"),
                "details": state.get("details"),
                "test": "unauthorized_privileged_execution",
            })
        return JSONResponse({"error": "Breach was not durably persisted"}, status_code=500)
    return JSONResponse({"error": "Ring enforcement unexpectedly allowed action"}, status_code=500)

async def recovery_route(request: Request):
    blocked = _guard(request)
    if blocked is not None:
        return blocked
    # A durable recovery request must not silently restart or override a
    # terminated in-memory agent. Stop all hosted replicas first.
    if os.getenv("AGT_RECOVERY_WORKLOAD_STOPPED", "").lower() != "true":
        return JSONResponse({"error": "Stop hosted workload and set recovery gate before recovery"}, status_code=409)
    try:
        body = await request.json()
        reviewer, reason = body.get("reviewer"), body.get("reason")
        if not isinstance(reviewer, str) or not isinstance(reason, str):
            return JSONResponse({"error": "reviewer and reason required"}, status_code=400)
        recover_agent(reviewer=reviewer, reason=reason)
        return JSONResponse({
            "status": "restart_required", "durable_kill_cleared": True,
            "message": "Restart hosted agents and revalidate governance before resuming traffic",
        }, status_code=202)
    except ValueError as exc:
        return JSONResponse({"error": str(exc)}, status_code=409)
    except Exception as exc:
        print("AGT_RECOVERY_ERROR", type(exc).__name__, flush=True)
        return JSONResponse({"error": "Recovery failed"}, status_code=500)

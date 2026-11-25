import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
OPA_DIRECTORY = PROJECT_ROOT / "tools"
OPA_SOURCE = OPA_DIRECTORY / "opa"
OPA_RUNTIME = Path("/tmp/opa")

# Copy OPA to writable runtime storage and restore executable permission.
if not OPA_SOURCE.is_file():
    raise FileNotFoundError(f"Bundled OPA binary missing: {OPA_SOURCE}")

import shutil
shutil.copy2(OPA_SOURCE, OPA_RUNTIME)
OPA_RUNTIME.chmod(0o755)

os.environ["ACS_OPA_PATH"] = str(OPA_RUNTIME)
os.environ["PATH"] = (
    str(OPA_RUNTIME.parent) + os.pathsep
    + str(OPA_DIRECTORY) + os.pathsep
    + os.environ.get("PATH", "")
)

# Keep policy and application paths independent of the launch directory.
os.chdir(PROJECT_ROOT)

import shutil
import subprocess

opa = shutil.which("opa")
print(f"ACS_DIAG_OPA_FOUND={opa}", flush=True)

if opa:
    print(f"ACS_DIAG_OPA_EXECUTABLE={os.access(opa, os.X_OK)}", flush=True)
    probe = subprocess.run(
        [
            opa,
            "eval",
            "--format", "pretty",
            "--data",
            str(PROJECT_ROOT / "governance/policies/acs/policy/policy.rego"),
            "data.agent_control_specification.agent_governance.input_verdict",
        ],
        capture_output=True,
        text=True,
        timeout=15,
    )
    print(f"ACS_DIAG_OPA_RC={probe.returncode}", flush=True)
    print(f"ACS_DIAG_OPA_STDOUT={probe.stdout}", flush=True)
    print(f"ACS_DIAG_OPA_STDERR={probe.stderr}", flush=True)


from agent_framework_foundry_hosting import ResponsesHostServer
from agent.hosted_adapter import create_hosted_agent

from starlette.requests import Request
from starlette.responses import JSONResponse
from governance.admin import test_ring_breach_route, recovery_route


server = ResponsesHostServer(agent=create_hosted_agent, history_source="agent")

async def list_approvals_route(request: Request):
    try:
        agent = create_hosted_agent()
        return JSONResponse({"approvals": agent.list_pending_approvals()})
    except Exception as exc:
        print(f"Approval listing failed: {exc}", flush=True)
        return JSONResponse({"error": "Unable to list approvals"}, status_code=500)


async def resolve_approval_route(request: Request):
    try:
        request_id = request.path_params["request_id"]
        body = await request.json()
        decision = body.get("decision")

        decision_map = {
            "approve": "allow",
            "approved": "allow",
            "allow": "allow",
            "reject": "deny",
            "rejected": "deny",
            "deny": "deny",
        }

        if decision not in decision_map:
            return JSONResponse(
                {"error": "Decision must be approve or reject"},
                status_code=400,
            )

        agent = create_hosted_agent()
        result = await agent.resolve_approval(
            request_id,
            decision_map[decision],
            body["reviewer"],
        )
        return JSONResponse(result)

    except ValueError as exc:
        return JSONResponse({"error": str(exc)}, status_code=409)
    except Exception as exc:
        print(f"Approval resolution failed: {exc}", flush=True)
        return JSONResponse(
            {"error": "Unable to resolve approval"},
            status_code=500,
        )


server.add_route(
    "/approvals/pending",
    list_approvals_route,
    methods=["GET"],
)
server.add_route(
    "/approvals/{request_id}/decision",
    resolve_approval_route,
    methods=["POST"],
)

server.add_route("/admin/test/ring-breach", test_ring_breach_route, methods=["POST"])
server.add_route("/admin/recovery", recovery_route, methods=["POST"])


if __name__ == "__main__":
    server.run(
        host="0.0.0.0",
        port=int(os.environ.get("PORT", "8088")),
    )

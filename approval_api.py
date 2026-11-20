import os
import shutil
from pathlib import Path

from fastapi import FastAPI, HTTPException, Header
from pydantic import BaseModel

ROOT = Path(__file__).resolve().parent
OPA_SOURCE = ROOT / "tools" / "opa"
OPA_RUNTIME = Path("/tmp/opa")

if not OPA_SOURCE.is_file():
    raise RuntimeError("Bundled OPA binary missing")

shutil.copy2(OPA_SOURCE, OPA_RUNTIME)
OPA_RUNTIME.chmod(0o755)
os.environ["ACS_OPA_PATH"] = str(OPA_RUNTIME)
os.environ["PATH"] = str(OPA_RUNTIME.parent) + os.pathsep + os.environ.get("PATH", "")
os.chdir(ROOT)

from governance.persistence.approval_repository import list_pending_approvals
from agent.hosted_adapter import create_hosted_agent

app = FastAPI(title="AGT Approval API", docs_url=None, redoc_url=None)


class DecisionRequest(BaseModel):
    decision: str


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/approvals/pending")
def pending():
    return {
        "approvals": [
            {
                "request_id": item["id"],
                "tool_name": item.get("tool_name"),
                "reason": item.get("reason"),
                "status": item["status"],
            }
            for item in list_pending_approvals()
        ]
    }


@app.post("/approvals/{request_id}/decision")
async def decision(
    request_id: str,
    body: DecisionRequest,
    x_demo_reviewer_secret: str | None = Header(default=None),
):
    import hmac

    expected = os.environ.get("DEMO_REVIEWER_SECRET")
    if not expected:
        raise HTTPException(status_code=503, detail="Demo reviewer access not configured")

    if not x_demo_reviewer_secret or not hmac.compare_digest(
        x_demo_reviewer_secret, expected
    ):
        raise HTTPException(status_code=403, detail="Reviewer access denied")

    decision_map = {"approve": "allow", "reject": "deny"}
    if body.decision not in decision_map:
        raise HTTPException(status_code=400, detail="Invalid decision")

    try:
        agent = create_hosted_agent()
        return await agent.resolve_approval(
            request_id,
            decision_map[body.decision],
            "poc-demo-reviewer",
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except Exception:
        raise HTTPException(status_code=500, detail="Governed approval execution failed")

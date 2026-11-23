"""Isolated, opt-in administrative POC routes. Never mount on the public Foundry host."""
import logging
import os
import hmac
from datetime import datetime, timezone
from uuid import uuid4

from azure.core import MatchConditions
from azure.cosmos import exceptions
from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, Field

from governance.persistence.cosmos import AGENT_ID, get_approvals_container
from governance.persistence.kill_repository import get_kill_status
from governance.persistence.security_events import record_security_event

router = APIRouter(prefix="/admin", tags=["controlled-governance"])
logger = logging.getLogger(__name__)
STATE_ID = "kill-switch-state"


def _authorize(secret: str | None):
    expected = os.getenv("AGT_INCIDENT_ADMIN_SECRET")
    if os.getenv("AGT_ENABLE_INCIDENT_ADMIN") != "true" or not expected:
        raise HTTPException(status_code=404, detail="Administrative controls disabled")
    if not secret or not hmac.compare_digest(secret, expected):
        raise HTTPException(status_code=403, detail="Incident administrator authorization denied")


class BreachTest(BaseModel):
    confirmation: str


@router.post("/test/ring-breach")
def controlled_ring_breach(body: BreachTest, x_agt_incident_admin_secret: str | None = Header(default=None)):
    _authorize(x_agt_incident_admin_secret)
    if os.getenv("AGT_ENABLE_DESTRUCTIVE_TEST") != "true":
        raise HTTPException(status_code=403, detail="Destructive test disabled")
    if body.confirmation != "TERMINATE_POC_AGENT":
        raise HTTPException(status_code=400, detail="Explicit termination confirmation required")
    if get_kill_status()["killed"]:
        raise HTTPException(status_code=409, detail="Agent already killed")
    # This invokes real AGT ring enforcement but does NOT execute the banking tool.
    from governance.kill_switch import AutomaticRingBreachKillSwitch
    governance = AutomaticRingBreachKillSwitch()
    try:
        governance.enforce_tool("delete_customer", approved_execution=True,
                                session_id="controlled-ring-breach-test")
    except Exception as exc:
        state = get_kill_status()
        if state["killed"] and state["reason"] == "RING_BREACH":
            logger.warning("CONTROLLED_RING_BREACH_TEST activated; agent-wide Cosmos latch set")
            return {"result": "RING_BREACH_KILL", "agentId": AGENT_ID,
                    "killSwitch": state, "runtime": "approval-service-process",
                    "note": "Foundry hosted process callback not verified"}
        logger.exception("Controlled breach failed without verified persistent kill")
        raise HTTPException(status_code=500, detail="Breach test failed; inspect server logs") from exc
    raise HTTPException(status_code=500, detail="Expected ring denial did not occur")


class RecoveryRequest(BaseModel):
    incident_etag: str = Field(min_length=1)
    reviewer: str = Field(min_length=3, max_length=128)
    justification: str = Field(min_length=15, max_length=2048)
    confirmation: str


@router.post("/recovery")
def recover(body: RecoveryRequest, x_agt_incident_admin_secret: str | None = Header(default=None)):
    _authorize(x_agt_incident_admin_secret)
    if body.confirmation != "AUTHORIZE_AGENT_RECOVERY":
        raise HTTPException(status_code=400, detail="Explicit recovery confirmation required")
    container = get_approvals_container()
    try:
        state = container.read_item(item=STATE_ID, partition_key=AGENT_ID)
    except exceptions.CosmosResourceNotFoundError:
        raise HTTPException(status_code=409, detail="No kill state exists")
    if not state.get("killed") or state.get("reason") != "RING_BREACH":
        raise HTTPException(status_code=409, detail="No automatic ring-breach kill to recover")
    if state.get("_etag") != body.incident_etag:
        raise HTTPException(status_code=409, detail="Kill state changed; re-review incident")
    incident = {"id": "incident-recovery-" + uuid4().hex, "agentId": AGENT_ID,
                "type": "governance_event", "eventType": "AGENT_RECOVERY_AUTHORIZED",
                "decision": "AUTHORIZE", "reviewer": body.reviewer,
                "reason": body.justification, "previousReason": state.get("reason"),
                "incidentETag": body.incident_etag,
                "timestamp": datetime.now(timezone.utc).isoformat()}
    # Record authorization BEFORE clearing latch; failure keeps the agent blocked.
    container.create_item(body=incident)
    state.update({"killed": False, "reason": "AUTHORIZED_RECOVERY",
                  "reviewer": body.reviewer, "recoveryIncidentId": incident["id"],
                  "timestamp": datetime.now(timezone.utc).isoformat()})
    try:
        container.replace_item(item=STATE_ID, body=state, etag=body.incident_etag,
                               match_condition=MatchConditions.IfNotModified)
    except exceptions.CosmosAccessConditionFailedError:
        raise HTTPException(status_code=409, detail="Kill state changed; recovery not applied")
    return {"result": "PERSISTENT_LATCH_CLEARED", "killSwitch": get_kill_status(),
            "incidentId": incident["id"], "runtimeRestartRequired": True,
            "note": "Existing Foundry runtime instances may retain terminated event; verify fresh runtime and chat"}

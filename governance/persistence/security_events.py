"""Low-volume, best-effort governance security evidence in the existing Approvals container.

Only security exceptions are persisted; ordinary allowed requests are not written.
Telemetry failures never change the existing enforcement outcome.
"""
import logging
from datetime import datetime, timezone
from uuid import uuid4

from governance.persistence.cosmos import AGENT_ID, get_approvals_container

logger = logging.getLogger(__name__)

def record_security_event(event_type, decision, reason=None, **attributes):
    allowed = {"PROMPT_INJECTION_DETECTED", "PROMPT_INJECTION_DETECTOR_ERROR",
               "RING_ENFORCEMENT_DENIED", "RING_BREACH_KILL"}
    if event_type not in allowed:
        raise ValueError("Unsupported security event type")
    doc = {
        "id": "gov-" + uuid4().hex,
        "agentId": AGENT_ID,
        "type": "governance_event",
        "eventType": event_type,
        "decision": str(decision),
        "reason": str(reason or "")[:512],
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    for key in ("tool", "threat_level", "injection_type", "confidence", "session_id"):
        if key in attributes and attributes[key] is not None:
            doc[key] = attributes[key]
    try:
        get_approvals_container().create_item(body=doc)
    except Exception:
        logger.exception("Governance evidence persistence failed: %s", event_type)

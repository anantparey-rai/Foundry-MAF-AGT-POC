from datetime import datetime, timezone
from azure.core import MatchConditions
from azure.cosmos import exceptions
from governance.persistence.cosmos import AGENT_ID, get_approvals_container

STATE_ID = "kill-switch-state"

def get_kill_state():
    try:
        return get_approvals_container().read_item(item=STATE_ID, partition_key=AGENT_ID)
    except exceptions.CosmosResourceNotFoundError:
        return None

def is_agent_killed():
    state = get_kill_state()
    return bool(state and state.get("killed") is True)

def persist_kill(reason, details=None):
    container = get_approvals_container()
    for _ in range(5):
        current = get_kill_state()
        if current is None:
            try:
                return container.create_item(body={
                    "id": STATE_ID, "agentId": AGENT_ID,
                    "type": "kill_switch", "killed": True,
                    "reason": str(reason), "details": str(details or ""),
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                })
            except exceptions.CosmosResourceExistsError:
                continue
        if current.get("killed") is True:
            return current
        current.update({
            "killed": True, "reason": str(reason),
            "details": str(details or ""),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })
        try:
            return container.replace_item(
                item=STATE_ID, body=current, etag=current["_etag"],
                match_condition=MatchConditions.IfNotModified,
            )
        except exceptions.CosmosAccessConditionFailedError:
            continue
    raise RuntimeError("Kill state write conflict")

def recover_agent(*, reviewer, reason):
    """Recovery requires an authenticated admin route and a stopped hosted workload."""
    if not reviewer or not reviewer.strip() or not reason or not reason.strip():
        raise ValueError("Verified reviewer and recovery reason required")
    container = get_approvals_container()
    for _ in range(5):
        current = get_kill_state()
        if current is None or current.get("killed") is not True:
            raise ValueError("Agent is not killed")
        from uuid import uuid4
        audit = {
            "id": "kill-recovery-" + uuid4().hex,
            "agentId": AGENT_ID, "type": "kill_recovery_audit",
            "reviewer": reviewer.strip(), "reason": reason.strip(),
            "previous_reason": current.get("reason"),
            "previous_timestamp": current.get("timestamp"),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        container.create_item(body=audit)
        current.update({
            "killed": False, "reason": "ADMIN_RECOVERY",
            "details": reason.strip(), "reviewer": reviewer.strip(),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })
        try:
            return container.replace_item(
                item=STATE_ID, body=current, etag=current["_etag"],
                match_condition=MatchConditions.IfNotModified,
            )
        except exceptions.CosmosAccessConditionFailedError:
            continue
    raise RuntimeError("Recovery state write conflict")

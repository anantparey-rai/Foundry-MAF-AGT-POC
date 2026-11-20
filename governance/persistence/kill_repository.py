from datetime import datetime, timezone

from azure.cosmos import exceptions

from governance.persistence.cosmos import (
    AGENT_ID,
    get_approvals_container,
)

STATE_ID = "kill-switch-state"


def is_agent_killed():
    container = get_approvals_container()

    try:
        record = container.read_item(
            item=STATE_ID,
            partition_key=AGENT_ID,
        )
        return record.get("killed") is True
    except exceptions.CosmosResourceNotFoundError:
        return False


def persist_kill(reason, details=None):
    """Latch an automatic kill even when a manual-state document already exists."""
    from azure.core import MatchConditions
    container = get_approvals_container()
    for _ in range(3):
        try:
            record = container.read_item(item=STATE_ID, partition_key=AGENT_ID)
        except exceptions.CosmosResourceNotFoundError:
            try:
                return container.create_item(body={
                    "id": STATE_ID, "agentId": AGENT_ID, "type": "kill_switch",
                    "killed": True, "reason": str(reason),
                    "details": str(details or ""),
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                })
            except exceptions.CosmosResourceExistsError:
                continue
        if record.get("killed") is True and record.get("reason") not in ("MANUAL_KILL", "MANUAL_RESET"):
            return record
        record.update({
            "killed": True, "reason": str(reason),
            "details": str(details or ""),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })
        try:
            return container.replace_item(item=STATE_ID, body=record,
                                          etag=record["_etag"],
                                          match_condition=MatchConditions.IfNotModified)
        except exceptions.CosmosAccessConditionFailedError:
            continue
    raise RuntimeError("Automatic kill persistence conflict")


def get_kill_status():
    container = get_approvals_container()
    try:
        record = container.read_item(item=STATE_ID, partition_key=AGENT_ID)
    except exceptions.CosmosResourceNotFoundError:
        return {"killed": False, "reason": None, "timestamp": None}
    return {
        "killed": record.get("killed") is True,
        "reason": record.get("reason"),
        "timestamp": record.get("timestamp"),
    }


def set_manual_kill(killed: bool, reviewer: str):
    """Durable manual kill state; optimistic concurrency prevents lost updates."""
    from azure.core import MatchConditions
    container = get_approvals_container()
    for _ in range(3):
        try:
            record = container.read_item(item=STATE_ID, partition_key=AGENT_ID)
        except exceptions.CosmosResourceNotFoundError:
            if not killed:
                return get_kill_status()
            try:
                container.create_item(body={
                    "id": STATE_ID, "agentId": AGENT_ID, "type": "kill_switch",
                    "killed": True, "reason": "MANUAL_KILL",
                    "reviewer": reviewer, "timestamp": datetime.now(timezone.utc).isoformat(),
                })
                return get_kill_status()
            except exceptions.CosmosResourceExistsError:
                continue
        if record.get("killed") is True and record.get("reason") not in ("MANUAL_KILL", "MANUAL_RESET") and not killed:
            raise ValueError("Automatic kill cannot be cleared by manual reset")
        if killed and record.get("killed") is True and record.get("reason") not in ("MANUAL_KILL", "MANUAL_RESET"):
            return get_kill_status()
        record.update({
            "killed": bool(killed),
            "reason": "MANUAL_KILL" if killed else "MANUAL_RESET",
            "reviewer": reviewer,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })
        try:
            container.replace_item(item=STATE_ID, body=record, etag=record["_etag"],
                                   match_condition=MatchConditions.IfNotModified)
            return get_kill_status()
        except exceptions.CosmosAccessConditionFailedError:
            continue
    raise RuntimeError("Kill switch update conflict; retry required")

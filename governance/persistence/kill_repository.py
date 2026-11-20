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
    container = get_approvals_container()

    record = {
        "id": STATE_ID,
        "agentId": AGENT_ID,
        "type": "kill_switch",
        "killed": True,
        "reason": str(reason),
        "details": str(details or ""),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

    try:
        return container.create_item(body=record)
    except exceptions.CosmosResourceExistsError:
        existing = container.read_item(
            item=STATE_ID,
            partition_key=AGENT_ID,
        )
        if existing.get("killed") is not True:
            raise RuntimeError("Invalid durable kill state")
        return existing

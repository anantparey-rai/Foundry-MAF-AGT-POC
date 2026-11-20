import json
from datetime import datetime, timezone
from azure.core import MatchConditions
from azure.cosmos import exceptions

from governance.persistence.cosmos import AGENT_ID, get_approvals_container


def create_approval(record):
    document = {
        **{k: v for k, v in record.items() if k != "policy_input"},
        "id": record["request_id"],
        "agentId": AGENT_ID,
        "status": "pending",
    }
    document["policy_input_json"] = json.dumps(
        record["policy_input"],
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    try:
        result = get_approvals_container().create_item(body=document)
        print("COSMOS_APPROVAL_CREATE: PASS", flush=True)
        return result
    except Exception as exc:
        print(
            f"COSMOS_APPROVAL_CREATE: FAILED "
            f"{type(exc).__name__}: {str(exc)[:300]}",
            flush=True,
        )
        raise


def get_approval(request_id):
    try:
        return get_approvals_container().read_item(
            item=request_id,
            partition_key=AGENT_ID,
        )
    except exceptions.CosmosResourceNotFoundError:
        return None


def list_pending_approvals():
    return list(get_approvals_container().query_items(
        query="SELECT * FROM c WHERE c.agentId = @agent AND c.status = @status",
        parameters=[
            {"name": "@agent", "value": AGENT_ID},
            {"name": "@status", "value": "pending"},
        ],
        partition_key=AGENT_ID,
    ))


def transition_approval(
    request_id, expected_status, new_status, reviewer=None
):
    container = get_approvals_container()
    document = get_approval(request_id)

    if document is None or document["status"] != expected_status:
        return False

    if expected_status == "pending" and new_status in ("allow", "deny"):
        if not isinstance(reviewer, str) or not reviewer.strip():
            raise ValueError("Verified reviewer identity is required")
        document["reviewer"] = reviewer.strip()
        document["decision_timestamp"] = datetime.now(
            timezone.utc
        ).isoformat()

    etag = document["_etag"]
    document["status"] = new_status

    try:
        container.replace_item(
            item=request_id,
            body=document,
            etag=etag,
            match_condition=MatchConditions.IfNotModified,
        )
        return True
    except exceptions.CosmosAccessConditionFailedError:
        return False


def claim_execution(request_id):
    return transition_approval(request_id, "allow", "executing")


def finalize_execution(request_id, succeeded):
    return transition_approval(request_id, "executing", "executed" if succeeded else "failed")

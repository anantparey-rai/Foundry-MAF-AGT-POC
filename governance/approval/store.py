import json
from dataclasses import dataclass
from threading import RLock
from typing import Any
from uuid import uuid4
from governance.persistence import approval_repository as repo


@dataclass
class PendingApproval:
    request_id: str
    intervention_point: str
    tool_name: str
    arguments: dict[str, Any]
    action_identity: str | None
    policy_input: dict[str, Any]
    status: str = "pending"
    reason: str | None = None


_PENDING: dict[str, PendingApproval] = {}
_LOCK = RLock()


def create_pending(intervention_point, result) -> PendingApproval:
    policy_input = result.policy_input or {}
    snapshot = policy_input.get("snapshot", {})
    tool_call = snapshot.get("tool_call", {})

    item = PendingApproval(
        request_id=uuid4().hex,
        intervention_point=intervention_point.value,
        tool_name=tool_call.get("name", ""),
        arguments=dict(tool_call.get("args", {})),
        action_identity=result.action_identity,
        policy_input=policy_input,
        reason=result.verdict.reason,
    )

    repo.create_approval(vars(item))
    return item


def get_pending_request(request_id: str):
    record = repo.get_approval(request_id)
    if not record:
        return None
    if "policy_input_json" not in record:
        raise ValueError("Approval missing canonical policy input")
    record["policy_input"] = json.loads(
        record["policy_input_json"],
        parse_float=float,
    )
    record["arguments"] = dict(
        record["policy_input"]["snapshot"]["tool_call"]["args"]
    )
    return PendingApproval(**{
        k: record[k] for k in PendingApproval.__dataclass_fields__
        if k in record
    })


def list_pending():
    approvals = []
    for record in repo.list_pending_approvals():
        data = dict(record)
        if "policy_input_json" in data:
            data["policy_input"] = json.loads(data["policy_input_json"])
        if "policy_input" not in data:
            raise ValueError("Missing policy_input for approval " + str(data.get("request_id")))
        approvals.append(PendingApproval(**{
            k: data[k] for k in PendingApproval.__dataclass_fields__
            if k in data
        }))
    return approvals


def set_decision(
    request_id: str, decision: str, reviewer: str
) -> bool:
    if decision not in ("allow", "deny"):
        raise ValueError("Decision must be allow or deny")

    if not reviewer or not reviewer.strip():
        raise ValueError("Verified reviewer identity is required")

    return repo.transition_approval(
        request_id, "pending", decision, reviewer=reviewer
    )


def consume_pending(request_id: str):
    raise NotImplementedError(
        "Durable approval finalization requires execution-state handling"
    )

from agent_control_specification import ApprovalOutcome, ApprovalResolution, action_identity


def create_approval_resolver(resume_request_id: str | None = None):
    def resolver(intervention_point, result):
        if resume_request_id is None:
            item = create_pending(intervention_point, result)
            return ApprovalResolution(
                ApprovalOutcome.SUSPEND,
                handle=item.request_id,
                action_identity=item.action_identity,
            )

        item = get_pending_request(resume_request_id)

        if (
            item is None
            or not item.action_identity
            or not result.action_identity
            or item.action_identity != result.action_identity
            or item.action_identity != action_identity(item.policy_input)
        ):
            return ApprovalResolution(ApprovalOutcome.DENY)

        if item.status == "allow":
            return ApprovalResolution(
                ApprovalOutcome.ALLOW,
                handle=item.request_id,
                action_identity=item.action_identity,
            )

        if item.status == "deny":
            return ApprovalResolution(ApprovalOutcome.DENY)

        return ApprovalResolution(
            ApprovalOutcome.SUSPEND,
            handle=item.request_id,
            action_identity=item.action_identity,
        )

    return resolver

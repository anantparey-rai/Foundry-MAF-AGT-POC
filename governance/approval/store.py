from dataclasses import dataclass
from threading import RLock
from typing import Any
from uuid import uuid4


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

    with _LOCK:
        _PENDING[item.request_id] = item

    return item


def get_pending_request(request_id: str):
    with _LOCK:
        return _PENDING.get(request_id)


def list_pending():
    with _LOCK:
        return [item for item in _PENDING.values() if item.status == "pending"]


def set_decision(request_id: str, decision: str) -> bool:
    if decision not in ("allow", "deny"):
        raise ValueError("Decision must be allow or deny")

    with _LOCK:
        item = _PENDING.get(request_id)
        if item is None or item.status != "pending":
            return False
        item.status = decision
        return True


def consume_pending(request_id: str):
    with _LOCK:
        return _PENDING.pop(request_id, None)

from agent_control_specification import ApprovalOutcome, ApprovalResolution


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

        if item is None or item.action_identity != result.action_identity:
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

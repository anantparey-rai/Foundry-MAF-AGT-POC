#!/usr/bin/env python3
"""Exercise real ACS protect_tool with an isolated in-memory approval resolver.

No Foundry credentials, Cosmos DB, or banking tool invocation.
"""
import asyncio
import os
from pathlib import Path
from agent_control_specification import (
    AgentControl, AgentControlSuspended, ApprovalOutcome, ApprovalResolution,
)

ROOT = Path(__file__).resolve().parents[1]
os.environ["ACS_OPA_PATH"] = str(ROOT / "tools" / "opa")
os.environ["PATH"] = str(ROOT / "tools") + os.pathsep + os.environ.get("PATH", "")
os.chdir(ROOT)
acs = AgentControl.from_path("governance/policies/acs/manifest.yaml")

async def main():
    executed = []
    approvals = {}

    def make_resolver(request_id=None):
        def resolve(intervention_point, result):
            identity = result.action_identity
            assert identity, "ACS action identity missing"
            if request_id is None:
                approvals["req-1"] = {"identity": identity, "state": "pending"}
                return ApprovalResolution(ApprovalOutcome.SUSPEND, handle="req-1",
                                          action_identity=identity)
            record = approvals.get(request_id)
            if not record or record["identity"] != identity:
                return ApprovalResolution(ApprovalOutcome.DENY)
            if record["state"] == "allow":
                return ApprovalResolution(ApprovalOutcome.ALLOW, handle=request_id,
                                          action_identity=identity)
            if record["state"] == "deny":
                return ApprovalResolution(ApprovalOutcome.DENY)
            return ApprovalResolution(ApprovalOutcome.SUSPEND, handle=request_id,
                                      action_identity=identity)
        return resolve

    def execute(args):
        record = approvals["req-1"]
        if record["state"] != "allow":
            raise PermissionError("Approval not authorized")
        record["state"] = "executed"  # Atomic execution claim stand-in
        executed.append(dict(args))
        return "MOCK_EXECUTED"

    args = {"amount": 100, "currency": "USD"}
    guarded = acs.protect_tool("transfer_money", execute, approval_resolver=make_resolver())
    try:
        await guarded(args)
    except AgentControlSuspended:
        pass
    else:
        raise AssertionError("High-impact tool did not suspend")
    assert not executed and approvals["req-1"]["state"] == "pending"
    print("PASS: ACS suspends high-impact tool without execution")

    approvals["req-1"]["state"] = "deny"
    denied = acs.protect_tool("transfer_money", execute, approval_resolver=make_resolver("req-1"))
    try:
        await denied(args)
    except Exception:
        pass
    else:
        raise AssertionError("Denied approval was allowed")
    assert not executed, "Rejected approval executed tool"
    print("PASS: ACS rejected approval does not execute tool")

    approvals["req-1"]["state"] = "allow"
    allowed = acs.protect_tool("transfer_money", execute, approval_resolver=make_resolver("req-1"))
    result = await allowed(args)
    assert result.value == "MOCK_EXECUTED" and executed == [args]
    print("PASS: ACS authorized approval executes mock exactly once")

    replay = acs.protect_tool("transfer_money", execute, approval_resolver=make_resolver("req-1"))
    try:
        await replay(args)
    except Exception:
        pass
    else:
        raise AssertionError("Executed approval was reusable")
    assert executed == [args], "Approval replay caused duplicate execution"
    print("PASS: ACS approval replay does not execute again")

    # Identity binding: changing tool arguments must not reuse the approval.
    approvals["req-1"]["state"] = "allow"
    tampered = acs.protect_tool("transfer_money", execute, approval_resolver=make_resolver("req-1"))
    try:
        await tampered({"amount": 999, "currency": "USD"})
    except Exception:
        pass
    else:
        raise AssertionError("Modified action was authorized with stale approval")
    assert executed == [args]
    print("PASS: ACS action identity rejects modified tool arguments")

asyncio.run(main())

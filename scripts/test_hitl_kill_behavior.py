#!/usr/bin/env python3
"""Offline behavioral checks of actual approval/kill persistence functions.

Uses in-memory Cosmos stand-ins; no Azure credentials, network or banking tools.
"""
import ast
import copy
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]

class NotFound(Exception): pass
class Conflict(Exception): pass
class Exists(Exception): pass

exceptions = SimpleNamespace(
    CosmosResourceNotFoundError=NotFound,
    CosmosAccessConditionFailedError=Conflict,
    CosmosResourceExistsError=Exists,
)
MatchConditions = SimpleNamespace(IfNotModified="IfNotModified")
AGENT_ID = "offline-test-agent"

class Container:
    def __init__(self):
        self.docs = {}
        self.force_conflict = False

    def read_item(self, item, partition_key):
        assert partition_key == AGENT_ID
        if item not in self.docs: raise NotFound(item)
        return copy.deepcopy(self.docs[item])

    def create_item(self, body):
        if body["id"] in self.docs: raise Exists(body["id"])
        doc = copy.deepcopy(body)
        doc["_etag"] = "1"
        self.docs[body["id"]] = doc
        return copy.deepcopy(doc)

    def replace_item(self, item, body, etag, match_condition):
        assert match_condition == MatchConditions.IfNotModified
        if self.force_conflict or self.docs[item]["_etag"] != etag:
            raise Conflict(item)
        doc = copy.deepcopy(body)
        doc["_etag"] = str(int(etag) + 1)
        self.docs[item] = doc
        return copy.deepcopy(doc)

container = Container()
scope = {
    "get_approvals_container": lambda: container,
    "AGENT_ID": AGENT_ID,
    "STATE_ID": "kill-switch-state",
    "exceptions": exceptions,
    "MatchConditions": MatchConditions,
    "datetime": datetime,
    "timezone": timezone,
}

def load_functions(path, names):
    tree = ast.parse((ROOT / path).read_text(encoding="utf-8-sig"))
    funcs = [n for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name in names]
    assert {f.name for f in funcs} == set(names), "Expected repository functions not found"
    # Remove imports that require Azure packages; test the original function bodies.
    for fn in funcs:
        fn.body = [n for n in fn.body if not (isinstance(n, ast.ImportFrom) and n.module == "azure.core")]
    module = ast.fix_missing_locations(ast.Module(body=funcs, type_ignores=[]))
    exec(compile(module, path, "exec"), scope)

load_functions("governance/persistence/approval_repository.py",
               ("get_approval", "transition_approval", "claim_execution", "finalize_execution"))
load_functions("governance/persistence/kill_repository.py",
               ("is_agent_killed", "get_kill_status", "persist_kill", "set_manual_kill"))

def check(condition, message):
    assert condition, message
    print("PASS:", message)

# HITL state transitions: pending -> allow -> executing -> executed, exactly once.
container.create_item({"id": "approved", "agentId": AGENT_ID, "status": "pending"})
check(scope["transition_approval"]("approved", "pending", "allow", reviewer="reviewer-1"),
      "reviewer authorizes pending approval")
check(not scope["transition_approval"]("approved", "pending", "deny", reviewer="reviewer-2"),
      "decision cannot be overwritten")
check(scope["claim_execution"]("approved"), "first execution claim succeeds")
check(not scope["claim_execution"]("approved"), "replayed execution claim rejected")
check(scope["finalize_execution"]("approved", True), "execution finalized")
check(not scope["claim_execution"]("approved"), "executed approval cannot replay")

container.create_item({"id": "denied", "agentId": AGENT_ID, "status": "pending"})
check(scope["transition_approval"]("denied", "pending", "deny", reviewer="reviewer-1"),
      "rejection recorded")
check(not scope["claim_execution"]("denied"), "denied approval cannot execute")

container.create_item({"id": "no-reviewer", "agentId": AGENT_ID, "status": "pending"})
try:
    scope["transition_approval"]("no-reviewer", "pending", "allow", reviewer=" ")
except ValueError:
    print("PASS: empty reviewer identity rejected")
else:
    raise AssertionError("Blank reviewer authorized approval")

container.create_item({"id": "conflict", "agentId": AGENT_ID, "status": "pending"})
container.force_conflict = True
check(not scope["transition_approval"]("conflict", "pending", "allow", reviewer="reviewer-1"),
      "optimistic concurrency conflict fails closed")
container.force_conflict = False

# Kill switch: manual latch/reset and automatic latch cannot be manually reset.
check(not scope["is_agent_killed"](), "agent initially active")
scope["set_manual_kill"](True, "reviewer-1")
check(scope["is_agent_killed"](), "manual kill blocks agent")
scope["set_manual_kill"](False, "reviewer-1")
check(not scope["is_agent_killed"](), "authorized manual reset clears manual kill")
scope["persist_kill"]("RING_BREACH", "offline test")
check(scope["is_agent_killed"](), "automatic ring breach latches kill")
try:
    scope["set_manual_kill"](False, "reviewer-1")
except ValueError:
    print("PASS: automatic kill cannot be manually reset")
else:
    raise AssertionError("Automatic kill was cleared")
check(scope["is_agent_killed"](), "automatic kill remains latched")
print("PASS: offline HITL state and kill-switch behavioral checks completed")

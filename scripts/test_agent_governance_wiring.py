#!/usr/bin/env python3
"""Offline agent wiring and ASI02 validator checks; never invokes Azure or tools."""
import ast
import inspect
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = (ROOT / "agent/agent.py").read_text(encoding="utf-8-sig")
HOSTED = (ROOT / "agent/hosted_adapter.py").read_text(encoding="utf-8-sig")
TREE = ast.parse(SOURCE)
HOSTED_TREE = ast.parse(HOSTED)
CLASS = next(n for n in TREE.body if isinstance(n, ast.ClassDef) and n.name == "GovernedMAFAgent")
METHOD = next(n for n in CLASS.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == "validate_tool_call")

# Compile just the validator method, without importing the cloud agent or its dependencies.
module = ast.Module(body=[ast.FunctionDef(name=METHOD.name, args=METHOD.args,
    body=METHOD.body, decorator_list=[], returns=None, type_comment=None)], type_ignores=[])
ast.fix_missing_locations(module)

def transfer_money(amount: float, currency: str):
    return "NOT_EXECUTED"

def get_balance(account_id: str):
    return "NOT_EXECUTED"

registry = {"transfer_money": transfer_money, "get_balance": get_balance}
scope = {"TOOL_FUNCTIONS": registry, "inspect": inspect, "math": math}
exec(compile(module, "agent/agent.py:validate_tool_call", "exec"), scope)
validate = scope["validate_tool_call"]

def rejected(label, name, fn, args):
    try:
        validate(name, fn, args)
    except (PermissionError, ValueError, TypeError):
        print("PASS rejected:", label)
        return
    raise AssertionError(f"Invalid tool call accepted: {label}")

validate("transfer_money", transfer_money, {"amount": 900, "currency": "USD"})
print("PASS accepted: valid registered tool call")
rejected("unknown tool", "unknown", transfer_money, {"amount": 900, "currency": "USD"})
rejected("function substitution", "transfer_money", get_balance, {"amount": 900, "currency": "USD"})
rejected("negative amount", "transfer_money", transfer_money, {"amount": -1, "currency": "USD"})
rejected("zero amount", "transfer_money", transfer_money, {"amount": 0, "currency": "USD"})
rejected("boolean amount", "transfer_money", transfer_money, {"amount": True, "currency": "USD"})
rejected("infinite amount", "transfer_money", transfer_money, {"amount": float("inf"), "currency": "USD"})
rejected("missing currency", "transfer_money", transfer_money, {"amount": 100})
rejected("blank currency", "transfer_money", transfer_money, {"amount": 100, "currency": " "})
rejected("unexpected argument", "transfer_money", transfer_money, {"amount": 100, "currency": "USD", "admin": True})

def method(name):
    return next(n for n in CLASS.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == name)

def calls_named(node, name):
    return any(isinstance(n, ast.Call) and (
        (isinstance(n.func, ast.Attribute) and n.func.attr == name) or
        (isinstance(n.func, ast.Name) and n.func.id == name)
    ) for n in ast.walk(node))

assert calls_named(method("_create_governed_tool"), "validate_tool_call"), "Tool wrapper missing validation"
assert calls_named(method("resolve_approval"), "validate_tool_call"), "Approval replay missing validation"
assert calls_named(method("_create_governed_tool"), "protect_tool"), "Tool wrapper missing ACS"
assert calls_named(method("resolve_approval"), "protect_tool"), "Approval replay missing ACS"
assert calls_named(method("screen_input"), "detect"), "AGT input detector missing"
assert calls_named(method("screen_input"), "exception"), "Detector fail-closed logging missing"
assert calls_named(method("resolve_approval"), "is_agent_killed"), "Approval kill check missing"

hosted_class = next(n for n in HOSTED_TREE.body if isinstance(n, ast.ClassDef) and n.name == "GovernedHostedAgent")
for name in ("_run_non_stream", "_run_stream"):
    fn = next(n for n in hosted_class.body if isinstance(n, ast.AsyncFunctionDef) and n.name == name)
    assert calls_named(fn, "screen_input"), f"{name}: missing AGT input screening"
    assert calls_named(fn, "run"), f"{name}: missing ACS execution"
print("PASS static governance wiring checks (not live integration tests)")

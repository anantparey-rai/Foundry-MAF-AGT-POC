#!/usr/bin/env python3
"""Execute actual GovernedMAFAgent input/run methods with isolated dependencies.

Tests ordering and fail-closed behavior without Foundry, Cosmos or real tools.
"""
import ast
import asyncio
import json
import logging
from pathlib import Path
from types import SimpleNamespace

root = Path(__file__).resolve().parents[1]
tree = ast.parse((root / "agent/agent.py").read_text(encoding="utf-8-sig"))
cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "GovernedMAFAgent")
names = {"screen_input", "run"}
methods = [n for n in cls.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name in names]
assert {n.name for n in methods} == names
isolated = ast.fix_missing_locations(ast.Module(body=[
    ast.ClassDef(name="GovernedMAFAgent", bases=[], keywords=[], body=methods, decorator_list=[])
], type_ignores=[]))
scope = {"json": json, "logger": logging.getLogger("offline-governance"),
         "is_agent_killed": lambda: False}
exec(compile(isolated, "agent/agent.py:isolated", "exec"), scope)
Agent = scope["GovernedMAFAgent"]

class Detector:
    def __init__(self, mode): self.mode = mode; self.calls = []
    def detect(self, message, source):
        self.calls.append((message, source))
        if self.mode == "error": raise RuntimeError("detector offline")
        return SimpleNamespace(is_injection=self.mode == "block",
                               threat_level=SimpleNamespace(value="high"),
                               injection_type=SimpleNamespace(value="injection"),
                               confidence=0.99)

class FakeACS:
    def __init__(self, events, deny=False): self.events = events; self.deny = deny
    async def run(self, payload, execute):
        self.events.append("acs_input")
        if self.deny: raise PermissionError("ACS policy denied")
        result = await execute(payload)
        self.events.append("acs_output")
        return SimpleNamespace(value=result)

class FakeModel:
    def __init__(self, events): self.events = events
    async def run(self, message):
        self.events.append("model")
        return "MOCK_RESPONSE"

def build(mode="allow", kill=False, acs_deny=False):
    events = []
    agent = Agent()
    agent.prompt_injection_detector = Detector(mode)
    agent.kill_switch_middleware = SimpleNamespace(
        terminated=SimpleNamespace(is_set=lambda: kill))
    agent.acs = FakeACS(events, deny=acs_deny)
    agent.agent = FakeModel(events)
    return agent, events

async def main():
    agent, events = build()
    assert await agent.run("balance") == "MOCK_RESPONSE"
    assert events == ["acs_input", "model", "acs_output"], events
    assert agent.prompt_injection_detector.calls == [("balance", "foundry_hosted_input")]
    print("PASS: detector -> ACS input -> model -> ACS output")

    for mode in ("block", "error"):
        agent, events = build(mode)
        try: await agent.run("adversarial input")
        except PermissionError: pass
        else: raise AssertionError(f"Detector {mode} did not block")
        assert events == [], f"Detector {mode} allowed ACS/model"
        print(f"PASS: detector {mode} fails closed before model")

    agent, events = build(kill=True)
    try: await agent.run("balance")
    except RuntimeError: pass
    else: raise AssertionError("Kill switch did not block")
    assert events == []
    print("PASS: terminated agent cannot reach ACS/model")

    agent, events = build(acs_deny=True)
    try: await agent.run("bypass governance")
    except PermissionError: pass
    else: raise AssertionError("ACS deny did not block")
    assert events == ["acs_input"], events
    print("PASS: ACS denies before model execution")

asyncio.run(main())

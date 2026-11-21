"""Offline governance state tests. No Azure resources or live credentials required."""
from copy import deepcopy

import pytest
from azure.cosmos import exceptions

from governance.persistence import approval_repository as approval
from governance.persistence import kill_repository as kill


class FakeContainer:
    def __init__(self):
        self.records = {}
        self.version = 0

    def read_item(self, item, partition_key):
        if item not in self.records:
            raise exceptions.CosmosResourceNotFoundError(status_code=404, message="missing")
        return deepcopy(self.records[item])

    def create_item(self, body):
        if body["id"] in self.records:
            raise exceptions.CosmosResourceExistsError(status_code=409, message="exists")
        self.version += 1
        doc = deepcopy(body)
        doc["_etag"] = str(self.version)
        self.records[doc["id"]] = doc
        return deepcopy(doc)

    def replace_item(self, item, body, etag=None, match_condition=None):
        current = self.records[item]
        if etag != current["_etag"]:
            raise exceptions.CosmosAccessConditionFailedError(status_code=412, message="etag mismatch")
        self.version += 1
        doc = deepcopy(body)
        doc["_etag"] = str(self.version)
        self.records[item] = doc
        return deepcopy(doc)


@pytest.fixture
def cosmos(monkeypatch):
    container = FakeContainer()
    monkeypatch.setattr(approval, "get_approvals_container", lambda: container)
    monkeypatch.setattr(kill, "get_approvals_container", lambda: container)
    return container


def test_approval_requires_reviewer_and_executes_once(cosmos):
    cosmos.create_item({"id": "req-1", "agentId": approval.AGENT_ID, "status": "pending"})
    with pytest.raises(ValueError, match="reviewer"):
        approval.transition_approval("req-1", "pending", "allow")
    assert approval.transition_approval("req-1", "pending", "allow", reviewer="authorized-demo-admin")
    assert not approval.transition_approval("req-1", "pending", "deny", reviewer="other")
    assert approval.claim_execution("req-1")
    assert not approval.claim_execution("req-1")
    assert approval.finalize_execution("req-1", succeeded=True)
    assert not approval.finalize_execution("req-1", succeeded=True)
    assert cosmos.read_item("req-1", approval.AGENT_ID)["status"] == "executed"


def test_reject_never_claimable(cosmos):
    cosmos.create_item({"id": "req-2", "agentId": approval.AGENT_ID, "status": "pending"})
    assert approval.transition_approval("req-2", "pending", "deny", reviewer="authorized-demo-admin")
    assert not approval.claim_execution("req-2")


def test_pre_execution_failure_is_not_reusable(cosmos):
    cosmos.create_item({"id": "req-3", "agentId": approval.AGENT_ID, "status": "pending"})
    assert approval.transition_approval("req-3", "pending", "allow", reviewer="authorized-demo-admin")
    assert approval.transition_approval("req-3", "allow", "failed")
    assert not approval.claim_execution("req-3")


def test_manual_kill_and_reset(cosmos):
    assert kill.get_kill_status()["killed"] is False
    assert kill.set_manual_kill(True, "authorized-demo-admin")["killed"] is True
    assert kill.is_agent_killed()
    assert kill.set_manual_kill(False, "authorized-demo-admin")["killed"] is False
    assert not kill.is_agent_killed()


def test_automatic_kill_is_latched_and_cannot_be_manually_reset(cosmos):
    kill.set_manual_kill(True, "authorized-demo-admin")
    kill.persist_kill("RING_BREACH", "test breach")
    status = kill.get_kill_status()
    assert status["killed"] is True
    assert status["reason"] == "RING_BREACH"
    with pytest.raises(ValueError, match="cannot be cleared"):
        kill.set_manual_kill(False, "authorized-demo-admin")
    assert kill.get_kill_status()["killed"] is True


def test_automatic_kill_without_existing_record(cosmos):
    kill.persist_kill("RING_BREACH")
    assert kill.is_agent_killed()
    assert kill.get_kill_status()["reason"] == "RING_BREACH"


def test_optimistic_concurrency_rejects_stale_approval(cosmos):
    cosmos.create_item({"id": "req-4", "agentId": approval.AGENT_ID, "status": "pending"})
    stale = cosmos.read_item("req-4", approval.AGENT_ID)
    assert approval.transition_approval("req-4", "pending", "deny", reviewer="authorized-demo-admin")
    with pytest.raises(exceptions.CosmosAccessConditionFailedError):
        cosmos.replace_item("req-4", stale, etag=stale["_etag"])

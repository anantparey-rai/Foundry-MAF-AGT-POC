"""Offline governance regression tests. No Azure resources required."""
import importlib
import sys
import types
from unittest.mock import MagicMock
import pytest


@pytest.fixture
def repository(monkeypatch):
    azure = types.ModuleType("azure")
    core = types.ModuleType("azure.core")
    core.MatchConditions = types.SimpleNamespace(IfNotModified="IfNotModified")
    cosmos = types.ModuleType("azure.cosmos")
    class NotFound(Exception): pass
    class Exists(Exception): pass
    class Conflict(Exception): pass
    cosmos.exceptions = types.SimpleNamespace(
        CosmosResourceNotFoundError=NotFound,
        CosmosResourceExistsError=Exists,
        CosmosAccessConditionFailedError=Conflict,
    )
    monkeypatch.setitem(sys.modules, "azure", azure)
    monkeypatch.setitem(sys.modules, "azure.core", core)
    monkeypatch.setitem(sys.modules, "azure.cosmos", cosmos)
    fake_cosmos = types.ModuleType("governance.persistence.cosmos")
    fake_cosmos.AGENT_ID = "did:test:agent"
    container = MagicMock()
    fake_cosmos.get_approvals_container = lambda: container
    monkeypatch.setitem(sys.modules, "governance.persistence.cosmos", fake_cosmos)
    sys.modules.pop("governance.persistence.kill_repository", None)
    module = importlib.import_module("governance.persistence.kill_repository")
    yield module, container, cosmos
    sys.modules.pop("governance.persistence.kill_repository", None)


def test_missing_record_is_not_killed(repository):
    repo, container, errors = repository
    container.read_item.side_effect = errors.exceptions.CosmosResourceNotFoundError()
    assert repo.is_agent_killed() is False


def test_existing_false_state_can_be_killed(repository):
    repo, container, _ = repository
    container.read_item.return_value = {
        "id": repo.STATE_ID, "agentId": "did:test:agent",
        "killed": False, "_etag": "etag-1",
    }
    container.replace_item.return_value = {"killed": True}
    assert repo.persist_kill("RING_BREACH", "test")["killed"] is True
    assert container.replace_item.call_args.kwargs["etag"] == "etag-1"
    assert container.replace_item.call_args.kwargs["body"]["killed"] is True


def test_existing_kill_is_not_cleared(repository):
    repo, container, _ = repository
    container.read_item.return_value = {
        "id": repo.STATE_ID, "killed": True, "reason": "RING_BREACH",
    }
    assert repo.persist_kill("OTHER")["reason"] == "RING_BREACH"
    container.replace_item.assert_not_called()


def test_cosmos_failure_fails_closed(repository):
    repo, container, _ = repository
    container.read_item.side_effect = RuntimeError("Cosmos unavailable")
    with pytest.raises(RuntimeError, match="Cosmos unavailable"):
        repo.is_agent_killed()


def test_compare_and_swap_conflict_fails(repository):
    repo, container, errors = repository
    container.read_item.return_value = {
        "id": repo.STATE_ID, "killed": False, "_etag": "etag-1",
    }
    container.replace_item.side_effect = errors.exceptions.CosmosAccessConditionFailedError()
    with pytest.raises(RuntimeError, match="conflict"):
        repo.persist_kill("RING_BREACH")
    assert container.replace_item.call_count == 5

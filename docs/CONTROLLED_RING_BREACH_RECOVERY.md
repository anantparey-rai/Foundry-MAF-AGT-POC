# Controlled Ring Breach and Recovery — POC

Feature branch: `feature/ring-breach-admin-recovery`. This feature is **not deployed** merely by committing it.

## Scope
Routes are mounted only on the internal FastAPI approval service (`approval_api.py`), not the public Foundry `main.py` or React dashboard.

- `POST /admin/test/ring-breach`: calls actual `AutomaticRingBreachKillSwitch.enforce_tool("delete_customer", approved_execution=True, session_id="controlled-ring-breach-test")` without elevation. **Does not invoke the banking tool**. Intended to latch the shared Cosmos kill state and record a ring-breach event. The AGT callback runs in the approval-service process, not the Foundry-hosted process.
- `POST /admin/recovery`: requires explicit incident ETag, reviewer, justification and confirmation; creates an authorization audit record before conditionally clearing the Cosmos kill state. Does **not** clear already-set in-memory termination events in existing Foundry instances.

## Security gates
The approval service must be privately accessible. Do **not** expose either route through the public dashboard or APIM. Set:
- `AGT_ENABLE_INCIDENT_ADMIN=true`
- `AGT_INCIDENT_ADMIN_SECRET` to a distinct strong secret, managed in Key Vault or container secret configuration
- `AGT_ENABLE_DESTRUCTIVE_TEST=true` **only during an isolated controlled test**

The existing `DEMO_REVIEWER_SECRET` must **not** be reused. Restrict the approval service's network and admin identity. These POC controls are not a replacement for enterprise Entra ID/RBAC, approval separation, or immutable audit storage.

## Test request
Only after verifying backup, recovery access, and service isolation:

```http
POST /admin/test/ring-breach
x-agt-incident-admin-secret: <secret>
Content-Type: application/json

{"confirmation":"TERMINATE_POC_AGENT"}
```

Expected: `result=RING_BREACH_KILL`, Cosmos `kill-switch-state.killed=true`, `reason=RING_BREACH`. Confirm Foundry and React calls are blocked; do not claim the Foundry process was physically terminated.

## Recovery request
Read the **current** Cosmos kill document's `_etag` *after the test* and review the incident first:

```http
POST /admin/recovery
x-agt-incident-admin-secret: <secret>
Content-Type: application/json

{"incident_etag":"<current-etag>","reviewer":"<authorized-reviewer>","justification":"<documented incident review and remediation>","confirmation":"AUTHORIZE_AGENT_RECOVERY"}
```

Expected: `result=PERSISTENT_LATCH_CLEARED`, `killed=false`, `reason=AUTHORIZED_RECOVERY`. This is **not yet proof of runtime recovery**: initialize/restart any affected hosted instances, verify healthy governed chat and new sessions, and verify that previously pending approvals have not executed automatically.

## Rollout / limitations
1. Review the feature branch and execute tests in an isolated environment.
2. Deploy the **approval service** revision only. Foundry v15 source is unchanged.
3. Keep the destructive test flag disabled except for the test window.
4. Confirm shared Cosmos DB is the intended POC environment; the persistent kill blocks the same agent identity across sessions.
5. Validate that the recovery audit event is visible. Audit write before reset is not transactional with the reset: a concurrent conflict may leave an authorization record while the agent remains killed.
6. Recovery does not reset an already-tripped breach detector or the in-memory `threading.Event`; a fresh runtime instance may be needed.
7. Disable incident admin flags after validation. Never use this endpoint on a production agent without stronger identity, audit and change-control measures.

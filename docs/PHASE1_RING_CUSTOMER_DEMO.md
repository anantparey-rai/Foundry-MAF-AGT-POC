# Phase 1: Ring enforcement customer demo (evidence-first)

## Boundaries in this POC
- Default agent execution: `RING_3_SANDBOX` (`governance/kill_switch.py`).
- Action classification is dynamic via AGT `ActionClassifier`; **do not claim a particular tool is Ring 1 or Ring 2 without recording the classifier result**.
- The approval replay requests a 30-second `RING_1_PRIVILEGED` elevation after ACS HITL approval; `RingEnforcer` must still permit the action.
- Ring 2 is a conceptual intermediate trust tier; this POC has no verified Ring 2 customer workflow.
- Normal chat cannot set an execution ring, grant approval, or invoke the ring enforcer directly. Prompt injection tests are **not** reliable ring-breach tests.

## Customer demonstration sequence
1. **Baseline**: verify hosted agent readiness with `Hello` and a permitted read-only banking request. Show user-visible response and, separately, telemetry availability. A successful answer alone is not a ring-enforcement proof.
2. **Privileged action**: request a small fictitious transfer using test accounts. Expect ACS suspension and a durable pending approval; no transfer should execute before reviewer authorization.
3. **HITL**: authorized reviewer approves in the reviewer UI. Show pending -> allow -> executing -> executed Cosmos states, and successful tool result only if genuinely observed. If replay fails, report failure instead.
4. **Unauthorized ring attempt**: in a dedicated test environment, exercise the AGT `enforce_tool` boundary with a high-impact tool **without** the approved-elevation context. Capture `RING_ENFORCEMENT_DENIED` or `RING_BREACH_KILL` only when actually emitted; a user chat prompt alone does not guarantee either.
5. **Automatic kill**: use an isolated demo agent and intentionally exercise the detector's documented breach threshold with a test harness. This writes a persistent kill-state and can block all subsequent requests. Never do this against the shared live demo agent without an approved recovery/reset plan.
6. **Evidence**: refresh Governance Command Center and filter to `RING_ENFORCEMENT_DENIED` or `RING_BREACH_KILL`. Distinguish actual Cosmos records from conceptual ring explanations. Show timestamps, tool and decision. Verify kill state independently.

## Recovery and constraints
- Do not create a public UI endpoint that allows an arbitrary visitor to set a ring, bypass ACS/HITL, or force a kill.
- Ring breach is a **runtime authorization boundary test**, not an LLM jailbreak prompt.
- The current governance overview samples only the latest 10 approval/security documents; older events may not appear.
- Current source persists kill-state and security events, but runtime integration and end-to-end customer UI remain **unverified**.
- The existing kill repository forbids manual reset of an automatic kill; isolate destructive tests or define an authorized recovery procedure before demonstrating.

## Hosted deployment prerequisite: OPA
`tools/opa` is excluded from Git and **must be bundled** before packaging. Use `bash scripts/deploy_hosted_agent.sh --environment foundry-agt-poc` from a freshly cloned repository with the existing azd environment configured. The script runs `scripts/prepare_opa.sh` and validates the binary before deploying. Do not use bare `azd deploy` from a clean clone.

Never equate a successful `azd deploy` with readiness: validate the hosted session and basic `Hello` request before governance tests.

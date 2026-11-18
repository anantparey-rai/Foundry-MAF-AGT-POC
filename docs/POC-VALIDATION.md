# Azure Foundry + MAF + AGT POC
## Security Validation and Evidence

**Date:** 19 November 2026

## 1. Environment

- Azure AI Foundry
- Microsoft Agent Framework (MAF)
- Microsoft Agent Governance Toolkit (AGT)
- Agent Control Specification (ACS)
- Open Policy Agent (OPA)
- Python 3.14.7

## 2. ASI01 — Goal Hijacking

**Implementation:** ACS input intervention point with Rego-based prompt-injection detection.

- User input is evaluated before MAF invokes the Foundry model.
- Rego rules detect configured prompt-injection patterns.
- Denied input does not reach MAF execution.

**Validation:**
- Clean input: ALLOW.
- Adversarial input: DENY.
- MAF invocation count for denied input: 0.

**Limitation:** Pattern-based detection. This does not establish complete prompt-injection immunity.

## 3. ASI02 — Excessive Agency

**Implementation:** ACS pre-tool-call governance with human-in-the-loop approval.

- High-impact actions are escalated before execution.
- Approval requests are created by the host-side approval resolver.
- Approved actions are revalidated against action identity.
- Denied actions are blocked.

**Validation:**
- High-impact loan application: ESCALATE.
- Tool execution before approval: prevented.
- Approved action: executed after approval.
- Loan application result: pending review.

**Limitations:**
- Approval store is currently in-memory.
- Approved tool execution is host-side re-execution.
- Original MAF conversation is not yet resumed with the approved tool result.

## 4. Automatic Kill Switch — Ring Breach

**Implementation:** AGT components integrated through MAF FunctionMiddleware.

Components:
- ActionClassifier
- RingElevationManager
- RingEnforcer
- RingBreachDetector
- KillSwitch
- KillReason.RING_BREACH
- MAF MiddlewareFailure

Agent base ring: RING_3_SANDBOX.

Verified action classifications:
- get_balance: RING_3_SANDBOX
- delete_customer: RING_1_PRIVILEGED

### Enforcement sequence

1. MAF FunctionMiddleware intercepts tool invocation.
2. AGT ActionClassifier determines the action's required ring.
3. RingElevationManager resolves the effective agent ring.
4. RingEnforcer blocks insufficient privilege.
5. RingBreachDetector monitors repeated anomalous calls.
6. HIGH/CRITICAL breach activates AGT KillSwitch.
7. MAF MiddlewareFailure aborts the current tool-call batch.
8. Subsequent requests are rejected by the termination flag.

### Actual Azure Foundry + MAF test evidence

| Test | Result |
|---|---|
| First delete_customer attempt | DENIED |
| First tool execution | Prevented |
| Repeated delete_customer attempt | Automatic kill activated |
| Kill reason | RING_BREACH |
| Post-kill balance request | Rejected |
| Final termination flag | True |

Observed anomaly score in the actual MAF test: 102.04.

### Kill-switch limitation

The registered callback currently sets a termination flag. It does not forcibly terminate the operating-system process or independently stop unrelated processes.

The detector uses a configurable call-rate baseline and ring-distance amplification. The observed anomaly score is specific to the test traffic and configuration.

## 5. Overall validation status

| Security capability | Status |
|---|---|
| ASI01 Goal Hijacking | Implemented and tested |
| ASI02 Excessive Agency | Implemented and tested |
| Automatic Ring Breach Detection | Implemented and tested |
| AGT Ring Enforcement | Implemented and tested |
| Automatic Kill Switch | Implemented and tested |
| Post-kill request rejection | Implemented and tested |
| Production-grade process termination | Not implemented |
| Persistent approval storage | Not implemented |
| Cloud-hosted deployment validation | Pending |

## 6. Next steps

1. Validate the complete POC in the target Azure-hosted environment.
2. Implement durable approval storage and conversation continuation.
3. Design process-level or workload-level termination for production.
4. Add audit persistence and operational monitoring.
5. Perform regression testing after deployment.

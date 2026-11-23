import threading
from governance.persistence.kill_repository import is_agent_killed, persist_kill
from governance.persistence.security_events import record_security_event

from agent_framework import (
    FunctionMiddleware,
    FunctionInvocationContext,
    MiddlewareFailure,
)
from hypervisor.models import ActionDescriptor, ExecutionRing
from hypervisor.rings.classifier import ActionClassifier
from hypervisor.rings.enforcer import RingEnforcer
from hypervisor.rings.elevation import RingElevationManager
from hypervisor.rings.breach_detector import RingBreachDetector, BreachSeverity
from hypervisor.security.kill_switch import KillSwitch, KillReason


class AutomaticRingBreachKillSwitch(FunctionMiddleware):
    def __init__(self):
        self.agent_did = "did:agt:poc:credit-union-agent"
        self.session_id = "maf-session-001"
        self.base_ring = ExecutionRing.RING_3_SANDBOX

        self.classifier = ActionClassifier()
        self.elevation_manager = RingElevationManager()
        self.enforcer = RingEnforcer()
        self.eff_score = 0.40
        self.detector = RingBreachDetector(
            window_seconds=60,
            baseline_rate=1.0,
        )

        self.kill_switch = KillSwitch()
        self.terminated = threading.Event()
        self.kill_switch.register_agent(
            self.agent_did,
            self.terminated.set,
        )

        self.read_only_tools = {
            "get_balance",
            "get_customer_details",
            "calculate_transfer",
        }

    def enforce_tool(self, tool_name: str, approved_execution: bool = False, session_id: str = None):
        session_id = session_id or self.session_id
        if self.terminated.is_set() or is_agent_killed():
            raise MiddlewareFailure("AGT kill switch: agent terminated.")

        if self.detector.is_breaker_tripped(
            self.agent_did, session_id
        ):
            details = "AGT ring-breach breaker already tripped"
            persist_kill("RING_BREACH", details)
            record_security_event("RING_BREACH_KILL", "TERMINATE", reason=details, tool=tool_name, session_id=session_id)
            self.kill_switch.kill(
                self.agent_did,
                session_id,
                KillReason.RING_BREACH,
                details=details,
            )
            raise MiddlewareFailure(
                f"AGT automatic kill activated: {details}"
            )

        action = ActionDescriptor(
            action_id=tool_name,
            name=tool_name,
            execute_api=tool_name,
            is_read_only=tool_name in self.read_only_tools,
        )

        target_ring = self.classifier.classify(action).ring
        agent_ring = self.elevation_manager.get_effective_ring(
            self.agent_did,
            session_id,
            self.base_ring,
        )

        # High-impact tools enter ACS only to create a HITL request.
        # Actual execution is separately governed in resolve_approval().
        if not approved_execution and tool_name in {
            "transfer_money", "update_customer", "send_email",
            "delete_customer", "apply_for_loan",
        }:
            return

        enforcement = self.enforcer.check(
            agent_ring=agent_ring,
            action=action,
            eff_score=self.eff_score,
        )

        if not enforcement.allowed:
            if approved_execution:
                details = f"Unauthorized ring execution: {tool_name}; {enforcement.reason}"
                persist_kill("RING_BREACH", details)
                record_security_event("RING_BREACH_KILL", "TERMINATE", reason=details, tool=tool_name, session_id=session_id)
                self.kill_switch.kill(
                    self.agent_did, session_id,
                    KillReason.RING_BREACH, details=details
                )
                raise MiddlewareFailure(f"AGT automatic kill activated: {details}")
            record_security_event("RING_ENFORCEMENT_DENIED", "DENY", reason=enforcement.reason, tool=tool_name, session_id=session_id)
            raise MiddlewareFailure(
                f"AGT RingEnforcer denied {tool_name}: {enforcement.reason}"
            )


        # Do not interpret legitimate same-ring bursts as ring breaches.
        # RingEnforcer has already validated this action.
        if target_ring == agent_ring:
            return

        breach = self.detector.record_call(
            self.agent_did,
            session_id,
            agent_ring,
            target_ring,
        )

        if self.detector.is_breaker_tripped(
            self.agent_did,
            session_id,
        ):
            details = breach.details if breach else "AGT ring-breach breaker tripped."
            try:
                persist_kill("RING_BREACH", details)
                record_security_event("RING_BREACH_KILL", "TERMINATE", reason=details, tool=tool_name, session_id=session_id)
                self.kill_switch.kill(
                    self.agent_did,
                    session_id,
                    KillReason.RING_BREACH,
                    details=details,
                )
            except Exception as exc:
                raise MiddlewareFailure("AGT kill-switch execution failed.") from exc

            raise MiddlewareFailure(f"AGT automatic kill activated: {details}")


    async def process(self, context: FunctionInvocationContext, call_next):
        self.enforce_tool(context.function.name)
        await call_next()

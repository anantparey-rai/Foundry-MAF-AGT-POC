import threading

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
            baseline_rate=0.01,
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

    async def process(self, context: FunctionInvocationContext, call_next):
        if self.terminated.is_set():
            raise MiddlewareFailure("AGT kill switch: agent terminated.")

        tool_name = context.function.name
        action = ActionDescriptor(
            action_id=tool_name,
            name=tool_name,
            execute_api=tool_name,
            is_read_only=tool_name in self.read_only_tools,
        )

        target_ring = self.classifier.classify(action).ring
        agent_ring = self.elevation_manager.get_effective_ring(
            self.agent_did,
            self.session_id,
            self.base_ring,
        )

        breach = self.detector.record_call(
            self.agent_did,
            self.session_id,
            agent_ring,
            target_ring,
        )

        if self.detector.is_breaker_tripped(
            self.agent_did,
            self.session_id,
        ):
            details = breach.details if breach else "AGT ring-breach breaker tripped."
            try:
                self.kill_switch.kill(
                    self.agent_did,
                    self.session_id,
                    KillReason.RING_BREACH,
                    details=details,
                )
            except Exception as exc:
                raise MiddlewareFailure("AGT kill-switch execution failed.") from exc

            raise MiddlewareFailure(f"AGT automatic kill activated: {details}")

        enforcement = self.enforcer.check(
            agent_ring=agent_ring,
            action=action,
            eff_score=self.eff_score,
        )

        if not enforcement.allowed:
            raise MiddlewareFailure(
                f"AGT RingEnforcer denied {tool_name}: {enforcement.reason}"
            )

        await call_next()

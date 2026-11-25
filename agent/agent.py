import os
from functools import wraps

from dotenv import load_dotenv
from azure.identity import DefaultAzureCredential
from agent_framework import Agent
from agent_framework.foundry import FoundryChatClient
from governance.kill_switch import AutomaticRingBreachKillSwitch
from governance.persistence.kill_repository import is_agent_killed

from agent_control_specification import (
    AgentControl,
    AgentControlBlocked,
    AgentControlSuspended,
)

from agent.tools import TOOL_FUNCTIONS
from governance.approval.store import (
    create_approval_resolver,
    get_pending_request,
    set_decision,
    consume_pending,
)


load_dotenv()


class GovernedMAFAgent:

    def __init__(self):
        endpoint = os.getenv("AZURE_AI_PROJECT_ENDPOINT") or os.getenv("FOUNDRY_PROJECT_ENDPOINT") or "https://foundrypoc2.services.ai.azure.com/api/projects/POC-proj"
        model = os.getenv("AZURE_AI_MODEL_DEPLOYMENT_NAME", "gpt-41-mini")

        if not endpoint:
            raise ValueError(
                "AZURE_AI_PROJECT_ENDPOINT is missing from environment"
            )

        self.acs = AgentControl.from_path(
            "governance/policies/acs/manifest.yaml"
        )

        self.client = FoundryChatClient(
            project_endpoint=endpoint,
            model=model,
            credential=DefaultAzureCredential(),
        )

        self.tools = [
            self._create_governed_tool(name, function)
            for name, function in TOOL_FUNCTIONS.items()
        ]

        self.kill_switch_middleware = AutomaticRingBreachKillSwitch()

        self.agent = Agent(
            client=self.client,
            name="credit_union_agent",
            instructions=(
                "You are a Credit Union banking assistant. "
                "Use the registered tools when appropriate. "
                "Never claim that a financial action was completed "
                "unless its tool execution actually succeeded. "
                "If a tool call is interrupted for approval, do not "
                "claim success or attempt to bypass governance. "
                "When a user explicitly requests an operation and provides "
                "all required tool parameters, invoke the corresponding "
                "registered tool rather than merely describing an action. "
                "Read-only tools do not require human approval under the "
                "current policy. High-impact tools are governed by ACS. "
                "Only report an approval as submitted when the tool returns "
                "ACTION_PENDING_HUMAN_APPROVAL. Never execute an action "
                "outside its registered tool."
            ),
            tools=self.tools,
            middleware=[self.kill_switch_middleware],
        )

    def _create_governed_tool(self, name, function):
        protected = self.acs.protect_tool(
            name,
            lambda args: function(**args),
            approval_resolver=create_approval_resolver(),
        )

        @wraps(function)
        async def governed_tool(**kwargs):
            try:
                result = await protected(kwargs)
                return result.value
            except AgentControlSuspended as exc:
                return (
                    "ACTION_PENDING_HUMAN_APPROVAL: The requested action "
                    "has been suspended by ACS. No tool action was executed. "
                    "An authorized reviewer must approve or reject it. "
                    f"Details: {exc}"
                )

        hitl_tools = {
            "transfer_money", "update_customer", "send_email",
            "delete_customer", "apply_for_loan",
        }
        governed_tool.__doc__ = (
            f"Execute {name} using its required parameters. "
            + (
                "This is a high-impact action. Invoke this tool to submit "
                "the action to ACS for mandatory human approval. "
                "Never claim approval was submitted without invoking the tool."
                if name in hitl_tools else
                "This is a read-only or calculation operation. "
                "Human approval is not required by the current ACS policy."
            )
        )
        return governed_tool

    async def run(self, message):
        if self.kill_switch_middleware.terminated.is_set() or is_agent_killed():
            raise RuntimeError("AGT kill switch: agent terminated")
        result = await self.acs.run(
            {"body": message},
            lambda effective_input: self.agent.run(effective_input["body"]),
        )
        return result.value

    async def resolve_approval(self, request_id, decision, reviewer):
        if self.kill_switch_middleware.terminated.is_set() or is_agent_killed():
            raise RuntimeError("AGT kill switch: agent terminated")
        if decision not in ("allow", "deny"):
            raise ValueError("Decision must be allow or deny")

        item = get_pending_request(request_id)

        if item is None:
            raise ValueError("Pending approval not found")

        if not set_decision(request_id, decision, reviewer):
            raise ValueError("Approval request is no longer pending")

        tool_name = item.tool_name

        if decision == "deny":
            return {
                "status": "denied",
                "tool": tool_name,
            }

        function = TOOL_FUNCTIONS[tool_name]

        tool_call = item.policy_input["snapshot"]["tool_call"]
        tool_call_id = tool_call.get("id")

        def execute_approved_tool(args):
            from governance.persistence.approval_repository import (
                claim_execution,
                finalize_execution,
            )

            from hypervisor.models import ExecutionRing

            governance = self.kill_switch_middleware
            elevation = None

            if not claim_execution(request_id):
                raise RuntimeError(
                    "Approval already claimed or no longer authorized"
                )

            try:
                if governance.terminated.is_set() or is_agent_killed():
                    raise RuntimeError("AGT kill switch: agent terminated")

                elevation = governance.elevation_manager.request_elevation(
                    agent_did=governance.agent_did,
                    session_id=f'approval-{request_id}',
                    current_ring=ExecutionRing.RING_3_SANDBOX,
                    target_ring=ExecutionRing.RING_1_PRIVILEGED,
                    ttl_seconds=30,
                    attestation=item.action_identity,
                    trust_score=0.85,
                    reason=f"ACS HITL approved: {request_id}",
                )

                governance.enforce_tool(tool_name, approved_execution=True, session_id=f'approval-{request_id}')
                result = function(**args)
            except BaseException:
                finalize_execution(request_id, succeeded=False)
                raise
            finally:
                if elevation is not None:
                    governance.elevation_manager.revoke_elevation(
                        elevation.elevation_id
                    )

            if not finalize_execution(request_id, succeeded=True):
                raise RuntimeError(
                    "Tool executed but approval finalization failed; "
                    "manual reconciliation required"
                )

            return result

        protected = self.acs.protect_tool(
            tool_name,
            execute_approved_tool,
            approval_resolver=create_approval_resolver(request_id),
        )

        try:
            result = await protected(
                item.arguments,
                tool_call_id=tool_call_id,
            )
            return {
                "status": "executed",
                "tool": tool_name,
                "result": result.value,
            }

        except AgentControlBlocked:
            from governance.persistence.approval_repository import get_approval

            record = get_approval(request_id)
            if record and record.get("status") == "executed":
                raise RuntimeError(
                    "Tool executed, but ACS post-tool enforcement blocked "
                    "the result. Manual reconciliation required."
                )

            raise


def create_agent():
    return GovernedMAFAgent()

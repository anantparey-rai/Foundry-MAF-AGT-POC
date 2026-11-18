import os
from functools import wraps

from dotenv import load_dotenv
from azure.identity import DefaultAzureCredential
from agent_framework import Agent
from agent_framework.foundry import FoundryChatClient
from governance.kill_switch import AutomaticRingBreachKillSwitch

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
        endpoint = os.getenv("AZURE_AI_PROJECT_ENDPOINT")
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
                "claim success or attempt to bypass governance."
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
            result = await protected(kwargs)
            return result.value

        return governed_tool

    async def run(self, message):
        result = await self.acs.run(
            {"body": message},
            lambda effective_input: self.agent.run(effective_input["body"]),
        )
        return result.value

    async def resolve_approval(self, request_id, decision):
        if decision not in ("allow", "deny"):
            raise ValueError("Decision must be allow or deny")

        item = get_pending_request(request_id)

        if item is None:
            raise ValueError("Pending approval not found")

        if not set_decision(request_id, decision):
            raise ValueError("Approval request is no longer pending")

        tool_name = item.tool_name
        function = TOOL_FUNCTIONS[tool_name]

        tool_call = item.policy_input["snapshot"]["tool_call"]
        tool_call_id = tool_call.get("id")

        protected = self.acs.protect_tool(
            tool_name,
            lambda args: function(**args),
            approval_resolver=create_approval_resolver(request_id),
        )

        try:
            result = await protected(
                item.arguments,
                tool_call_id=tool_call_id,
            )
            consume_pending(request_id)

            return {
                "status": "executed",
                "tool": tool_name,
                "result": result.value,
            }

        except AgentControlBlocked:
            consume_pending(request_id)

            if decision == "deny":
                return {
                    "status": "denied",
                    "tool": tool_name,
                }

            raise


def create_agent():
    return GovernedMAFAgent()

from collections.abc import Mapping, Sequence
from typing import Any

from agent_framework import ResponseStream

from agent.agent import create_agent
from governance.approval.store import list_pending


def _extract_text(value: Any) -> str:
    if value is None:
        return ""

    if isinstance(value, str):
        return value

    if isinstance(value, Mapping):
        content = value.get("content", value.get("text", ""))
        return _extract_text(content)

    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        return "\n".join(filter(None, (_extract_text(item) for item in value)))

    text = getattr(value, "text", None)
    if isinstance(text, str):
        return text

    contents = getattr(value, "contents", None)
    if contents is not None:
        return _extract_text(contents)

    content = getattr(value, "content", None)
    if content is not None:
        return _extract_text(content)

    return str(value)


def _messages_to_text(messages: Any) -> str:
    if isinstance(messages, str):
        return messages

    if messages is None:
        return ""

    if isinstance(messages, Sequence) and not isinstance(messages, (str, bytes)):
        parts = []
        for message in messages:
            role = getattr(message, "role", None)
            text = _extract_text(message)
            if text:
                parts.append(f"{role or 'message'}: {text}")
        return "\n".join(parts)

    return _extract_text(messages)


class GovernedHostedAgent:
    """MAF hosted-agent adapter with ACS input/output enforcement."""

    def __init__(self):
        self.governed = create_agent()
        self.agent = self.governed.agent
        self.acs = self.governed.acs

    def list_pending_approvals(self):
        return [
            {
                "request_id": item.request_id,
                "intervention_point": item.intervention_point,
                "tool_name": item.tool_name,
                "arguments": item.arguments,
                "reason": item.reason,
                "status": item.status,
            }
            for item in list_pending()
        ]

    async def resolve_approval(self, request_id, decision, reviewer):
        return await self.governed.resolve_approval(request_id, decision, reviewer)


    @property
    def id(self):
        return "credit_union_agent"

    @property
    def name(self):
        return "credit_union_agent"

    @property
    def description(self):
        return "Credit Union assistant protected by AGT governance."

    def create_session(self, *, session_id=None):
        return self.agent.create_session(session_id=session_id)

    def get_session(self, service_session_id, *, session_id=None):
        return self.agent.get_session(
            service_session_id,
            session_id=session_id,
        )

    def run(
        self,
        messages=None,
        *,
        stream=False,
        session=None,
        function_invocation_kwargs=None,
        client_kwargs=None,
        options=None,
        **kwargs,
    ):
        body = _messages_to_text(messages)

        if stream:
            return ResponseStream.from_awaitable(
                self._run_stream(
                    body,
                    session,
                    function_invocation_kwargs,
                    client_kwargs,
                    options,
                )
            )

        return self._run_non_stream(
            body,
            session,
            function_invocation_kwargs,
            client_kwargs,
            options,
        )

    async def _run_non_stream(
        self, body, session, function_invocation_kwargs, client_kwargs, options
    ):
        async def execute(effective_input):
            return await self.agent.run(
                effective_input["body"],
                session=session,
                options=options,
                function_invocation_kwargs=function_invocation_kwargs,
                client_kwargs=client_kwargs,
            )

        result = await self.acs.run({"body": body}, execute)
        return result.value

    async def _run_stream(
        self, body, session, function_invocation_kwargs, client_kwargs, options
    ):
        updates = []

        async def execute(effective_input):
            inner_stream = self.agent.run(
                effective_input["body"],
                stream=True,
                session=session,
                options=options,
                function_invocation_kwargs=function_invocation_kwargs,
                client_kwargs=client_kwargs,
            )

            async for update in inner_stream:
                updates.append(update)

            return await inner_stream.get_final_response()

        # Buffer the entire stream. ACS output enforcement completes
        # before any response update is released to the hosted server.
        result = await self.acs.run({"body": body}, execute)
        final_response = result.value

        async def replay():
            for update in updates:
                yield update

        return ResponseStream(
            replay(),
            finalizer=lambda _: final_response,
        )


def create_hosted_agent():
    return GovernedHostedAgent()

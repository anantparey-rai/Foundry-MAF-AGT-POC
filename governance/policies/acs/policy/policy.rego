package agent_control_specification.agent_governance

import rego.v1

default governance_kill_switch := false

governance_kill_switch := true if {
    input.annotations.governance_kill_switch == true
}

default verdict := {"decision": "allow"}
default input_verdict := {"decision": "allow"}
default pre_tool_call_verdict := {"decision": "allow"}
default post_tool_call_verdict := {"decision": "allow"}
default output_verdict := {"decision": "allow"}

verdict := input_verdict if {
    input.intervention_point == "input"
}

verdict := pre_tool_call_verdict if {
    input.intervention_point == "pre_tool_call"
}

verdict := post_tool_call_verdict if {
    input.intervention_point == "post_tool_call"
}

verdict := output_verdict if {
    input.intervention_point == "output"
}


# OUTPUT GOVERNANCE

output_verdict := {"decision": "deny", "reason": "sensitive_output"} if {
    input.intervention_point == "output"
    contains(lower(sprintf("%v", [input.policy_target.value])), "pan")
}

output_verdict := {"decision": "deny", "reason": "sensitive_output"} if {
    input.intervention_point == "output"
    contains(lower(sprintf("%v", [input.policy_target.value])), "aadhaar")
}

output_verdict := {"decision": "deny", "reason": "sensitive_output"} if {
    input.intervention_point == "output"
    contains(lower(sprintf("%v", [input.policy_target.value])), "account number")
}


# INPUT GOVERNANCE

input_verdict := {"decision": "deny", "reason": "governance_bypass_attempt"} if {
    input.intervention_point == "input"
    contains(lower(sprintf("%v", [input.policy_target.value])), "bypass governance")
}


# LLM01 detection is enforced by AGT PromptInjectionDetector in the hosted adapter.
# ASI01: ACS retains an independent governance-bypass deny rule above.
# ASI02: unknown tools are denied before execution, including at approval replay.

pre_tool_call_verdict := {"decision": "deny", "reason": "tool_not_registered"} if {
    input.intervention_point == "pre_tool_call"
    not input.tool.name in {
        "get_balance", "get_customer_details", "calculate_transfer",
        "transfer_money", "update_customer", "send_email",
        "delete_customer", "apply_for_loan"
    }
}

# PRE-TOOL GOVERNANCE
# High-impact / mutation / external / destructive actions
# require human approval.

pre_tool_call_verdict := {
    "decision": "escalate",
    "reason": "high_impact_action"
} if {
    input.intervention_point == "pre_tool_call"
    input.tool.name in {
        "transfer_money",
        "update_customer",
        "send_email",
        "delete_customer",
        "apply_for_loan"
    }
}


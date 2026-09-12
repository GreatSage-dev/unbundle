from typing import Optional, Dict, Any, List
from strands import Agent
from src.agent.tools import (
    audit_eob_claims,
    evaluate_cedar_policy,
    generate_erisa_appeal,
    dispatch_statutory_dispute
)

UNBUNDLE_SYSTEM_PROMPT = """You are UNBUNDLE, an industrial-grade autonomous EOB compliance sentinel.
You operate silently in the background inside the AWS Bedrock AgentCore Runtime.

Your objectives:
1. Ingest Explanation of Benefits (EOB) documents and claim line summaries.
2. Delegate all procedure code audits strictly to deterministic tools (CMS NCCI PTP and CARC/RARC crosswalks).
3. NEVER calculate financial deltas in prose; always rely on audited mathematical outputs from tools.
4. Enforce AWS Cedar least-privilege policies: you are strictly forbidden from filing legal disputes
   unless an explicit cryptographic human approval token is present in the context.
5. Emulate the Aviation Ground Proximity Warning System (GPWS) pattern: if a claim is clean,
   silently archive it without pinging the user. If an overbill is detected, emit a single, quantified
   steering decision for the human.
"""

def create_unbundle_agent(model_id: Optional[str] = None) -> Agent:
    """
    Factory creating a configured Strands Agent equipped with UNBUNDLE's
    deterministic audit gates and Cedar policy tools.
    """
    tools = [
        audit_eob_claims,
        evaluate_cedar_policy,
        generate_erisa_appeal,
        dispatch_statutory_dispute
    ]

    agent_kwargs: Dict[str, Any] = {
        "system_prompt": UNBUNDLE_SYSTEM_PROMPT,
        "tools": tools
    }

    if model_id:
        agent_kwargs["model"] = model_id

    return Agent(**agent_kwargs)

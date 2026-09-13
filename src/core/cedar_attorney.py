from pathlib import Path
from typing import Optional, Dict, Any, Tuple
import cedarpy

POLICY_PATH = Path(__file__).resolve().parent.parent.parent / "policies" / "unbundle.cedar"

class CedarAttorney:
    """
    AWS Cedar Least-Privilege Policy Enforcement Gate.
    Enforces that the Strands Agent is mathematically forbidden from performing
    consequential actions (such as dispatching appeals or settling debt)
    unless a valid, cryptographically verified human approval token is in context.
    """
    def __init__(self, policy_path: Optional[Path] = None):
        self.policy_path = policy_path or POLICY_PATH
        if not self.policy_path.exists():
            raise FileNotFoundError(f"Cedar policy not found at {self.policy_path}")
        self.policy_text = self.policy_path.read_text(encoding="utf-8")

    def is_action_authorized(
        self,
        action: str,
        principal: str = 'Agent::"UNBUNDLE_Sentinel"',
        resource: str = 'Resource::"MemberDispute"',
        context: Optional[Dict[str, Any]] = None
    ) -> bool:
        """
        Evaluates the requested action against the Cedar policy set using cedarpy Rust engine.
        Returns True if ALLOW, False if DENY.
        """
        eval_context = context or {}
        
        request = {
            "principal": principal,
            "action": f'Action::"{action}"',
            "resource": resource,
            "context": eval_context
        }

        result = cedarpy.is_authorized(
            request=request,
            policies=self.policy_text,
            entities=[]
        )

        return result.decision == cedarpy.Decision.Allow

    def enforce_dispatch_gate(self, human_token: Optional[str]) -> Tuple[bool, str]:
        """
        Specialized gate for legal dispatch.
        Verifies presence and validity of human signature token.
        """
        from src.core.auth import verify_cryptographic_token
        is_token_valid = bool(human_token and verify_cryptographic_token(human_token))
        
        context = {
            "human_approval_token_valid": is_token_valid
        }

        allowed = self.is_action_authorized(action="dispatch_dispute", context=context)
        
        if allowed:
            return True, "CEDAR_DECISION: ALLOW - Verified cryptographic human token present."
        else:
            return False, "CEDAR_DECISION: EXPLICIT_DENY - Autonomous dispatch forbidden under policies.cedar (HTTP 403 Forbidden)."

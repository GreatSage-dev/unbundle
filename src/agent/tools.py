from typing import Dict, Any, List, Optional
from strands import tool
from src.core.models import EOBDocument, AuditResult, AuditViolation, AppealPacket
from src.core.ncci_engine import NCCIValidator
from src.core.carc_engine import CARCValidator
from src.core.cedar_attorney import CedarAttorney
from src.packet.erisa_generator import ERISAAppealGenerator

ncci_engine = NCCIValidator()
carc_engine = CARCValidator()
cedar_attorney = CedarAttorney()

@tool
def audit_eob_claims(eob_dict: Dict[str, Any]) -> Dict[str, Any]:
    """
    Deterministically audits an Explanation of Benefits (EOB) document.
    Executes CMS NCCI PTP unbundling checks, Modifier 59 abuse validation,
    and CARC predatory liability shift checks.
    """
    eob = EOBDocument(**eob_dict)
    
    ncci_violations = ncci_engine.audit_lines(eob.lines)
    carc_violations = carc_engine.audit_liability_shifts(eob.lines, in_network=eob.in_network)
    
    all_violations: List[AuditViolation] = ncci_violations + carc_violations
    
    # Continuous Net Settlement: deduplicate excised amount by line_number
    # A single line item's charge cannot be double-excised across multiple rule triggers
    line_excised_map: Dict[int, float] = {}
    for v in all_violations:
        line_excised_map[v.line_number] = max(line_excised_map.get(v.line_number, 0.0), v.excised_amount)
    
    total_excised = sum(line_excised_map.values())
    revised_liability = max(0.0, eob.total_patient_responsibility - total_excised)
    has_violations = len(all_violations) > 0
    status = "DISCREPANCY_DETECTED" if has_violations else "SILENT_ARCHIVE"
    
    annunciator_msg = None
    if has_violations:
        annunciator_msg = (
            f"OVERBILL DETECTED on Claim #{eob.claim_id} ({eob.provider_name}): "
            f"{len(all_violations)} violation finding(s) across {len(line_excised_map)} line(s). "
            f"Original patient liability: ${eob.total_patient_responsibility:,.2f}. "
            f"Excised unlawful charges: ${total_excised:,.2f}. "
            f"Corrected lawful liability: ${revised_liability:,.2f}."
        )
    else:
        annunciator_msg = f"Claim #{eob.claim_id} verified clean against CMS NCCI tables. 0 user interruptions required."

    audit_result = AuditResult(
        claim_id=eob.claim_id,
        has_violations=has_violations,
        total_original_patient_liability=eob.total_patient_responsibility,
        total_excised_amount=total_excised,
        revised_patient_liability=revised_liability,
        violations=all_violations,
        status=status,
        annunciator_message=annunciator_msg
    )
    
    return audit_result.model_dump()

@tool
def evaluate_cedar_policy(action_name: str, human_token: Optional[str] = None) -> Dict[str, Any]:
    """
    Evaluates AWS Cedar policy to determine whether an agent action is authorized.
    Enforces least-privilege boundaries before consequential execution.
    """
    if action_name == "dispatch_dispute":
        allowed, msg = cedar_attorney.enforce_dispatch_gate(human_token)
    else:
        allowed = cedar_attorney.is_action_authorized(action=action_name)
        msg = f"CEDAR_DECISION: {'ALLOW' if allowed else 'DENY'} for {action_name}"

    return {
        "action": action_name,
        "is_authorized": allowed,
        "status_message": msg
    }

@tool
def generate_erisa_appeal(eob_dict: Dict[str, Any], audit_dict: Dict[str, Any], human_token: Optional[str] = None) -> Dict[str, Any]:
    """
    Synthesizes a formal ERISA § 503 statutory dispute packet.
    Checks Cedar authorization before compiling final packet.
    """
    cedar_check = evaluate_cedar_policy("draft_statutory_appeal")
    if not cedar_check["is_authorized"]:
        raise PermissionError("Cedar authorization failed: Agent not permitted to draft appeal.")

    eob = EOBDocument(**eob_dict)
    audit = AuditResult(**audit_dict)
    
    from src.core.auth import verify_cryptographic_token
    is_signed = bool(human_token and verify_cryptographic_token(human_token))
    packet = ERISAAppealGenerator.compile_appeal_packet(eob, audit, cedar_verified=is_signed)
    
    return packet.model_dump()

@tool
def dispatch_statutory_dispute(appeal_packet_dict: Dict[str, Any], human_signature_token: Optional[str]) -> Dict[str, Any]:
    """
    Dispatches a formal statutory dispute packet.
    MANDATORY CEDAR GATE: Blocked unless verified human token is present.
    """
    allowed, msg = cedar_attorney.enforce_dispatch_gate(human_signature_token)
    
    if not allowed:
        return {
            "success": False,
            "error_code": 403,
            "cedar_decision": "EXPLICIT_DENY",
            "message": msg
        }

    return {
        "success": True,
        "packet_id": appeal_packet_dict.get("packet_id"),
        "claim_id": appeal_packet_dict.get("claim_id"),
        "cedar_decision": "ALLOW",
        "message": "Statutory dispute packet certified and ready for submission under member authority."
    }

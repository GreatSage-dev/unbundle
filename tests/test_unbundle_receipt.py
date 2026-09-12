import json
import pytest
from pathlib import Path
from src.agent.tools import (
    audit_eob_claims,
    evaluate_cedar_policy,
    generate_erisa_appeal,
    dispatch_statutory_dispute
)
from src.runtime.event_handler import BedrockAgentCoreEventHandler
from src.core.models import ViolationType

FIXTURES_DIR = Path(__file__).parent / "fixtures"

def load_fixture(filename: str) -> dict:
    path = FIXTURES_DIR / filename
    return json.loads(path.read_text(encoding="utf-8"))

def test_case_1_clean_preventative_claim():
    """
    Case 1 (The Silence Test): Routine annual physical exam.
    Must silently archive with ZERO user interruptions or alerts.
    """
    eob = load_fixture("clean_preventative_claim.json")
    handler = BedrockAgentCoreEventHandler()
    event = {"bucket": "eob-inbound-sentinel", "key": "eobs/clean_claim.json"}
    
    result = handler.handle_s3_eob_event(event, eob)
    
    assert result["event_status"] == "SILENTLY_ARCHIVED"
    assert result["user_interrupted"] is False
    assert result["audit_result"]["has_violations"] is False
    assert result["audit_result"]["total_excised_amount"] == 0.0
    assert result["audit_result"]["revised_patient_liability"] == 0.0

def test_case_2_ncci_ptp_unbundling_indicator_0():
    """
    Case 2 (NCCI Indicator 0): Comprehensive Panel (80053) + Basic Panel (80048).
    CMS PTP Indicator 0 strictly forbids separate billing. Excises $410 overcharge.
    """
    eob = load_fixture("ncci_indicator_0_unbundling.json")
    audit = audit_eob_claims(eob)
    
    assert audit["has_violations"] is True
    assert audit["status"] == "DISCREPANCY_DETECTED"
    assert audit["total_excised_amount"] == 410.0
    assert audit["revised_patient_liability"] == 50.0  # Original $460 - $410 excised
    
    violation = audit["violations"][0]
    assert violation["violation_type"] == ViolationType.NCCI_INDICATOR_0_UNBUNDLING.value
    assert violation["primary_code"] == "80053"
    assert violation["secondary_code"] == "80048"
    assert "CMS NCCI Policy Manual" in violation["statutory_reference"]

def test_case_3_modifier_59_abuse_detected():
    """
    Case 3 (Modifier Creep): Hospital appended Modifier 59 to CT Scan (70450)
    without clinical documentation of distinct anatomical site. Caught & excised ($2,180).
    """
    eob = load_fixture("modifier_59_abuse.json")
    audit = audit_eob_claims(eob)
    
    assert audit["has_violations"] is True
    assert audit["total_excised_amount"] == 2180.0
    assert audit["revised_patient_liability"] == 200.0  # ER copay remains
    
    mod59_violation = next(v for v in audit["violations"] if v["violation_type"] == ViolationType.NCCI_MODIFIER_59_ABUSE.value)
    assert mod59_violation["primary_code"] == "99285"
    assert mod59_violation["secondary_code"] == "70450"
    assert "Modifier 59 Abuse" in mod59_violation["explanation"]

def test_case_4_carc_balance_shift_violation():
    """
    Case 4 (Predatory Balance Shift): Insurer marked unbundled service as CARC 97
    but shifted $840 to Patient Responsibility (PR). Intercepted under ERISA guidelines.
    """
    eob = load_fixture("carc_balance_shift.json")
    audit = audit_eob_claims(eob)
    
    assert audit["has_violations"] is True
    assert audit["total_excised_amount"] == 840.0
    assert audit["revised_patient_liability"] == 0.0
    
    carc_violation = next(v for v in audit["violations"] if "CARC" in v["violation_type"])
    assert carc_violation["excised_amount"] == 840.0
    assert "ERISA § 503" in carc_violation["statutory_reference"]

def test_case_5_cedar_policy_enforces_hard_deny():
    """
    Case 5 (Cedar Security Boundary):
    1. Agent attempts autonomous dispatch without human signature -> CEDAR EXPLICIT_DENY (403).
    2. Human approves via cryptographic token -> CEDAR ALLOW (200).
    """
    eob = load_fixture("ncci_indicator_0_unbundling.json")
    audit = audit_eob_claims(eob)
    packet = generate_erisa_appeal(eob, audit, human_token=None)
    
    # Step 1: Hostile Autonomous Dispatch Attempt (No Token)
    unauthorized_attempt = dispatch_statutory_dispute(packet, human_signature_token=None)
    assert unauthorized_attempt["success"] is False
    assert unauthorized_attempt["error_code"] == 403
    assert unauthorized_attempt["cedar_decision"] == "EXPLICIT_DENY"
    
    # Step 2: Authorized Human-in-the-Loop Dispatch
    authorized_attempt = dispatch_statutory_dispute(packet, human_signature_token="HUMAN_AUTH_TOKEN_ROBERTC_2026")
    assert authorized_attempt["success"] is True
    assert authorized_attempt["cedar_decision"] == "ALLOW"
    assert "certified" in authorized_attempt["message"].lower()

def test_case_6_erisa_appeal_packet_format():
    """
    Case 6 (Statutory Document Synthesis):
    Verifies formal ERISA § 503 legal citations, claim deltas, and demand structure.
    """
    eob = load_fixture("ncci_indicator_0_unbundling.json")
    audit = audit_eob_claims(eob)
    packet = generate_erisa_appeal(eob, audit, human_token="HUMAN_AUTH_TOKEN_ROBERTC_2026")
    
    assert packet["claim_id"] == "CLM-2026-NCCI-02"
    assert packet["disputed_amount"] == 410.0
    assert packet["cedar_authorization_verified"] is True
    
    letter = packet["formal_appeal_letter"]
    assert "ERISA § 503 (29 U.S.C. § 1133)" in letter
    assert "29 CFR § 2560.503-1" in letter
    assert "CLM-2026-NCCI-02" in letter
    assert "$410.00" in letter
    assert "VERIFIED_HUMAN_SIGNATURE_TOKEN" in letter

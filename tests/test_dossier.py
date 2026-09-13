import json
import re
from pathlib import Path
import pytest

from src.agent.tools import (
    audit_eob_claims,
    generate_erisa_appeal
)
from src.packet.dossier_renderer import render_dossier_html
from src.lifecycle.tracker import StatutoryClockTracker
from src.ingest.eob_parser import RealEOBParser

FIXTURES_DIR = Path(__file__).parent / "fixtures"


def load_fixture(filename: str) -> dict:
    path = FIXTURES_DIR / filename
    return json.loads(path.read_text(encoding="utf-8"))


def test_render_dossier_with_ncci_indicator_0():
    """
    Verifies dossier rendering with NCCI Indicator 0 unbundling claim.
    Validates legal caption, metadata ledger, violation table, statutory citations,
    cryptographic SHA-256 integrity hash, and print CSS.
    """
    eob = load_fixture("ncci_indicator_0_unbundling.json")
    audit = audit_eob_claims(eob)
    human_token = "HUMAN_AUTH_TOKEN_ROBERTC_2026"
    packet = generate_erisa_appeal(eob, audit, human_token=human_token)

    html_out = render_dossier_html(packet, eob, audit)

    # 1. Document Structure & Legal Caption
    assert "<!DOCTYPE html>" in html_out
    assert "BEFORE THE PLAN ADMINISTRATOR / APPEALS COMMITTEE" in html_out
    assert "ADMINISTERED PURSUANT TO 29 U.S.C. § 1133 (ERISA § 503) &amp; 29 CFR § 2560.503-1(g)" in html_out
    assert "IN RE THE CLAIM OF:" in html_out
    assert "Robert Chen" in html_out
    assert "Metro Diagnostic Laboratories" in html_out

    # 2. Metadata Block
    assert "CLM-2026-NCCI-02" in html_out
    assert "MBR-554109" in html_out
    assert "$1,030.00" in html_out  # Total Billed
    assert "$410.00" in html_out    # Excised Amount
    assert "$50.00" in html_out     # Lawful Liability

    # 3. Section 1: Formal Statutory Demand
    assert "Formal Statutory Demand for Adverse Benefit Determination Reversal" in html_out
    assert "COMES NOW THE CLAIMANT" in html_out
    assert "29 CFR § 2560.503-1(h)(2)(iii)" in html_out
    assert "Contractual Obligations (CO-45)" in html_out

    # 4. Section 2: Itemized Table of Audit Violations
    assert "Itemized Table of Audit Violations &amp; Deterministic Findings" in html_out
    assert "80048" in html_out  # Secondary CPT Billed
    assert "80053" in html_out  # Primary Comprehensive CPT
    assert "CMS NCCI PTP" in html_out

    # 5. Section 3: Statutory Citations & Legal Authorities
    assert "29 U.S.C. § 1133" in html_out
    assert "ERISA § 503" in html_out
    assert "29 CFR § 2560.503-1" in html_out
    assert "CMS NCCI Policy Manual" in html_out
    assert "No Surprises Act" in html_out

    # 6. Section 4: Cryptographic Human Signature & Certificate of Service
    assert "Certificate of Service Under Federal Rule" in html_out
    assert "Human-in-the-Loop Signature Block" in html_out
    assert human_token in html_out
    assert "CEDAR VERIFIED" in html_out

    # Verify 64-character hex SHA-256 hash is present
    sha_matches = re.findall(r"\b[a-f0-9]{64}\b", html_out)
    assert len(sha_matches) >= 1, "Expected SHA-256 audit integrity hash to be present in HTML output"

    # 7. Print CSS & Floating Action Bar
    assert "@media print" in html_out
    assert "size: letter portrait;" in html_out
    assert "floating-action-bar" in html_out
    assert "window.print()" in html_out
    assert "Download Text (.txt)" in html_out
    assert "/console" in html_out


def test_render_dossier_with_modifier_59_abuse():
    """
    Verifies dossier rendering with Modifier 59 abuse claim.
    """
    eob = load_fixture("modifier_59_abuse.json")
    audit = audit_eob_claims(eob)
    human_token = "HUMAN_AUTH_TOKEN_ELEANORV_2026"
    packet = generate_erisa_appeal(eob, audit, human_token=human_token)

    html_out = render_dossier_html(packet, eob, audit)

    assert "Eleanor Vance" in html_out
    assert "CLM-2026-MOD59-03" in html_out
    assert "$2,180.00" in html_out  # Excised overcharge
    assert "$200.00" in html_out    # Lawful ER copay
    assert "70450" in html_out      # CT Scan Head
    assert "99285" in html_out      # Primary ER Visit
    assert "Emergency Medical Services" in html_out
    assert "45 CFR § 149.30" in html_out


def test_render_dossier_with_carc_balance_shift_and_tracking_clock():
    """
    Verifies dossier rendering with CARC balance shift and active 30-day statutory clock.
    """
    eob = load_fixture("carc_balance_shift.json")
    audit = audit_eob_claims(eob)
    packet = generate_erisa_appeal(eob, audit, human_token="HUMAN_AUTH_TOKEN_MARCUSB_2026")

    tracker = StatutoryClockTracker.create(
        packet_id=packet["packet_id"],
        claim_id=eob["claim_id"],
        patient_name=eob["patient_name"],
        payor_name=eob["provider_name"],
        disputed_amount=packet["disputed_amount"]
    )
    tracking_status = tracker.record_dispatch()

    html_out = render_dossier_html(packet, eob, audit, tracking_status=tracking_status)

    assert "Marcus Brody" in html_out
    assert "$840.00" in html_out  # Excised amount
    assert "$0.00" in html_out    # Revised lawful liability
    assert "STATUTORY 30-DAY CLOCK STATUS:" in html_out
    assert "PENDING_PAYOR_RESPONSE" in html_out
    assert "Deemed Exhaustion of Administrative Remedies under 29 CFR § 2560.503-1(l)" in html_out


def test_render_dossier_with_real_unstructured_eob():
    """
    Verifies end-to-end flow from unstructured EOB text to court-ready dossier.
    """
    raw_text = (FIXTURES_DIR / "real_unstructured_eob.txt").read_text(encoding="utf-8")
    parser = RealEOBParser(confidence_threshold=0.90)
    report = parser.parse_raw_text(raw_text)
    doc_dict = report.document.model_dump()

    audit = audit_eob_claims(doc_dict)
    packet = generate_erisa_appeal(doc_dict, audit, human_token="HUMAN_AUTH_TOKEN_ROBERTC_2026")

    html_out = render_dossier_html(packet, doc_dict, audit)

    assert "ELEANOR RIGBY" in html_out
    assert "CLM-2026-NY-8912" in html_out
    assert "MEMORIAL REGIONAL HEALTH" in html_out
    assert "$190.00" in html_out  # Excised Basic Metabolic Panel
    assert "80048" in html_out
    assert "80053" in html_out
    assert "BEFORE THE PLAN ADMINISTRATOR / APPEALS COMMITTEE" in html_out

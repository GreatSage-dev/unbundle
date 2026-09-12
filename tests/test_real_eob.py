from pathlib import Path
from src.ingest.eob_parser import RealEOBParser
from src.agent.tools import audit_eob_claims

def test_real_unstructured_eob_parsing():
    fixture_path = Path(__file__).parent / "fixtures" / "real_unstructured_eob.txt"
    raw_text = fixture_path.read_text(encoding="utf-8")

    parser = RealEOBParser(confidence_threshold=0.90)
    report = parser.parse_raw_text(raw_text)

    # 1. Verify Header Extraction
    assert report.patient_name == "ELEANOR RIGBY"
    assert report.claim_id == "CLM-2026-NY-8912"
    assert report.provider_name == "MEMORIAL REGIONAL HEALTH"

    # 2. Verify Table Lines Parsed
    assert report.total_lines_parsed == 6
    assert report.lines_mapped_high_confidence == 4
    assert report.lines_quarantined_by_safety_gate == 2

    # 3. Verify Deltr Bug Story: Ambiguous lines quarantined
    assert len(report.bug_story_notes) == 2
    assert "MISC SURGICAL SUPPLIES" in report.bug_story_notes[0]
    assert "GLOBAL FACILITY OVERHEAD" in report.bug_story_notes[1]

    # 4. Verify Audited Document catches NCCI Indicator 0 unbundling
    doc_dict = report.document.model_dump()
    audit_res = audit_eob_claims(doc_dict)

    assert audit_res["has_violations"] is True
    assert len(audit_res["violations"]) >= 1
    # Line 2: Basic Metabolic Panel (80048) unbundled from Comprehensive Metabolic Panel (80053)
    violation = audit_res["violations"][0]
    assert violation["primary_code"] == "80053"
    assert violation["secondary_code"] == "80048"
    assert violation["excised_amount"] == 190.0

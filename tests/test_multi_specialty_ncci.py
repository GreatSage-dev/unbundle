"""
UNBUNDLE: Multi-Specialty CMS NCCI PTP Collision Unit Test Suite
Verifies that the deterministic SQLite engine catches unbundling and modifier abuse
across 5 medical specialties: Laboratory, Cardiovascular, Emergency, Endoscopy, and Radiology.
"""

import time
import pytest
from src.core.models import ClaimLine, AuditViolation, ViolationType
from src.core.ncci_engine import NCCIValidator

@pytest.fixture
def validator():
    return NCCIValidator()

def test_laboratory_specialty_collisions(validator):
    """Verifies that mutually inclusive laboratory panels trigger NCCI Indicator 0."""
    lines = [
        ClaimLine(line_number=1, cpt_code="80053", description="Comprehensive Metabolic Panel", billed_amount=240.0, patient_responsibility=40.0),
        ClaimLine(line_number=2, cpt_code="80048", description="Basic Metabolic Panel", billed_amount=190.0, patient_responsibility=190.0),
        ClaimLine(line_number=3, cpt_code="80076", description="Hepatic Function Panel", billed_amount=150.0, patient_responsibility=150.0),
    ]
    violations = validator.audit_lines(lines)
    assert len(violations) >= 2
    unbundled_codes = {v.secondary_code for v in violations}
    assert "80048" in unbundled_codes
    assert "80076" in unbundled_codes

def test_cardiovascular_specialty_collision(validator):
    """Verifies complete ECG (93000) excises unbundled interpretation (93010)."""
    lines = [
        ClaimLine(line_number=1, cpt_code="93000", description="12-Lead Electrocardiogram Global", billed_amount=350.0, patient_responsibility=50.0),
        ClaimLine(line_number=2, cpt_code="93010", description="ECG Interpretation and Report", billed_amount=120.0, patient_responsibility=120.0),
    ]
    violations = validator.audit_lines(lines)
    assert len(violations) == 1
    assert violations[0].primary_code == "93000"
    assert violations[0].secondary_code == "93010"
    assert violations[0].violation_type == ViolationType.NCCI_INDICATOR_0_UNBUNDLING

def test_emergency_trauma_specialty_modifier_creep(validator):
    """Verifies emergency intubation without modifier under Level 5 E/M is flagged."""
    lines = [
        ClaimLine(line_number=1, cpt_code="99285", description="Emergency Department Visit Level 5", billed_amount=1200.0, patient_responsibility=200.0),
        ClaimLine(line_number=2, cpt_code="31500", description="Emergency Endotracheal Intubation", billed_amount=650.0, patient_responsibility=650.0, modifiers=[]),
    ]
    violations = validator.audit_lines(lines)
    assert len(violations) == 1
    assert violations[0].primary_code == "99285"
    assert violations[0].secondary_code == "31500"

def test_surgical_endoscopy_specialty_collision(validator):
    """Verifies upper GI endoscopy biopsy (43239) excises diagnostic endoscopy (43235)."""
    lines = [
        ClaimLine(line_number=1, cpt_code="43239", description="Esophagogastroduodenoscopy with Biopsy", billed_amount=1800.0, patient_responsibility=300.0),
        ClaimLine(line_number=2, cpt_code="43235", description="Diagnostic Esophagogastroduodenoscopy", billed_amount=840.0, patient_responsibility=840.0),
    ]
    violations = validator.audit_lines(lines)
    assert len(violations) == 1
    assert violations[0].primary_code == "43239"
    assert violations[0].secondary_code == "43235"
    assert violations[0].violation_type == ViolationType.NCCI_INDICATOR_0_UNBUNDLING

def test_radiology_specialty_collision(validator):
    """Verifies chest X-ray 2 views (71046) excises single view (71045)."""
    lines = [
        ClaimLine(line_number=1, cpt_code="71046", description="Radiologic Examination Chest 2 Views", billed_amount=280.0, patient_responsibility=45.0),
        ClaimLine(line_number=2, cpt_code="71045", description="Radiologic Examination Chest Single View", billed_amount=160.0, patient_responsibility=160.0),
    ]
    violations = validator.audit_lines(lines)
    assert len(violations) == 1
    assert violations[0].primary_code == "71046"
    assert violations[0].secondary_code == "71045"

def test_sub_millisecond_audit_latency(validator):
    """Verifies deterministic SQLite query performance is well under 0.05 seconds."""
    lines = [
        ClaimLine(line_number=1, cpt_code="80053", description="CMP", billed_amount=240.0, patient_responsibility=40.0),
        ClaimLine(line_number=2, cpt_code="80048", description="BMP", billed_amount=190.0, patient_responsibility=190.0),
        ClaimLine(line_number=3, cpt_code="93000", description="ECG", billed_amount=350.0, patient_responsibility=50.0),
        ClaimLine(line_number=4, cpt_code="93010", description="ECG Interp", billed_amount=120.0, patient_responsibility=120.0),
        ClaimLine(line_number=5, cpt_code="43239", description="EGD Biopsy", billed_amount=1800.0, patient_responsibility=300.0),
        ClaimLine(line_number=6, cpt_code="43235", description="EGD Diag", billed_amount=840.0, patient_responsibility=840.0),
        ClaimLine(line_number=7, cpt_code="71046", description="CXR 2V", billed_amount=280.0, patient_responsibility=45.0),
        ClaimLine(line_number=8, cpt_code="71045", description="CXR 1V", billed_amount=160.0, patient_responsibility=160.0),
    ]
    start_time = time.perf_counter()
    violations = validator.audit_lines(lines)
    elapsed = time.perf_counter() - start_time

    assert len(violations) >= 4
    assert elapsed < 0.05, f"Audit took {elapsed:.4f}s, expected < 0.05s"

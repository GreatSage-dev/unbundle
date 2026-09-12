"""
UNBUNDLE: Real-World Messy EOB Ingestion & Clinical Description Normalizer
Handles unstructured payor ASCII/text exports, OCR dumps, and abbreviated hospital charge lines.

THE DELTR SAFETY GATE (THE BUG STORY):
In the wild, hospital billing departments frequently strip 5-digit CPT codes or use proprietary
descriptions like "MISC SURGICAL SUPPLIES TRAY 3" or "GLOBAL OVERHEAD".
Probabilistic LLMs routinely hallucinate CPT codes for these descriptions.
UNBUNDLE implements a strict Confidence Gate:
- Confidence >= 0.90: Mapped to verified CPT code and passed to deterministic SQLite NCCI auditor.
- Confidence < 0.90: Quarantined as REQUIRES_CLINICAL_VERIFICATION. Never passed to NCCI engine
  to prevent false-positive audit collisions.
"""

import re
from typing import List, Dict, Tuple, Optional, Any
from pydantic import BaseModel, Field
from src.core.models import ClaimLine, EOBDocument

# Clinical Description to CPT Crosswalk with Ground-Truth Confidence
CLINICAL_DESCRIPTION_CROSSWALK: Dict[str, Tuple[str, float, str]] = {
    # Key substrings (case-insensitive) -> (CPT, Confidence, Canonical Name)
    "COMP METAB PNL": ("80053", 0.98, "Comprehensive Metabolic Panel"),
    "BASIC METAB PNL": ("80048", 0.98, "Basic Metabolic Panel"),
    "HC EMERG DEPT VISIT HIGH SEV": ("99285", 0.95, "Emergency Dept Visit, High Severity"),
    "EMERG DEPT VISIT HIGH": ("99285", 0.95, "Emergency Dept Visit, High Severity"),
    "HC CT SCAN HEAD/BRAIN": ("70450", 0.95, "CT Head/Brain without Contrast"),
    "CT SCAN HEAD/BRAIN": ("70450", 0.95, "CT Head/Brain without Contrast"),
    "UPR GI ENDO W/ BIOPSY": ("43239", 0.95, "EGD with Biopsy"),
    "UPR GI ENDOSCOPY DIAGNOSTIC": ("43235", 0.95, "Diagnostic EGD"),
    "PREV VISIT EST 40-64": ("99396", 0.98, "Preventative Physical Exam Age 40-64"),
    "ROUTINE VENIPUNCTURE": ("36415", 0.98, "Routine Blood Draw / Venipuncture")
}

class ParsedLineResult(BaseModel):
    line_number: int
    raw_description: str
    resolved_cpt: Optional[str] = None
    canonical_name: Optional[str] = None
    confidence: float = 0.0
    billed_amount: float
    allowed_amount: float
    patient_responsibility: float
    carc_codes: List[str] = Field(default_factory=list)
    group_code: str = "CO"
    quarantined_by_safety_gate: bool = False
    quarantine_reason: Optional[str] = None

class IngestReport(BaseModel):
    patient_name: str
    claim_id: str
    provider_name: str
    total_lines_parsed: int
    lines_mapped_high_confidence: int
    lines_quarantined_by_safety_gate: int
    quarantined_charges_total: float
    bug_story_notes: List[str] = Field(default_factory=list)
    document: EOBDocument

class RealEOBParser:
    """Parses raw text/OCR dumps from payor EOB portals."""

    def __init__(self, confidence_threshold: float = 0.90):
        self.confidence_threshold = confidence_threshold

    def parse_raw_text(self, text: str) -> IngestReport:
        lines = [line.strip() for line in text.strip().splitlines() if line.strip()]

        # 1. Extract Header Metadata
        patient_name = self._extract_field(r"Patient:\s*([A-Za-z\s]+?)(?:\s+Group|\s*$)", text) or "UNKNOWN PATIENT"
        member_id = self._extract_field(r"Member ID:\s*([A-Za-z0-9\-]+)", text) or "UNKNOWN-ID"
        claim_id = self._extract_field(r"Claim #:\s*([A-Za-z0-9\-]+)", text) or "CLM-UNKNOWN"
        provider_name = self._extract_field(r"Provider:\s*([A-Za-z0-9\s]+?)(?:\s+Claim|\s*$)", text) or "UNKNOWN PROVIDER"
        service_date = self._extract_field(r"Date of Service:\s*([0-9\/]+)", text) or "2026-01-01"
        in_network = "IN-NETWORK" in text.upper()

        parsed_line_results: List[ParsedLineResult] = []
        claim_lines: List[ClaimLine] = []
        bug_story_notes: List[str] = []

        # 2. Extract Table Lines
        # Regex matching line rows: e.g. "01 01/14/2026 COMP METAB PNL $220.00 $110.00 $88.00 $22.00 PR-1, PR-2"
        line_pattern = re.compile(
            r"^(\d{1,3})\s+\d{2}/\d{2}/\d{4}\s+(.+?)\s+\$([0-9,]+\.\d{2})\s+\$([0-9,]+\.\d{2})\s+\$([0-9,]+\.\d{2})\s+\$([0-9,]+\.\d{2})(?:\s+(.*))?$"
        )

        for line_str in lines:
            m = line_pattern.match(line_str)
            if not m:
                continue

            line_num = int(m.group(1))
            raw_desc = m.group(2).strip()
            billed_val = float(m.group(3).replace(",", ""))
            allowed_val = float(m.group(4).replace(",", ""))
            # group 5 is plan paid
            patient_resp_val = float(m.group(6).replace(",", ""))
            raw_remarks = m.group(7) or ""

            # Extract CARC codes from remarks
            carcs: List[str] = []
            group_code = "CO"
            if "PR-" in raw_remarks:
                group_code = "PR"
            
            for code_match in re.findall(r"(?:PR|CO|OA|CR)-(\d+)", raw_remarks):
                carcs.append(code_match)

            # 3. Clinical Description Resolution & Confidence Scorer
            resolved_cpt, confidence, canonical_name = self._resolve_clinical_description(raw_desc)

            if confidence >= self.confidence_threshold and resolved_cpt is not None:
                # High-confidence deterministic mapping
                result = ParsedLineResult(
                    line_number=line_num,
                    raw_description=raw_desc,
                    resolved_cpt=resolved_cpt,
                    canonical_name=canonical_name,
                    confidence=confidence,
                    billed_amount=billed_val,
                    allowed_amount=allowed_val,
                    patient_responsibility=patient_resp_val,
                    carc_codes=carcs,
                    group_code=group_code,
                    quarantined_by_safety_gate=False
                )
                parsed_line_results.append(result)
                claim_lines.append(
                    ClaimLine(
                        line_number=line_num,
                        cpt_code=resolved_cpt,
                        description=canonical_name or raw_desc,
                        billed_amount=billed_val,
                        allowed_amount=allowed_val,
                        patient_responsibility=patient_resp_val,
                        group_code=group_code,
                        carc_codes=carcs
                    )
                )
            else:
                # DELTR BUG STORY GATE: Quarantined
                reason = (
                    f"Ambiguous non-standard hospital charge string '{raw_desc}' has confidence {confidence:.2f} "
                    f"(below safety threshold {self.confidence_threshold:.2f}). Refusing to invent CPT code."
                )
                result = ParsedLineResult(
                    line_number=line_num,
                    raw_description=raw_desc,
                    resolved_cpt=None,
                    canonical_name="QUARANTINED_CHARGE",
                    confidence=confidence,
                    billed_amount=billed_val,
                    allowed_amount=allowed_val,
                    patient_responsibility=patient_resp_val,
                    carc_codes=carcs,
                    group_code=group_code,
                    quarantined_by_safety_gate=True,
                    quarantine_reason=reason
                )
                parsed_line_results.append(result)
                bug_story_notes.append(f"Line {line_num}: {reason}")

        # Construct typed EOBDocument for high-confidence audited lines
        total_billed = sum(l.billed_amount for l in claim_lines)
        total_allowed = sum(l.allowed_amount for l in claim_lines)
        total_patient_resp = sum(l.patient_responsibility for l in claim_lines)

        doc = EOBDocument(
            claim_id=claim_id,
            patient_name=patient_name,
            patient_id=member_id,
            provider_name=provider_name,
            service_date=service_date,
            in_network=in_network,
            total_billed=total_billed,
            total_allowed=total_allowed,
            total_patient_responsibility=total_patient_resp,
            lines=claim_lines
        )

        quarantined = [r for r in parsed_line_results if r.quarantined_by_safety_gate]

        return IngestReport(
            patient_name=patient_name,
            claim_id=claim_id,
            provider_name=provider_name,
            total_lines_parsed=len(parsed_line_results),
            lines_mapped_high_confidence=len(claim_lines),
            lines_quarantined_by_safety_gate=len(quarantined),
            quarantined_charges_total=sum(r.billed_amount for r in quarantined),
            bug_story_notes=bug_story_notes,
            document=doc
        )

    def _resolve_clinical_description(self, raw_desc: str) -> Tuple[Optional[str], float, Optional[str]]:
        desc_upper = raw_desc.upper()

        # Check if an exact 5-digit CPT code already exists in description
        cpt_match = re.search(r"\b(\d{5})\b", raw_desc)
        if cpt_match:
            code = cpt_match.group(1)
            return code, 0.99, f"CPT-{code}"

        for key, (cpt, conf, canonical) in CLINICAL_DESCRIPTION_CROSSWALK.items():
            if key in desc_upper:
                return cpt, conf, canonical

        # Unmatched clinical description
        return None, 0.25, None

    def _extract_field(self, pattern: str, text: str) -> Optional[str]:
        m = re.search(pattern, text, re.IGNORECASE)
        return m.group(1).strip() if m else None

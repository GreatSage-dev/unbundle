import json
from pathlib import Path
from typing import List, Optional
from src.core.models import ClaimLine, AuditViolation, ViolationType

CROSSWALK_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "carc_rarc_crosswalk.json"

class CARCValidator:
    """
    Deterministic Claim Adjustment Reason Code (CARC) & Group Code Validator.
    Catches predatory balance-shifting where contractual adjustments (CO) are improperly
    reclassified as Patient Responsibility (PR).
    """
    def __init__(self, crosswalk_path: Optional[Path] = None):
        self.crosswalk_path = crosswalk_path or CROSSWALK_PATH
        with open(self.crosswalk_path, "r", encoding="utf-8") as f:
            self.crosswalk = json.load(f)

    def audit_liability_shifts(self, lines: List[ClaimLine], in_network: bool = True) -> List[AuditViolation]:
        violations: List[AuditViolation] = []

        for line in lines:
            # Check each CARC code on this claim line
            for code_entry in line.carc_codes:
                # normalize code: e.g. "CO-97", "PR-97", "97" -> "97"
                raw_code = code_entry.split("-")[-1].strip()
                carc_key = f"CARC_{raw_code}"

                if carc_key not in self.crosswalk:
                    continue

                spec = self.crosswalk[carc_key]
                target_violation_group = spec["violation_if_assigned_to"]  # "PR"

                # If line is assigned to PR and has an adjustment code that MUST be CO
                if line.group_code == target_violation_group and in_network:
                    if raw_code == "97":
                        # Unbundled service re-billed to patient
                        violations.append(AuditViolation(
                            violation_type=ViolationType.CARC_UNBUNDLED_BALANCE_SHIFT,
                            primary_code=line.cpt_code,
                            secondary_code=None,
                            line_number=line.line_number,
                            excised_amount=line.patient_responsibility,
                            statutory_reference=spec["statutory_citation"],
                            explanation=(
                                f"Predatory Balance Shift (CARC 97): Insurer correctly adjudicated CPT {line.cpt_code} "
                                f"as an unbundled service included in primary procedure payment, but improperly "
                                f"shifted ${line.patient_responsibility:.2f} to Patient Responsibility (PR). "
                                f"Remedy: {spec['remedy']}"
                            )
                        ))
                    elif raw_code == "45":
                        # Contractual allowance overage billed to patient (Balance Billing)
                        violations.append(AuditViolation(
                            violation_type=ViolationType.NO_SURPRISES_ACT_BALANCE_BILL,
                            primary_code=line.cpt_code,
                            secondary_code=None,
                            line_number=line.line_number,
                            excised_amount=line.patient_responsibility,
                            statutory_reference=spec["statutory_citation"],
                            explanation=(
                                f"Balance Billing Violation (CARC 45): Provider billed ${line.patient_responsibility:.2f} "
                                f"exceeding in-network contracted fee schedule. In-network provider is bound to write off "
                                f"this contractual difference under 45 CFR § 149.30."
                            )
                        ))

        return violations

import sqlite3
from pathlib import Path
from typing import List, Optional, Tuple
from src.core.models import ClaimLine, AuditViolation, ViolationType

DB_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "ncci_ptp_edits.db"

class NCCIValidator:
    """
    Deterministic CMS National Correct Coding Initiative (NCCI) PTP Edit Validator.
    Executes binary pair-wise lookups against CMS Medicare/Medicaid Column 1 / Column 2 tables.
    Zero LLM hallucination - 100% hard SQLite verification.
    """
    def __init__(self, db_path: Optional[Path] = None):
        self.db_path = db_path or DB_PATH
        if not self.db_path.exists():
            raise FileNotFoundError(f"NCCI database not found at {self.db_path}. Run seed_ncci_db.py first.")

    def _query_ptp_collision(self, col1: str, col2: str) -> Optional[Tuple[int, str]]:
        """Queries whether col2 is a component of col1, returning (modifier_indicator, rationale)."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute(
            "SELECT modifier_indicator, policy_rationale FROM ncci_ptp_edits WHERE column_1 = ? AND column_2 = ?",
            (col1, col2)
        )
        row = cursor.fetchone()
        conn.close()
        return (row[0], row[1]) if row else None

    def audit_lines(self, lines: List[ClaimLine]) -> List[AuditViolation]:
        """
        Audits all claim lines in O(N^2) against CMS NCCI PTP tables.
        Checks for:
        1. Indicator 0: Hard unbundling (never allowed).
        2. Indicator 1 without modifier: Unbundling without clinical exception.
        3. Indicator 1 with Modifier 59/25 but no separate site: Modifier Creep.
        """
        violations: List[AuditViolation] = []
        n = len(lines)

        for i in range(n):
            for j in range(n):
                if i == j:
                    continue
                line_a = lines[i]
                line_b = lines[j]

                collision = self._query_ptp_collision(line_a.cpt_code, line_b.cpt_code)
                if not collision:
                    continue

                mod_indicator, rationale = collision

                # Case 1: Modifier Indicator 0 - Absolute Unbundling Prohibition
                if mod_indicator == 0:
                    violations.append(AuditViolation(
                        violation_type=ViolationType.NCCI_INDICATOR_0_UNBUNDLING,
                        primary_code=line_a.cpt_code,
                        secondary_code=line_b.cpt_code,
                        line_number=line_b.line_number,
                        excised_amount=line_b.patient_responsibility or line_b.billed_amount,
                        statutory_reference="CMS NCCI Policy Manual, Chapter 1, Section A (PTP Indicator 0)",
                        explanation=(
                            f"Illegal Unbundling: Secondary CPT {line_b.cpt_code} is an integral component "
                            f"of primary CPT {line_a.cpt_code}. CMS PTP Indicator 0 strictly forbids separate "
                            f"billing under any circumstances. Rationale: {rationale}."
                        )
                    ))

                # Case 2: Modifier Indicator 1 - Modifier 59 / Distinct Service Rules
                elif mod_indicator == 1:
                    has_modifier_59 = any(m in ["59", "XE", "XS", "XP", "XU"] for m in line_b.modifiers)
                    
                    if not has_modifier_59:
                        violations.append(AuditViolation(
                            violation_type=ViolationType.NCCI_INDICATOR_0_UNBUNDLING,
                            primary_code=line_a.cpt_code,
                            secondary_code=line_b.cpt_code,
                            line_number=line_b.line_number,
                            excised_amount=line_b.patient_responsibility or line_b.billed_amount,
                            statutory_reference="CMS NCCI Policy Manual, Chapter 1, Section E (PTP Indicator 1)",
                            explanation=(
                                f"Unbundled Procedure: CPT {line_b.cpt_code} is mutually exclusive with CPT {line_a.cpt_code} "
                                f"and lacked an appropriate CMS clinical modifier (Modifier 59/X-subset)."
                            )
                        ))
                    elif not line_b.distinct_site_documented:
                        # Case 3: Modifier 59 Abuse (Modifier Creep)
                        violations.append(AuditViolation(
                            violation_type=ViolationType.NCCI_MODIFIER_59_ABUSE,
                            primary_code=line_a.cpt_code,
                            secondary_code=line_b.cpt_code,
                            line_number=line_b.line_number,
                            excised_amount=line_b.patient_responsibility or line_b.billed_amount,
                            statutory_reference="CMS Transmittal 1422; OIG Report OEI-05-02-00060 (Modifier 59 Abuse)",
                            explanation=(
                                f"Modifier 59 Abuse (Modifier Creep): Provider appended Modifier 59 to CPT {line_b.cpt_code} "
                                f"to bypass CMS unbundling edit against CPT {line_a.cpt_code}, but the claim lacks "
                                f"documentation of a distinct anatomical organ/site or separate patient encounter."
                            )
                        ))

        return violations

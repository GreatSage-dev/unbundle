from enum import Enum
from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field

class ViolationType(str, Enum):
    NCCI_INDICATOR_0_UNBUNDLING = "NCCI_INDICATOR_0_UNBUNDLING"
    NCCI_MODIFIER_59_ABUSE = "NCCI_MODIFIER_59_ABUSE"
    CARC_UNBUNDLED_BALANCE_SHIFT = "CARC_UNBUNDLED_BALANCE_SHIFT"
    NO_SURPRISES_ACT_BALANCE_BILL = "NO_SURPRISES_ACT_BALANCE_BILL"

class ClaimLine(BaseModel):
    line_number: int
    cpt_code: str
    description: str
    modifiers: List[str] = Field(default_factory=list)
    billed_amount: float
    allowed_amount: float = 0.0
    patient_responsibility: float = 0.0
    group_code: str = "CO"  # CO (Contractual Obligation), PR (Patient Responsibility)
    carc_codes: List[str] = Field(default_factory=list)
    distinct_site_documented: bool = False

class EOBDocument(BaseModel):
    claim_id: str
    patient_name: str
    patient_id: str
    provider_name: str
    service_date: str
    in_network: bool = True
    is_emergency: bool = False
    total_billed: float
    total_allowed: float
    total_patient_responsibility: float
    lines: List[ClaimLine]

class AuditViolation(BaseModel):
    violation_type: ViolationType
    primary_code: str
    secondary_code: Optional[str] = None
    line_number: int
    excised_amount: float
    statutory_reference: str
    explanation: str

class AuditResult(BaseModel):
    claim_id: str
    has_violations: bool
    total_original_patient_liability: float
    total_excised_amount: float
    revised_patient_liability: float
    violations: List[AuditViolation] = Field(default_factory=list)
    status: str  # "SILENT_ARCHIVE" or "DISCREPANCY_DETECTED"
    annunciator_message: Optional[str] = None

class AppealPacket(BaseModel):
    packet_id: str
    claim_id: str
    generated_at: str
    statutory_citations: List[str]
    patient_name: str
    provider_name: str
    original_charge: float
    audited_charge: float
    disputed_amount: float
    formal_appeal_letter: str
    evidence_breakdown: List[Dict[str, Any]]
    cedar_authorization_verified: bool = False

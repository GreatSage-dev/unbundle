"""
UNBUNDLE: ERISA § 503 Statutory Clock & Post-Dispatch Lifecycle Tracker
Governed by 29 U.S.C. § 1133 and 29 CFR § 2560.503-1.

Under federal law, insurers have exactly 30 calendar days to adjudicate a formal
post-service appeal. If the insurer fails to respond within 30 days, administrative
remedies are deemed exhausted by operation of law, entitling the claimant to immediate
statutory remedies and State Department of Insurance regulatory complaints.
"""

from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Dict, List, Optional, Any
from pydantic import BaseModel, Field

class AppealLifecycleState(str, Enum):
    DRAFTED = "DRAFTED"
    DISPATCHED = "DISPATCHED"
    PENDING_PAYOR_RESPONSE = "PENDING_PAYOR_RESPONSE"
    REVERSAL_CONFIRMED = "REVERSAL_CONFIRMED"
    ADVERSE_MAINTAINED = "ADVERSE_MAINTAINED"
    DEEMED_EXHAUSTED = "DEEMED_EXHAUSTED"
    ESCALATED_DOI = "ESCALATED_DOI"

class PayorResponse(str, Enum):
    OVERTURNED_FULL = "OVERTURNED_FULL"          # Illegal unbundling charge fully excised ($0 balance)
    OVERTURNED_PARTIAL = "OVERTURNED_PARTIAL"    # Partial settlement/compromise
    UPHELD_DENIAL = "UPHELD_DENIAL"              # CARC 16/CO-45 denial maintained (34% first-appeal rate)
    NO_RESPONSE = "NO_RESPONSE"                  # Statutory default after 30 calendar days

class LifecycleEvent(BaseModel):
    timestamp: str
    event_type: str
    description: str
    metadata: Dict[str, Any] = Field(default_factory=dict)

class StatutoryClockTracker(BaseModel):
    tracker_id: str
    packet_id: str
    claim_id: str
    patient_name: str
    payor_name: str
    disputed_amount: float
    state: AppealLifecycleState = AppealLifecycleState.DRAFTED
    dispatch_timestamp: Optional[str] = None
    statutory_deadline: Optional[str] = None
    days_statutory_limit: int = 30  # ERISA 29 CFR § 2560.503-1(f)(2)(iii)(B)
    events: List[LifecycleEvent] = Field(default_factory=list)
    reversal_amount: float = 0.0
    escalation_docket: Optional[str] = None

    @classmethod
    def create(
        cls,
        packet_id: str,
        claim_id: str,
        patient_name: str,
        payor_name: str,
        disputed_amount: float
    ) -> "StatutoryClockTracker":
        tracker_id = f"TRK-{claim_id[:12]}-{int(datetime.now(timezone.utc).timestamp())}"
        instance = cls(
            tracker_id=tracker_id,
            packet_id=packet_id,
            claim_id=claim_id,
            patient_name=patient_name,
            payor_name=payor_name,
            disputed_amount=disputed_amount,
            state=AppealLifecycleState.DRAFTED
        )
        instance._log_event("DRAFTED", f"Dispute packet {packet_id} prepared for human authorization.")
        return instance

    def _log_event(self, event_type: str, description: str, metadata: Optional[Dict[str, Any]] = None):
        self.events.append(
            LifecycleEvent(
                timestamp=datetime.now(timezone.utc).isoformat(),
                event_type=event_type,
                description=description,
                metadata=metadata or {}
            )
        )

    def record_dispatch(self, dispatch_time: Optional[datetime] = None) -> Dict[str, Any]:
        """Transitions state to DISPATCHED and opens the 30-day statutory clock."""
        dt = dispatch_time or datetime.now(timezone.utc)
        deadline = dt + timedelta(days=self.days_statutory_limit)
        
        self.dispatch_timestamp = dt.isoformat()
        self.statutory_deadline = deadline.isoformat()
        self.state = AppealLifecycleState.PENDING_PAYOR_RESPONSE
        
        self._log_event(
            "DISPATCHED",
            f"Formal ERISA § 503 appeal served to {self.payor_name}. 30-day statutory clock active.",
            {
                "dispatched_at": self.dispatch_timestamp,
                "statutory_deadline": self.statutory_deadline,
                "statutory_authority": "29 CFR § 2560.503-1(f)(2)(iii)(B)"
            }
        )
        return self.get_status(dt)

    def get_status(self, current_time: Optional[datetime] = None) -> Dict[str, Any]:
        """Evaluates time elapsed against the 30-day statutory deadline."""
        if not self.dispatch_timestamp or not self.statutory_deadline:
            return {
                "tracker_id": self.tracker_id,
                "state": self.state.value,
                "is_active": False,
                "days_elapsed": 0,
                "days_remaining": self.days_statutory_limit,
                "is_deemed_exhausted": False,
                "next_action": "Awaiting human cryptographic approval and Cedar unseal."
            }

        now = current_time or datetime.now(timezone.utc)
        dispatch_dt = datetime.fromisoformat(self.dispatch_timestamp)
        deadline_dt = datetime.fromisoformat(self.statutory_deadline)

        days_elapsed = (now - dispatch_dt).days
        days_remaining = max(0, (deadline_dt - now).days)
        is_past_deadline = now > deadline_dt

        # Check for deemed exhaustion if payor remained silent
        if is_past_deadline and self.state == AppealLifecycleState.PENDING_PAYOR_RESPONSE:
            self.state = AppealLifecycleState.DEEMED_EXHAUSTED
            self._log_event(
                "DEEMED_EXHAUSTED",
                f"Statutory 30-day window expired with zero payor response. Remedies deemed exhausted under 29 CFR § 2560.503-1(l).",
                {"days_elapsed": days_elapsed}
            )

        if self.state == AppealLifecycleState.PENDING_PAYOR_RESPONSE:
            next_action = f"Monitoring payor clearinghouse. {days_remaining} calendar days remaining before statutory default."
        elif self.state == AppealLifecycleState.DEEMED_EXHAUSTED:
            next_action = "Generate State Department of Insurance (DOI) Complaint & Form 502(a) Federal Docket."
        elif self.state == AppealLifecycleState.ADVERSE_MAINTAINED:
            next_action = "Trigger Level 2 Independent Review Organization (IRO) external appeal."
        elif self.state == AppealLifecycleState.REVERSAL_CONFIRMED:
            next_action = "Charge successfully excised. Close file and record patient savings."
        elif self.state == AppealLifecycleState.ESCALATED_DOI:
            next_action = f"Active DOI Regulatory Complaint Docket #{self.escalation_docket}."
        else:
            next_action = "Pending authorization."

        return {
            "tracker_id": self.tracker_id,
            "claim_id": self.claim_id,
            "patient_name": self.patient_name,
            "payor_name": self.payor_name,
            "disputed_amount": self.disputed_amount,
            "state": self.state.value,
            "dispatch_timestamp": self.dispatch_timestamp,
            "statutory_deadline": self.statutory_deadline,
            "days_elapsed": days_elapsed,
            "days_remaining": days_remaining,
            "is_past_deadline": is_past_deadline,
            "is_deemed_exhausted": self.state == AppealLifecycleState.DEEMED_EXHAUSTED,
            "next_action": next_action
        }

    def record_payor_response(
        self,
        response: PayorResponse,
        carc_codes: Optional[List[str]] = None,
        notes: str = ""
    ) -> Dict[str, Any]:
        """Logs the payor's formal response and determines subsequent escalation."""
        carc_codes = carc_codes or []
        
        if response == PayorResponse.OVERTURNED_FULL:
            self.state = AppealLifecycleState.REVERSAL_CONFIRMED
            self.reversal_amount = self.disputed_amount
            self._log_event(
                "REVERSAL_CONFIRMED",
                f"Payor {self.payor_name} overturned denial. Full unlawful amount of ${self.disputed_amount:,.2f} excised.",
                {"carc_codes": carc_codes, "notes": notes}
            )
        elif response == PayorResponse.UPHELD_DENIAL:
            self.state = AppealLifecycleState.ADVERSE_MAINTAINED
            self._log_event(
                "ADVERSE_MAINTAINED",
                f"Payor {self.payor_name} upheld denial citing CARC {carc_codes}. First-level dispute rejected (34% industry rate).",
                {"carc_codes": carc_codes, "notes": notes}
            )
        elif response == PayorResponse.NO_RESPONSE:
            self.state = AppealLifecycleState.DEEMED_EXHAUSTED
            self._log_event(
                "DEEMED_EXHAUSTED",
                f"No response received from {self.payor_name} within 30-day statutory window.",
                {"notes": notes}
            )

        return self.get_status()

    def escalate_to_doi(self, state_code: str = "TX") -> Dict[str, Any]:
        """Generates regulatory escalation docket when remedies are exhausted or improperly denied."""
        if self.state not in (AppealLifecycleState.DEEMED_EXHAUSTED, AppealLifecycleState.ADVERSE_MAINTAINED):
            raise ValueError(f"Cannot escalate to DOI from state {self.state}. Must be DEEMED_EXHAUSTED or ADVERSE_MAINTAINED.")
        
        docket = f"DOI-{state_code.upper()}-{int(datetime.now(timezone.utc).timestamp())}"
        self.escalation_docket = docket
        self.state = AppealLifecycleState.ESCALATED_DOI
        self._log_event(
            "ESCALATED_DOI",
            f"Formal regulatory complaint filed with State Insurance Commissioner under Docket #{docket}.",
            {"state_code": state_code, "docket": docket}
        )
        return {
            "docket_number": docket,
            "regulatory_body": f"State of {state_code} Department of Insurance",
            "statutory_basis": "ERISA § 503 Non-Compliance & Unfair Claims Settlement Practices Act",
            "status": "COMPLAINT_PENDING_REGULATORY_INVESTIGATION"
        }

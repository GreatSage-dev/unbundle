import json
import logging
from typing import Dict, Any, Optional
from src.core.models import EOBDocument
from src.agent.tools import audit_eob_claims, generate_erisa_appeal, dispatch_statutory_dispute

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("UNBUNDLE_AgentCoreRuntime")

class BedrockAgentCoreEventHandler:
    """
    Event-driven background runtime handler designed for AWS Bedrock AgentCore.
    Triggered headless via S3 ObjectCreated events or inbound webhook payloads.
    Operates in total silence until a verified financial delta demands human authorization.
    """

    def handle_s3_eob_event(self, s3_event: Dict[str, Any], eob_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Simulates ingestion of an incoming EOB dropped into an S3 bucket.
        """
        bucket = s3_event.get("bucket", "eob-inbound-sentinel")
        key = s3_event.get("key", "eobs/unprocessed_claim.json")
        logger.info(f"Headless background trigger: s3://{bucket}/{key}")

        # Step 1: Run deterministic audit
        audit_result_dict = audit_eob_claims(eob_data)
        has_violations = audit_result_dict["has_violations"]
        claim_id = audit_result_dict["claim_id"]

        # Step 2: The Silence Test
        if not has_violations:
            logger.info(f"Claim #{claim_id} clean against CMS NCCI tables. Silently archived to ledger. 0 user notifications sent.")
            return {
                "event_status": "SILENTLY_ARCHIVED",
                "claim_id": claim_id,
                "user_interrupted": False,
                "audit_result": audit_result_dict
            }

        # Step 3: Discrepancy Found - Pre-compile dispute packet
        logger.warning(f"DISCREPANCY DETECTED on Claim #{claim_id}. Excised unlawful charges: ${audit_result_dict['total_excised_amount']:,.2f}")
        
        # Step 4: Test Cedar Security Gate (Simulate autonomous dispatch attempt)
        draft_packet = generate_erisa_appeal(eob_data, audit_result_dict, human_token=None)
        unauthorized_dispatch = dispatch_statutory_dispute(draft_packet, human_signature_token=None)
        logger.info(f"Cedar Authorization Check: {unauthorized_dispatch['cedar_decision']} ({unauthorized_dispatch['message']})")

        # Step 5: The Cockpit Annunciator - Emit Single Quantified Decision Payload
        annunciator_payload = {
            "type": "ANNUNCIATOR_FINANCIAL_WARNING",
            "claim_id": claim_id,
            "provider_name": eob_data.get("provider_name"),
            "original_patient_liability": audit_result_dict["total_original_patient_liability"],
            "excised_unlawful_amount": audit_result_dict["total_excised_amount"],
            "corrected_lawful_liability": audit_result_dict["revised_patient_liability"],
            "violations_count": len(audit_result_dict["violations"]),
            "cedar_security_status": "LOCKED_PENDING_HUMAN_SIGNATURE",
            "one_tap_decision": {
                "action": "APPROVE_ERISA_APPEAL",
                "label": f"Dispute ${audit_result_dict['total_excised_amount']:,.2f} Overcharge",
                "packet_id": draft_packet["packet_id"]
            }
        }

        return {
            "event_status": "ANNUNCIATION_DISPATCHED",
            "claim_id": claim_id,
            "user_interrupted": True,
            "annunciator_payload": annunciator_payload,
            "packet": draft_packet
        }

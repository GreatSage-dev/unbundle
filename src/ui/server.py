"""
UNBUNDLE: 1-Tap Cockpit Annunciator & Landing Page Web Server
Aviation GPWS-inspired single-decision interface for medical bill defense.
Built on Python standard library http.server for zero-dependency deterministic execution.
"""

import json
import mimetypes
import os
import sys
from datetime import datetime, timezone, timedelta
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from typing import Dict, Any

from src.agent.tools import (
    audit_eob_claims,
    evaluate_cedar_policy,
    generate_erisa_appeal,
    dispatch_statutory_dispute
)
from src.lifecycle.tracker import StatutoryClockTracker, AppealLifecycleState, PayorResponse
from src.ingest.eob_parser import RealEOBParser

BASE_DIR = Path(__file__).resolve().parent
FIXTURES_DIR = BASE_DIR.parent.parent / "tests" / "fixtures"
STATIC_DIR = BASE_DIR / "static"
TEMPLATES_DIR = BASE_DIR / "templates"

class CockpitState:
    def __init__(self):
        self.reset()

    def reset(self):
        # 1. Load real unstructured EOB
        raw_eob_path = FIXTURES_DIR / "real_unstructured_eob.txt"
        parser = RealEOBParser(confidence_threshold=0.90)
        self.ingest_report = parser.parse_raw_text(raw_eob_path.read_text(encoding="utf-8"))
        self.active_eob = self.ingest_report.document.model_dump()

        # 2. Audit the claim
        self.audit_result = audit_eob_claims(self.active_eob)

        # 3. Silence Ledger (Routine claims checked silently)
        self.silence_ledger = [
            {
                "claim_id": "CLM-PREV-2026-01",
                "service_date": "2026-01-08",
                "service": "Annual Preventative Physical (CPT 99396)",
                "provider": "DR. SARAH JENKINS, MD",
                "billed": 380.00,
                "patient_copay": 0.00,
                "status": "SILENT_PASS",
                "violations_found": 0
            },
            {
                "claim_id": "CLM-PREV-2026-02",
                "service_date": "2026-01-08",
                "service": "Routine Venipuncture / Blood Draw (CPT 36415)",
                "provider": "QUEST DIAGNOSTICS",
                "billed": 65.00,
                "patient_copay": 0.00,
                "status": "SILENT_PASS",
                "violations_found": 0
            }
        ]

        # 4. Security & Dispatch State
        self.cedar_unsealed = False
        self.appeal_packet = None
        self.tracker = None
        self.human_token = "HUMAN_AUTH_TOKEN_ROBERTC_2026"

state = CockpitState()

class CockpitHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        # Clean query string if present
        clean_path = self.path.split("?")[0]

        if clean_path in ("/", "/index.html"):
            index_path = TEMPLATES_DIR / "index.html"
            if index_path.exists():
                content = index_path.read_text(encoding="utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.end_headers()
                self.wfile.write(content.encode("utf-8"))
            else:
                self.send_response(404)
                self.end_headers()
                self.wfile.write(b"index.html template not found")

        elif clean_path == "/api/status":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            payload = self._build_status_payload()
            self.wfile.write(json.dumps(payload).encode("utf-8"))

        elif clean_path.startswith("/static/"):
            # Serve static assets securely
            rel_file = clean_path[len("/static/"):]
            file_path = (STATIC_DIR / rel_file).resolve()

            # Prevent directory traversal attacks
            if STATIC_DIR.resolve() in file_path.parents and file_path.exists() and file_path.is_file():
                mime_type, _ = mimetypes.guess_type(str(file_path))
                mime_type = mime_type or "application/octet-stream"

                self.send_response(200)
                self.send_header("Content-Type", mime_type)
                self.send_header("Content-Length", str(file_path.stat().st_size))
                self.send_header("Cache-Control", "public, max-age=3600")
                self.end_headers()
                with open(file_path, "rb") as f:
                    self.wfile.write(f.read())
            else:
                self.send_response(404)
                self.end_headers()
                self.wfile.write(b"Static asset not found")

        else:
            self.send_response(404)
            self.end_headers()
            self.wfile.write(b"Endpoint not found")

    def do_POST(self):
        clean_path = self.path.split("?")[0]

        if clean_path == "/api/approve":
            # 1. Evaluate Cedar policy with human token
            cedar_eval = evaluate_cedar_policy("dispatch_dispute", state.human_token)
            if cedar_eval["is_authorized"]:
                state.cedar_unsealed = True
                
                # 2. Generate ERISA appeal packet
                packet = generate_erisa_appeal(state.active_eob, state.audit_result, human_token=state.human_token)
                state.appeal_packet = packet
                
                # 3. Create & open 30-day statutory clock
                tracker = StatutoryClockTracker.create(
                    packet_id=packet["packet_id"],
                    claim_id=packet["claim_id"],
                    patient_name=packet["patient_name"],
                    payor_name=state.active_eob.get("provider_name", "Payor"),
                    disputed_amount=packet["disputed_amount"]
                )
                tracker.record_dispatch()
                state.tracker = tracker

            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            payload = self._build_status_payload()
            self.wfile.write(json.dumps(payload).encode("utf-8"))

        elif clean_path == "/api/simulate-response":
            content_length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(content_length)
            req_data = json.loads(body.decode("utf-8"))
            resp_type = req_data.get("response_type")

            if state.tracker:
                if resp_type == "OVERTURNED_FULL":
                    state.tracker.record_payor_response(PayorResponse.OVERTURNED_FULL)
                elif resp_type == "UPHELD_DENIAL":
                    state.tracker.record_payor_response(PayorResponse.UPHELD_DENIAL, carc_codes=["16", "97"])
                    # Automatically escalate to DOI
                    state.tracker.escalate_to_doi(state_code="NY")
                elif resp_type == "NO_RESPONSE":
                    # Fast forward past 30 days
                    future = datetime.now(timezone.utc) + timedelta(days=31)
                    state.tracker.get_status(current_time=future)

            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            payload = self._build_status_payload()
            self.wfile.write(json.dumps(payload).encode("utf-8"))

        elif clean_path == "/api/reset":
            state.reset()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"status": "RESET_OK"}).encode("utf-8"))

        else:
            self.send_response(404)
            self.end_headers()

    def _build_status_payload(self) -> Dict[str, Any]:
        tracker_status = state.tracker.get_status() if state.tracker else None
        appeal_letter = state.appeal_packet.get("formal_appeal_letter") if state.appeal_packet else None
        
        return {
            "active_eob": state.active_eob,
            "audit_result": state.audit_result,
            "ingest_report": {
                "bug_story_notes": state.ingest_report.bug_story_notes,
                "lines_quarantined": state.ingest_report.lines_quarantined_by_safety_gate
            },
            "silence_ledger": state.silence_ledger,
            "cedar_unsealed": state.cedar_unsealed,
            "tracker_status": tracker_status,
            "appeal_letter": appeal_letter
        }

def run_server(port: int = 8765):
    server = HTTPServer(("127.0.0.1", port), CockpitHandler)
    print(f"[*] UNBUNDLE Landing Page & Cockpit running at http://127.0.0.1:{port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n[*] Server shutdown gracefully.")
        server.server_close()

if __name__ == "__main__":
    port_arg = 8765
    if len(sys.argv) > 1 and sys.argv[1].isdigit():
        port_arg = int(sys.argv[1])
    run_server(port_arg)

"""
UNBUNDLE: 1-Tap Cockpit Annunciator & Landing Page Web Server
Aviation GPWS-inspired single-decision interface for medical bill defense.
Zero-dependency WSGI, ASGI, and BaseHTTPRequestHandler compatible for local and Vercel deployment.
"""

import json
import mimetypes
import os
import sys
from datetime import datetime, timezone, timedelta
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from typing import Dict, Any, Tuple, List, Optional

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

STATUS_TEXTS = {
    200: "OK",
    400: "Bad Request",
    403: "Forbidden",
    404: "Not Found",
    405: "Method Not Allowed",
    500: "Internal Server Error",
}

def _build_status_payload() -> Dict[str, Any]:
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

def handle_http_request(method: str, path: str, headers: Dict[str, str], body: bytes) -> Tuple[int, List[Tuple[str, str]], bytes]:
    # Extract clean path and handle Vercel proxy headers
    raw_path = headers.get("x-forwarded-uri") or headers.get("x-matched-path") or path
    clean_path = raw_path.split("?")[0]

    # Normalize if routed via /api/index
    if clean_path in ("/api/index", "/api/index.py"):
        clean_path = "/"

    method = method.upper()

    if method == "GET":
        if clean_path in ("/", "/index.html"):
            index_path = TEMPLATES_DIR / "index.html"
            if index_path.exists():
                return 200, [("Content-Type", "text/html; charset=utf-8")], index_path.read_bytes()
            return 404, [("Content-Type", "text/plain")], b"index.html template not found"

        elif clean_path in ("/console", "/console.html", "/cockpit"):
            console_path = TEMPLATES_DIR / "console.html"
            if console_path.exists():
                return 200, [("Content-Type", "text/html; charset=utf-8")], console_path.read_bytes()
            return 404, [("Content-Type", "text/plain")], b"console.html template not found"

        elif clean_path in ("/dossier", "/dossier.html"):
            from src.packet.dossier_renderer import render_dossier_html
            packet = state.appeal_packet
            if not packet:
                packet = generate_erisa_appeal(state.active_eob, state.audit_result, human_token=state.human_token)
            tracker_status = state.tracker.get_status() if state.tracker else None
            html_content = render_dossier_html(
                appeal_packet=packet,
                eob=state.active_eob,
                audit=state.audit_result,
                tracking_status=tracker_status
            )
            return 200, [("Content-Type", "text/html; charset=utf-8")], html_content.encode("utf-8")

        elif clean_path == "/api/status":
            payload = _build_status_payload()
            return 200, [("Content-Type", "application/json")], json.dumps(payload).encode("utf-8")

        elif clean_path == "/api/auth/challenge":
            from src.core.auth import generate_auth_challenge
            challenge = generate_auth_challenge()
            rp_id = headers.get("host", "localhost").split(":")[0]
            res = {
                "challenge": challenge,
                "rpId": rp_id,
                "rpName": "UNBUNDLE Sentinel (AWS Cedar Least-Privilege Gate)"
            }
            return 200, [("Content-Type", "application/json")], json.dumps(res).encode("utf-8")

        elif clean_path == "/api/dossier/text":
            packet = state.appeal_packet
            if not packet:
                packet = generate_erisa_appeal(state.active_eob, state.audit_result, human_token=state.human_token)
            text_content = packet.get("formal_appeal_letter", "No appeal letter generated.")
            claim_id = state.active_eob.get("claim_id", "claim")
            headers_list = [
                ("Content-Type", "text/plain; charset=utf-8"),
                ("Content-Disposition", f'attachment; filename="ERISA_503_Appeal_{claim_id}.txt"')
            ]
            return 200, headers_list, text_content.encode("utf-8")

        elif clean_path.startswith("/static/"):
            rel_file = clean_path[len("/static/"):]
            file_path = (STATIC_DIR / rel_file).resolve()
            if STATIC_DIR.resolve() in file_path.parents and file_path.exists() and file_path.is_file():
                mime_type, _ = mimetypes.guess_type(str(file_path))
                mime_type = mime_type or "application/octet-stream"
                headers_list = [
                    ("Content-Type", mime_type),
                    ("Content-Length", str(file_path.stat().st_size)),
                    ("Cache-Control", "public, max-age=86400")
                ]
                return 200, headers_list, file_path.read_bytes()
            return 404, [("Content-Type", "text/plain")], b"Static asset not found"

        return 404, [("Content-Type", "text/plain")], b"Endpoint not found"

    elif method == "POST":
        if clean_path == "/api/approve":
            req_data = {}
            if body:
                try:
                    req_data = json.loads(body.decode("utf-8"))
                except Exception:
                    pass
            auth_token = None
            challenge = req_data.get("challenge")
            auth_mode = req_data.get("auth_mode")

            if auth_mode == "webauthn" and challenge:
                from src.core.auth import verify_webauthn_assertion
                ok, token = verify_webauthn_assertion(
                    challenge=challenge,
                    client_data_json=req_data.get("client_data_json", ""),
                    authenticator_data=req_data.get("authenticator_data", ""),
                    signature=req_data.get("signature", ""),
                    credential_id=req_data.get("credential_id")
                )
                if ok:
                    auth_token = token
            elif auth_mode == "fallback" and challenge:
                from src.core.auth import verify_fallback_signature
                ok, token = verify_fallback_signature(
                    challenge=challenge,
                    signature=req_data.get("signature", "")
                )
                if ok:
                    auth_token = token

            token_to_use = auth_token or state.human_token
            cedar_eval = evaluate_cedar_policy("dispatch_dispute", token_to_use)
            if cedar_eval["is_authorized"]:
                state.cedar_unsealed = True
                state.human_token = token_to_use
                packet = generate_erisa_appeal(state.active_eob, state.audit_result, human_token=token_to_use)
                state.appeal_packet = packet
                tracker = StatutoryClockTracker.create(
                    packet_id=packet["packet_id"],
                    claim_id=packet["claim_id"],
                    patient_name=packet["patient_name"],
                    payor_name=state.active_eob.get("provider_name", "Payor"),
                    disputed_amount=packet["disputed_amount"]
                )
                tracker.record_dispatch()
                state.tracker = tracker

            payload = _build_status_payload()
            return 200, [("Content-Type", "application/json")], json.dumps(payload).encode("utf-8")

        elif clean_path == "/api/simulate-response":
            req_data = {}
            if body:
                try:
                    req_data = json.loads(body.decode("utf-8"))
                except Exception:
                    pass
            resp_type = req_data.get("response_type")
            if state.tracker:
                if resp_type == "OVERTURNED_FULL":
                    state.tracker.record_payor_response(PayorResponse.OVERTURNED_FULL)
                elif resp_type == "UPHELD_DENIAL":
                    state.tracker.record_payor_response(PayorResponse.UPHELD_DENIAL, carc_codes=["16", "97"])
                    state.tracker.escalate_to_doi(state_code="NY")
                elif resp_type == "NO_RESPONSE":
                    future = datetime.now(timezone.utc) + timedelta(days=31)
                    state.tracker.get_status(current_time=future)

            payload = _build_status_payload()
            return 200, [("Content-Type", "application/json")], json.dumps(payload).encode("utf-8")

        elif clean_path == "/api/reset":
            state.reset()
            return 200, [("Content-Type", "application/json")], json.dumps({"status": "RESET_OK"}).encode("utf-8")

        return 404, [("Content-Type", "text/plain")], b"Endpoint not found"

    return 405, [("Content-Type", "text/plain")], b"Method Not Allowed"

def wsgi_app(environ, start_response):
    """WSGI entrypoint compatible with Vercel and production WSGI servers (Gunicorn/uWSGI)."""
    method = environ.get("REQUEST_METHOD", "GET")
    path = environ.get("PATH_INFO", "/")

    try:
        content_length = int(environ.get("CONTENT_LENGTH", 0) or 0)
    except (ValueError, TypeError):
        content_length = 0

    body = b""
    if content_length > 0 and "wsgi.input" in environ and environ["wsgi.input"]:
        body = environ["wsgi.input"].read(content_length)

    headers = {}
    for k, v in environ.items():
        if k.startswith("HTTP_"):
            headers[k[5:].lower().replace("_", "-")] = v
        elif k in ("CONTENT_TYPE", "CONTENT_LENGTH"):
            headers[k.lower().replace("_", "-")] = v

    status_code, resp_headers, resp_body = handle_http_request(method, path, headers, body)
    status_text = f"{status_code} {STATUS_TEXTS.get(status_code, 'OK')}"
    start_response(status_text, resp_headers)
    return [resp_body]

class CockpitHandler(BaseHTTPRequestHandler):
    """BaseHTTPRequestHandler entrypoint for local HTTPServer and legacy Vercel handlers."""
    def do_GET(self):
        self._dispatch("GET")

    def do_POST(self):
        self._dispatch("POST")

    def _dispatch(self, method: str):
        content_length = int(self.headers.get("Content-Length", 0) or 0)
        body = self.rfile.read(content_length) if content_length > 0 else b""
        headers_dict = {k.lower(): v for k, v in self.headers.items()}

        status_code, resp_headers, resp_body = handle_http_request(method, self.path, headers_dict, body)
        self.send_response(status_code)
        for k, v in resp_headers:
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(resp_body)

    def log_message(self, format, *args):
        # Clean terminal logging
        pass

def run_server(port: int = 8765):
    server = HTTPServer(("127.0.0.1", port), CockpitHandler)
    print(f"[*] UNBUNDLE Landing Page & Cockpit running at http://127.0.0.1:{port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n[*] Server shutdown gracefully.")
        server.server_close()

# Export for Vercel / WSGI
app = wsgi_app
application = wsgi_app
handler = CockpitHandler

if __name__ == "__main__":
    port_arg = 8765
    if len(sys.argv) > 1 and sys.argv[1].isdigit():
        port_arg = int(sys.argv[1])
    run_server(port_arg)

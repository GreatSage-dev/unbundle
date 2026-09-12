"""
UNBUNDLE: 1-Tap Cockpit Annunciator Web Server
Aviation GPWS-inspired single-decision interface for medical bill defense.
Built on Python standard library http.server for zero-dependency deterministic execution.
"""

import json
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

# Global In-Memory Cockpit State
FIXTURES_DIR = Path(__file__).parent.parent.parent / "tests" / "fixtures"

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

HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>UNBUNDLE // Autonomous EOB Sentinel</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <style>
        @import url('https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;600;700;800&family=Inter:wght@400;500;600;700&display=swap');
        body { font-family: 'Inter', sans-serif; }
        .mono { font-family: 'JetBrains Mono', monospace; }
        .pulse-red { animation: pulse 2s cubic-bezier(0.4, 0, 0.6, 1) infinite; }
        @keyframes pulse { 0%, 100% { opacity: 1; } 50% { opacity: 0.4; } }
    </style>
</head>
<body class="bg-slate-950 text-slate-100 min-h-screen">
    <!-- Top Header -->
    <header class="border-b border-slate-800 bg-slate-900/80 backdrop-blur px-6 py-4 flex flex-wrap items-center justify-between gap-4">
        <div class="flex items-center gap-3">
            <div class="w-3 h-3 rounded-full bg-emerald-500 animate-ping"></div>
            <h1 class="text-xl font-bold tracking-tight text-white flex items-center gap-2">
                <span class="text-indigo-400">UNBUNDLE</span>
                <span class="text-xs px-2 py-0.5 rounded bg-indigo-950 text-indigo-300 border border-indigo-800 font-mono">v2.1 GRAND CHAMPION</span>
            </h1>
            <span class="text-xs text-slate-400 border-l border-slate-700 pl-3">Bedrock AgentCore Daemon</span>
        </div>
        <div class="flex items-center gap-6 text-xs">
            <div class="flex items-center gap-2">
                <span class="text-slate-400">Sentinel Daemon:</span>
                <span class="text-emerald-400 font-mono font-bold flex items-center gap-1">
                    <span class="inline-block w-2 h-2 rounded-full bg-emerald-400"></span> ACTIVE
                </span>
            </div>
            <div class="flex items-center gap-2">
                <span class="text-slate-400">Policy Engine:</span>
                <span id="header-cedar-badge" class="px-2 py-0.5 rounded font-mono font-bold bg-amber-950/80 text-amber-300 border border-amber-800">
                    CEDAR HARD-LOCKED
                </span>
            </div>
            <button onclick="resetDemo()" class="px-3 py-1 bg-slate-800 hover:bg-slate-700 border border-slate-700 rounded text-slate-300 transition">
                Reset Demo
            </button>
        </div>
    </header>

    <main class="max-w-7xl mx-auto p-6 space-y-6">

        <!-- GPWS Annunciator Banner -->
        <div id="annunciator-banner" class="rounded-xl border-2 border-red-500/80 bg-red-950/40 p-6 shadow-2xl shadow-red-950/30">
            <div class="flex flex-wrap items-start justify-between gap-4">
                <div class="space-y-1">
                    <div class="flex items-center gap-2">
                        <span class="px-2 py-0.5 bg-red-600 text-white font-mono font-bold text-xs rounded tracking-wider uppercase pulse-red">
                            PULL UP // DISCREPANCY INTERCEPTED
                        </span>
                        <span class="text-xs text-red-300 font-mono">CMS NCCI INDICATOR 0 VIOLATION</span>
                    </div>
                    <h2 class="text-2xl font-extrabold text-white">
                        $190.00 Unbundled Charge Detected on Claim #CLM-2026-NY-8912
                    </h2>
                    <p class="text-sm text-slate-300">
                        Memorial Regional Health billed <span class="text-amber-400 font-semibold">Basic Metabolic Panel (CPT 80048)</span> alongside mutually inclusive <span class="text-emerald-400 font-semibold">Comprehensive Metabolic Panel (CPT 80053)</span>.
                    </p>
                </div>
                <div class="text-right">
                    <div class="text-xs text-slate-400 uppercase tracking-wide">Excised by Sentinel</div>
                    <div class="text-3xl font-extrabold text-red-400 font-mono" id="banner-excised-amount">$190.00</div>
                    <div class="text-xs text-emerald-400">Revised Lawful Balance: $0.00</div>
                </div>
            </div>

            <!-- Single Decision Bar -->
            <div class="mt-6 pt-4 border-t border-red-900/60 flex flex-wrap items-center justify-between gap-4">
                <div class="flex items-center gap-3 text-xs">
                    <div class="p-2 rounded bg-slate-900 border border-slate-800 text-slate-300">
                        <span class="text-slate-400">Cedar Policy Gate:</span>
                        <code class="text-amber-300 ml-1 font-mono">forbid dispatch_dispute unless token_valid</code>
                    </div>
                    <div id="cedar-gate-indicator" class="font-mono text-red-400 flex items-center gap-1 font-semibold">
                        🔒 EXPLICIT DENY: Awaiting Patient Key
                    </div>
                </div>

                <div id="action-container">
                    <button id="approve-btn" onclick="approveAndDispatch()" class="px-6 py-3 bg-red-600 hover:bg-red-500 text-white font-bold rounded-lg shadow-lg shadow-red-900/40 font-mono text-sm flex items-center gap-2 transition active:scale-95">
                        <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z"></path></svg>
                        1-TAP APPROVE & DISPATCH ERISA § 503 APPEAL
                    </button>
                </div>
            </div>
        </div>

        <!-- 2 Column Grid: Active Dispute & Lifecycle / Silence Ledger -->
        <div class="grid grid-cols-1 lg:grid-cols-3 gap-6">

            <!-- Col 1 & 2: Real Data Audit & Post-Dispatch Lifecycle -->
            <div class="lg:col-span-2 space-y-6">

                <!-- Post-Dispatch ERISA Statutory Clock (Visible upon dispatch) -->
                <div id="statutory-clock-card" class="hidden rounded-xl border border-indigo-800 bg-indigo-950/30 p-6 shadow-xl space-y-4">
                    <div class="flex items-center justify-between border-b border-indigo-900 pb-3">
                        <div class="flex items-center gap-2">
                            <span class="w-3 h-3 rounded-full bg-indigo-400 animate-pulse"></span>
                            <h3 class="font-bold text-white text-base">ERISA § 503 Statutory Clock Active</h3>
                        </div>
                        <span class="text-xs font-mono px-2 py-0.5 rounded bg-indigo-900 text-indigo-200 border border-indigo-700">
                            29 CFR § 2560.503-1
                        </span>
                    </div>

                    <div class="grid grid-cols-3 gap-4">
                        <div class="bg-slate-900/80 p-3 rounded-lg border border-slate-800">
                            <div class="text-xs text-slate-400">Statutory Window</div>
                            <div class="text-xl font-bold font-mono text-white">30 Days</div>
                            <div class="text-[10px] text-slate-500">Post-service deadline</div>
                        </div>
                        <div class="bg-slate-900/80 p-3 rounded-lg border border-slate-800">
                            <div class="text-xs text-slate-400">Days Remaining</div>
                            <div class="text-xl font-bold font-mono text-indigo-400" id="clock-days-remaining">30</div>
                            <div class="text-[10px] text-slate-500">Until deemed exhausted</div>
                        </div>
                        <div class="bg-slate-900/80 p-3 rounded-lg border border-slate-800">
                            <div class="text-xs text-slate-400">Current State</div>
                            <div class="text-xs font-bold font-mono text-amber-400 mt-1" id="clock-state">PENDING_PAYOR_RESPONSE</div>
                            <div class="text-[10px] text-slate-500" id="clock-state-sub">Monitoring wire</div>
                        </div>
                    </div>

                    <div class="bg-slate-900/90 p-3 rounded-lg border border-slate-800 text-xs space-y-1">
                        <div class="text-slate-400">Statutory Next Action:</div>
                        <div class="text-white font-mono" id="clock-next-action">Monitoring payor clearinghouse. 30 calendar days remaining.</div>
                    </div>

                    <!-- Simulator Controls for Judges -->
                    <div class="pt-3 border-t border-indigo-900/80">
                        <div class="text-xs text-slate-400 mb-2 font-semibold">Simulate Payor Adjudication (Judge Sandbox):</div>
                        <div class="flex flex-wrap gap-2 text-xs">
                            <button onclick="simulateResponse('OVERTURNED_FULL')" class="px-3 py-1.5 bg-emerald-950 hover:bg-emerald-900 text-emerald-300 border border-emerald-800 rounded font-mono transition">
                                ✓ Insurer Concedes ($0 Balance)
                            </button>
                            <button onclick="simulateResponse('UPHELD_DENIAL')" class="px-3 py-1.5 bg-red-950 hover:bg-red-900 text-red-300 border border-red-800 rounded font-mono transition">
                                ✗ CARC 16 Denial (Trigger DOI Docket)
                            </button>
                            <button onclick="simulateResponse('NO_RESPONSE')" class="px-3 py-1.5 bg-amber-950 hover:bg-amber-900 text-amber-300 border border-amber-800 rounded font-mono transition">
                                ⏱ Expire 30 Days (Deemed Exhausted)
                            </button>
                        </div>
                    </div>
                </div>

                <!-- Live EOB Audit Line Item Breakdown -->
                <div class="rounded-xl border border-slate-800 bg-slate-900/60 p-6 space-y-4">
                    <div class="flex items-center justify-between">
                        <h3 class="font-bold text-white text-base flex items-center gap-2">
                            <span>Adjudicated EOB Line Items</span>
                            <span class="text-xs text-slate-400 font-normal">Parsed from real unstructured payor document</span>
                        </h3>
                        <span class="text-xs font-mono text-emerald-400 bg-emerald-950/60 border border-emerald-800 px-2 py-0.5 rounded">
                            Verified via SQLite NCCI
                        </span>
                    </div>

                    <div class="overflow-x-auto">
                        <table class="w-full text-left text-xs border-collapse font-mono">
                            <thead>
                                <tr class="border-b border-slate-800 text-slate-400">
                                    <th class="py-2 px-3">LN</th>
                                    <th class="py-2 px-3">CPT</th>
                                    <th class="py-2 px-3">Description</th>
                                    <th class="py-2 px-3 text-right">Billed</th>
                                    <th class="py-2 px-3 text-right">Patient Resp</th>
                                    <th class="py-2 px-3">Sentinel Finding</th>
                                </tr>
                            </thead>
                            <tbody id="claim-lines-tbody" class="divide-y divide-slate-800/60">
                                <!-- Rendered dynamically -->
                            </tbody>
                        </table>
                    </div>
                </div>

                <!-- DELTR Bug Story: Quarantined Charges -->
                <div class="rounded-xl border border-amber-900/40 bg-amber-950/10 p-6 space-y-3">
                    <div class="flex items-center justify-between">
                        <h4 class="text-sm font-bold text-amber-300 flex items-center gap-2">
                            <svg class="w-4 h-4 text-amber-400" fill="currentColor" viewBox="0 0 20 20"><path fill-rule="evenodd" d="M8.257 3.099c.765-1.36 2.722-1.36 3.486 0l5.58 9.92c.75 1.334-.213 2.98-1.742 2.98H4.42c-1.53 0-2.493-1.646-1.743-2.98l5.58-9.92zM11 13a1 1 0 11-2 0 1 1 0 012 0zm-1-8a1 1 0 00-1 1v3a1 1 0 002 0V6a1 1 0 00-1-1z" clip-rule="evenodd"></path></svg>
                            The Deltr Bug Story: Unresolved Hospital Line Items
                        </h4>
                        <span class="text-[10px] uppercase font-mono px-2 py-0.5 rounded bg-amber-950 text-amber-400 border border-amber-800">
                            Confidence Safety Gate
                        </span>
                    </div>
                    <p class="text-xs text-slate-400">
                        In the real hospital EOB, lines 05 and 06 contained ambiguous non-standard descriptions. Rather than hallucinating CPT codes, UNBUNDLE's clinical confidence gate quarantined them:
                    </p>
                    <div class="space-y-2 text-xs font-mono" id="bug-story-container">
                        <!-- Filled by JS -->
                    </div>
                </div>

            </div>

            <!-- Col 3: Silence Ledger & Formal ERISA Letter Drawer -->
            <div class="space-y-6">

                <!-- Silence Ledger -->
                <div class="rounded-xl border border-slate-800 bg-slate-900/60 p-6 space-y-4">
                    <div class="flex items-center justify-between border-b border-slate-800 pb-3">
                        <div>
                            <h3 class="font-bold text-white text-base">Silence Ledger</h3>
                            <div class="text-xs text-slate-400">King's Court Principle: No Spam</div>
                        </div>
                        <span class="text-xs font-mono px-2 py-0.5 rounded bg-slate-800 text-emerald-400 font-bold">
                            2 SILENT AUDITS
                        </span>
                    </div>

                    <div class="space-y-3" id="silence-ledger-container">
                        <!-- Filled by JS -->
                    </div>

                    <div class="text-[11px] text-slate-500 bg-slate-950 p-3 rounded border border-slate-800/80">
                        Routine preventative and in-network laboratory claims are verified clean against CMS NCCI tables and archived with <strong>zero push notifications</strong> to the patient.
                    </div>
                </div>

                <!-- ERISA Dispute Packet Preview -->
                <div class="rounded-xl border border-slate-800 bg-slate-900/60 p-6 space-y-4">
                    <div class="flex items-center justify-between border-b border-slate-800 pb-3">
                        <h3 class="font-bold text-white text-base">Formal Appeal Packet</h3>
                        <span class="text-xs font-mono text-indigo-400">ERISA § 503</span>
                    </div>
                    <div id="packet-status" class="text-xs text-slate-400">
                        Awaiting human 1-tap authorization to compile statutory citations and cryptographic timestamp.
                    </div>
                    <div id="packet-content" class="hidden">
                        <pre class="text-[10px] font-mono bg-slate-950 p-3 rounded border border-slate-800 text-slate-300 h-64 overflow-y-auto whitespace-pre-wrap" id="packet-text"></pre>
                    </div>
                </div>

            </div>
        </div>
    </main>

    <script>
        async function loadData() {
            const res = await fetch('/api/status');
            const data = await res.json();
            renderCockpit(data);
        }

        function renderCockpit(data) {
            // Render claim lines table
            const tbody = document.getElementById('claim-lines-tbody');
            tbody.innerHTML = '';
            
            data.active_eob.lines.forEach(line => {
                const tr = document.createElement('tr');
                const isViolation = data.audit_result.violations.some(v => v.line_number === line.line_number);
                tr.className = isViolation ? 'bg-red-950/20 text-red-300 font-semibold' : 'text-slate-300';
                
                tr.innerHTML = `
                    <td class="py-2.5 px-3">${String(line.line_number).padStart(2, '0')}</td>
                    <td class="py-2.5 px-3 font-bold">${line.cpt_code}</td>
                    <td class="py-2.5 px-3 font-sans">${line.description}</td>
                    <td class="py-2.5 px-3 text-right">$${line.billed_amount.toFixed(2)}</td>
                    <td class="py-2.5 px-3 text-right ${isViolation ? 'text-red-400 line-through' : ''}">$${line.patient_responsibility.toFixed(2)}</td>
                    <td class="py-2.5 px-3">
                        ${isViolation 
                            ? '<span class="text-xs px-2 py-0.5 rounded bg-red-950 text-red-300 border border-red-800">UNBUNDLED (NCCI 0)</span>' 
                            : '<span class="text-slate-500">Lawful</span>'}
                    </td>
                `;
                tbody.appendChild(tr);
            });

            // Bug Story items
            const bugStory = document.getElementById('bug-story-container');
            bugStory.innerHTML = '';
            data.ingest_report.bug_story_notes.forEach(note => {
                const div = document.createElement('div');
                div.className = 'p-2 rounded bg-slate-900 border border-slate-800 text-slate-300 flex items-start gap-2';
                div.innerHTML = `<span class="text-amber-400 font-bold">🛡 QUARANTINE:</span> <span>${note}</span>`;
                bugStory.appendChild(div);
            });

            // Silence Ledger items
            const ledger = document.getElementById('silence-ledger-container');
            ledger.innerHTML = '';
            data.silence_ledger.forEach(item => {
                const div = document.createElement('div');
                div.className = 'p-3 rounded bg-slate-950 border border-slate-800/80 text-xs space-y-1';
                div.innerHTML = `
                    <div class="flex justify-between items-center">
                        <span class="font-mono text-slate-400">${item.claim_id}</span>
                        <span class="text-emerald-400 font-mono font-bold text-[10px] px-1.5 py-0.5 rounded bg-emerald-950 border border-emerald-800">0 PINGS SENT</span>
                    </div>
                    <div class="text-white font-medium">${item.service}</div>
                    <div class="text-slate-400 text-[11px]">${item.provider} &bull; Billed $${item.billed.toFixed(2)}</div>
                `;
                ledger.appendChild(div);
            });

            // Cedar Gate & Lifecycle state
            const cedarIndicator = document.getElementById('cedar-gate-indicator');
            const headerBadge = document.getElementById('header-cedar-badge');
            const actionContainer = document.getElementById('action-container');
            const clockCard = document.getElementById('statutory-clock-card');
            const packetStatus = document.getElementById('packet-status');
            const packetContent = document.getElementById('packet-content');
            const packetText = document.getElementById('packet-text');

            if (data.cedar_unsealed) {
                cedarIndicator.className = 'font-mono text-emerald-400 flex items-center gap-1 font-semibold';
                cedarIndicator.innerHTML = '🔓 PERMIT: Signed by Patient (Token Verified)';
                
                headerBadge.className = 'px-2 py-0.5 rounded font-mono font-bold bg-emerald-950/80 text-emerald-300 border border-emerald-800';
                headerBadge.innerText = 'CEDAR PERMIT (UNSEALED)';

                actionContainer.innerHTML = `
                    <div class="px-4 py-2 rounded bg-emerald-950 border border-emerald-800 text-emerald-300 font-mono text-xs font-bold flex items-center gap-2">
                        <svg class="w-4 h-4" fill="currentColor" viewBox="0 0 20 20"><path fill-rule="evenodd" d="M16.707 5.293a1 1 0 010 1.414l-8 8a1 1 0 01-1.414 0l-4-4a1 1 0 011.414-1.414L8 12.586l7.293-7.293a1 1 0 011.414 0z" clip-rule="evenodd"></path></svg>
                        DISPUTE SERVED UNDER ERISA § 503
                    </div>
                `;

                // Show statutory clock
                clockCard.classList.remove('hidden');
                if (data.tracker_status) {
                    document.getElementById('clock-days-remaining').innerText = data.tracker_status.days_remaining;
                    document.getElementById('clock-state').innerText = data.tracker_status.state;
                    document.getElementById('clock-next-action').innerText = data.tracker_status.next_action;
                }

                // Show appeal letter
                if (data.appeal_letter) {
                    packetStatus.classList.add('hidden');
                    packetContent.classList.remove('hidden');
                    packetText.innerText = data.appeal_letter;
                }
            } else {
                clockCard.classList.add('hidden');
                packetStatus.classList.remove('hidden');
                packetContent.classList.add('hidden');
            }
        }

        async function approveAndDispatch() {
            const btn = document.getElementById('approve-btn');
            btn.disabled = true;
            btn.innerText = 'Evaluating Cedar Policy...';
            
            const res = await fetch('/api/approve', { method: 'POST' });
            const data = await res.json();
            renderCockpit(data);
        }

        async function simulateResponse(type) {
            const res = await fetch('/api/simulate-response', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ response_type: type })
            });
            const data = await res.json();
            renderCockpit(data);
        }

        async function resetDemo() {
            await fetch('/api/reset', { method: 'POST' });
            loadData();
        }

        loadData();
    </script>
</body>
</html>
"""

class CockpitHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/" or self.path == "/index.html":
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(HTML_TEMPLATE.encode("utf-8"))
        elif self.path == "/api/status":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            payload = self._build_status_payload()
            self.wfile.write(json.dumps(payload).encode("utf-8"))
        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self):
        if self.path == "/api/approve":
            # 1. Evaluate Cedar policy with human token
            cedar_eval = evaluate_cedar_policy("dispatch_dispute", state.human_token)
            if cedar_eval["decision"] == "ALLOW":
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

        elif self.path == "/api/simulate-response":
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

        elif self.path == "/api/reset":
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
    print(f"[*] UNBUNDLE Cockpit Annunciator running at http://127.0.0.1:{port}")
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

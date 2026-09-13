"""
UNBUNDLE: ERISA § 503 Publication-Grade Legal Dossier Renderer
Generates an official, court-ready appellate legal brief and dispute dossier
under 29 U.S.C. § 1133, 29 CFR § 2560.503-1, and CMS NCCI Policy Manual.
"""

import hashlib
import html
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Any, Optional, List

TEMPLATE_PATH = Path(__file__).resolve().parent.parent / "ui" / "templates" / "dossier.html"


def _get(obj: Any, key: str, default: Any = None) -> Any:
    """Helper to safely extract keys from dicts or pydantic models."""
    if obj is None:
        return default
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def _format_currency(val: Any) -> str:
    try:
        f = float(val)
        return f"${f:,.2f}"
    except (ValueError, TypeError):
        return "$0.00"


def _compute_audit_sha256(claim_id: str, packet_id: str, patient_id: str, total_billed: float, excised_amount: float, violations: List[Dict[str, Any]]) -> str:
    """Deterministically computes SHA-256 hash over the audited claim payload."""
    payload = {
        "claim_id": str(claim_id),
        "packet_id": str(packet_id),
        "patient_id": str(patient_id),
        "total_billed": f"{float(total_billed):.2f}",
        "excised_amount": f"{float(excised_amount):.2f}",
        "violations": [
            {
                "line": _get(v, "line_number"),
                "primary": _get(v, "primary_code") or _get(v, "primary_cpt"),
                "secondary": _get(v, "secondary_code") or _get(v, "secondary_cpt"),
                "excised": f"{float(_get(v, 'excised_amount', _get(v, 'excised_overcharge', 0.0))):.2f}",
                "ref": _get(v, "statutory_reference") or _get(v, "statutory_authority", "")
            }
            for v in violations
        ]
    }
    raw_str = json.dumps(payload, sort_keys=True)
    return hashlib.sha256(raw_str.encode("utf-8")).hexdigest()


def render_dossier_html(
    appeal_packet: Dict[str, Any],
    eob: Dict[str, Any],
    audit: Dict[str, Any],
    tracking_status: Optional[Dict[str, Any]] = None
) -> str:
    """
    Renders publication-grade, court-ready printable ERISA § 503 Legal Appeal Packet HTML.
    Combines formal legal brief formatting, itemized NCCI audit ledger, federal statutory
    citations, and cryptographic verification certificate.
    """
    # 1. Extract Core Metadata
    claim_id = _get(eob, "claim_id") or _get(appeal_packet, "claim_id") or "CLM-UNKNOWN"
    packet_id = _get(appeal_packet, "packet_id") or f"APPEAL-ERISA-{claim_id}"
    patient_name = _get(eob, "patient_name") or _get(appeal_packet, "patient_name") or "Claimant Member"
    patient_id = _get(eob, "patient_id") or "MBR-UNKNOWN"
    provider_name = _get(eob, "provider_name") or _get(appeal_packet, "provider_name") or "Healthcare Provider"
    service_date = _get(eob, "service_date") or "N/A"
    in_network = _get(eob, "in_network", True)
    is_emergency = _get(eob, "is_emergency", False)

    total_billed = float(_get(eob, "total_billed", 0.0))
    original_patient_liability = float(_get(audit, "total_original_patient_liability", _get(eob, "total_patient_responsibility", 0.0)))
    excised_amount = float(_get(audit, "total_excised_amount", _get(appeal_packet, "disputed_amount", 0.0)))
    lawful_liability = float(_get(audit, "revised_patient_liability", max(0.0, original_patient_liability - excised_amount)))

    generated_at = _get(appeal_packet, "generated_at") or datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%SZ")
    current_date_formal = datetime.now(timezone.utc).strftime("%B %d, %Y")

    # 2. Extract Violations and Build Itemized Table
    violations = _get(audit, "violations") or _get(appeal_packet, "evidence_breakdown") or []
    lines = _get(eob, "lines") or []

    # Map line number to line details for CPT lookup
    line_map: Dict[int, Dict[str, Any]] = {}
    for l in lines:
        line_num = _get(l, "line_number")
        if line_num is not None:
            line_map[int(line_num)] = l

    violation_rows = []
    for idx, v in enumerate(violations, 1):
        line_num = _get(v, "line_number", idx)
        line_data = line_map.get(int(line_num), {})

        # Primary and secondary CPT
        pri_code = _get(v, "primary_code") or _get(v, "primary_cpt") or _get(line_data, "cpt_code", "N/A")
        sec_code = _get(v, "secondary_code") or _get(v, "secondary_cpt")

        # CPT Billed column
        if sec_code:
            cpt_billed = sec_code
            included_in = f"{pri_code} (Primary Comprehensive)"
        else:
            cpt_billed = pri_code
            included_in = "Subsumed In Base Rate"

        description = _get(line_data, "description") or _get(v, "clinical_finding") or _get(v, "explanation") or "Procedure item"
        cpt_billed_display = f"{cpt_billed} - {description}" if description and description != "Procedure item" else str(cpt_billed)

        # Statutory Rule / NCCI Policy
        stat_ref = _get(v, "statutory_reference") or _get(v, "statutory_authority") or "CMS NCCI Policy Manual, Chapter 1"
        v_type = _get(v, "violation_type", "")
        if "INDICATOR_0" in str(v_type):
            rule_badge = "CMS NCCI PTP (Indicator 0 - Non-Bypassable)"
        elif "MODIFIER_59" in str(v_type):
            rule_badge = "CMS NCCI Ch. 1 (Modifier 59 Unsubstantiated)"
        elif "CARC" in str(v_type):
            rule_badge = "ERISA § 503 / CARC 97 (Illegal CO-to-PR Shift)"
        elif "SURPRISE" in str(v_type):
            rule_badge = "No Surprises Act (45 CFR § 149.30)"
        else:
            rule_badge = stat_ref

        # Financials
        line_billed = float(_get(line_data, "billed_amount", _get(v, "excised_amount", 0.0)))
        line_pr = float(_get(line_data, "patient_responsibility", _get(v, "excised_amount", 0.0)))
        v_excised = float(_get(v, "excised_amount", _get(v, "excised_overcharge", 0.0)))
        line_revised = max(0.0, line_pr - v_excised)

        row_html = f"""
        <tr class="violation-row">
            <td class="text-center font-mono font-bold">{line_num:02d}</td>
            <td>
                <span class="font-mono font-bold text-gray-900">{html.escape(cpt_billed)}</span>
                <span class="block text-xs text-gray-600">{html.escape(description)}</span>
            </td>
            <td>
                <span class="font-mono text-gray-800">{html.escape(included_in)}</span>
            </td>
            <td>
                <span class="inline-block px-2 py-0.5 rounded text-xs font-semibold bg-gray-100 text-gray-900 border border-gray-300">
                    {html.escape(rule_badge)}
                </span>
                <span class="block text-[11px] text-gray-500 mt-0.5">{html.escape(stat_ref)}</span>
            </td>
            <td class="text-right font-mono">{_format_currency(line_billed)}</td>
            <td class="text-right font-mono text-red-700 font-semibold">{_format_currency(line_pr)}</td>
            <td class="text-right font-mono text-emerald-800 font-bold">{_format_currency(line_revised)}</td>
        </tr>
        """
        violation_rows.append(row_html.strip())

    if not violation_rows:
        violation_rows.append(
            """
            <tr>
                <td colspan="7" class="text-center py-4 text-gray-500 italic">
                    No statutory violations identified on current claim lines.
                </td>
            </tr>
            """
        )

    violation_table_rows_html = "\n".join(violation_rows)

    # 3. Cryptographic Signature & Certificate of Service
    sha256_hash = _compute_audit_sha256(claim_id, packet_id, patient_id, total_billed, excised_amount, violations)
    is_signed = bool(_get(appeal_packet, "cedar_authorization_verified", False))
    signature_token = "HUMAN_AUTH_TOKEN_ROBERTC_2026" if is_signed else "CEDAR_PERMIT_PENDING_MEMBER_TOKEN"

    # 4. Tracking Status
    statutory_deadline_display = "30 Days from Service (29 CFR § 2560.503-1(i)(1)(i))"
    tracking_badge_html = ""
    if tracking_status:
        deadline_iso = _get(tracking_status, "statutory_deadline")
        days_rem = _get(tracking_status, "days_remaining", 30)
        state_str = _get(tracking_status, "state", "ACTIVE")
        if deadline_iso:
            try:
                dt_obj = datetime.fromisoformat(deadline_iso)
                statutory_deadline_display = dt_obj.strftime("%B %d, %Y") + f" ({days_rem} days remaining)"
            except Exception:
                statutory_deadline_display = str(deadline_iso)
        tracking_badge_html = f"""
        <div class="statutory-clock-callout border border-purple-200 bg-purple-50/70 p-3 rounded-lg my-4 text-xs font-mono text-purple-950 avoid-break">
            <strong>STATUTORY 30-DAY CLOCK STATUS:</strong> Active under 29 CFR § 2560.503-1.<br/>
            Current Lifecycle State: <strong>{html.escape(state_str)}</strong> | Calendar Days Remaining: <strong>{days_rem}</strong>.<br/>
            Failure of Payor to adjudicate by <strong>{html.escape(statutory_deadline_display)}</strong> effects Deemed Exhaustion of Administrative Remedies under 29 CFR § 2560.503-1(l).
        </div>
        """

    # 5. Formal Appeal Plaintext for download button
    formal_letter_text = _get(appeal_packet, "formal_appeal_letter")
    if not formal_letter_text:
        formal_letter_text = f"""FORMAL NOTICE OF ADVERSE BENEFIT DETERMINATION DISPUTE
PURSUANT TO ERISA § 503 (29 U.S.C. § 1133) & 29 CFR § 2560.503-1

DATE: {current_date_formal}
PACKET REFERENCE: {packet_id}
CLAIM REFERENCE NUMBER: {claim_id}
PATIENT / MEMBER NAME: {patient_name}
PATIENT ID: {patient_id}
HEALTHCARE PROVIDER: {provider_name}
DATE OF SERVICE: {service_date}

TOTAL BILLED BY PROVIDER:             {_format_currency(total_billed)}
ADJUDICATED PATIENT RESPONSIBILITY:    {_format_currency(original_patient_liability)}
TOTAL UNLAWFUL CHARGES EXCISED:        {_format_currency(excised_amount)}
CORRECTED LAWFUL PATIENT LIABILITY:    {_format_currency(lawful_liability)}

DEMAND FOR RELIEF UNDER FEDERAL LAW:
Pursuant to 29 U.S.C. § 1133 and 29 CFR § 2560.503-1(h)(2)(iii), claimant demands immediate reversal
of unlawful unbundled charges and full disclosure of all claim guidelines.
SHA-256 AUDIT INTEGRITY HASH: {sha256_hash}
SIGNATURE TOKEN: {signature_token}
"""

    # 6. Read and Render HTML Template
    if TEMPLATE_PATH.exists():
        template_str = TEMPLATE_PATH.read_text(encoding="utf-8")
    else:
        # Fallback if template is being loaded from alternative path
        alt_path = Path.cwd() / "src" / "ui" / "templates" / "dossier.html"
        if alt_path.exists():
            template_str = alt_path.read_text(encoding="utf-8")
        else:
            raise FileNotFoundError(f"Dossier HTML template not found at {TEMPLATE_PATH} or {alt_path}")

    # Template replacement mapping
    replacements = {
        "{{PATIENT_NAME}}": html.escape(str(patient_name)),
        "{{PATIENT_ID}}": html.escape(str(patient_id)),
        "{{PROVIDER_NAME}}": html.escape(str(provider_name)),
        "{{CLAIM_ID}}": html.escape(str(claim_id)),
        "{{PACKET_ID}}": html.escape(str(packet_id)),
        "{{SERVICE_DATE}}": html.escape(str(service_date)),
        "{{CURRENT_DATE}}": html.escape(str(current_date_formal)),
        "{{GENERATED_TIMESTAMP}}": html.escape(str(generated_at)),
        "{{TOTAL_BILLED}}": _format_currency(total_billed),
        "{{ORIGINAL_PATIENT_LIABILITY}}": _format_currency(original_patient_liability),
        "{{EXCISED_AMOUNT}}": _format_currency(excised_amount),
        "{{LAWFUL_LIABILITY}}": _format_currency(lawful_liability),
        "{{VIOLATION_TABLE_ROWS}}": violation_table_rows_html,
        "{{SHA256_HASH}}": sha256_hash,
        "{{SIGNATURE_TOKEN}}": html.escape(signature_token),
        "{{STATUTORY_DEADLINE}}": html.escape(statutory_deadline_display),
        "{{TRACKING_BADGE_HTML}}": tracking_badge_html,
        "{{APPEAL_PLAINTEXT}}": html.escape(formal_letter_text),
        "{{NETWORK_STATUS}}": "In-Network Participating Facility" if in_network else "Out-of-Network Facility (No Surprises Act Protected)",
        "{{EMERGENCY_STATUS}}": "Emergency Medical Services (45 CFR § 149.30 Covered)" if is_emergency else "Scheduled Post-Service Care"
    }

    rendered = template_str
    for placeholder, val in replacements.items():
        rendered = rendered.replace(placeholder, val)

    return rendered

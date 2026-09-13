"""
Test Suite: WebAuthn / Passkey Biometric Cryptographic Authentication & AWS Cedar Gate Integration.

Verifies:
1. Cryptographic challenge generation, uniqueness, and lifecycle expiry.
2. Real WebAuthn assertion verification with ECDSA P-256 / SHA-256 signatures.
3. Replay attack prevention (single-use challenges).
4. Tampered challenge, signature, and missing User-Present flag rejections.
5. Deterministic test fallback verification for headless CI/CD.
6. Cryptographic token format validation and forgery resistance.
7. CedarAttorney.enforce_dispatch_gate() unsealing with emitted tokens.
8. End-to-end agent dispatch tool attenuation gate execution.
"""

import time
import json
import base64
import hashlib
import pytest
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives import hashes

from src.core.auth import (
    generate_auth_challenge,
    verify_webauthn_assertion,
    verify_fallback_signature,
    generate_fallback_signature,
    verify_cryptographic_token,
    get_default_passkey_pair,
    get_default_public_key,
    register_credential,
    register_auth_token,
    clear_auth_state,
    DETERMINISTIC_PROOF_TOKEN
)
from src.core.cedar_attorney import CedarAttorney
from src.agent.tools import dispatch_statutory_dispute


@pytest.fixture(autouse=True)
def clean_state():
    """Ensure clean auth state before each test."""
    clear_auth_state()
    yield
    clear_auth_state()


# Helper to build valid WebAuthn assertion parameters
def build_test_assertion(challenge: str, private_key=None, rp_id: str = "unbundle.internal", flags: int = 0x05, counter: int = 1):
    if private_key is None:
        priv, pub = get_default_passkey_pair()
    else:
        priv = private_key
        pub = priv.public_key()

    client_data_dict = {
        "type": "webauthn.get",
        "challenge": challenge,
        "origin": f"https://{rp_id}"
    }
    client_data_json = json.dumps(client_data_dict)
    client_data_hash = hashlib.sha256(client_data_json.encode("utf-8")).digest()

    rp_id_hash = hashlib.sha256(rp_id.encode("utf-8")).digest()
    flags_byte = bytes([flags])
    counter_bytes = counter.to_bytes(4, "big")
    authenticator_data = rp_id_hash + flags_byte + counter_bytes

    signed_payload = authenticator_data + client_data_hash
    signature = priv.sign(signed_payload, ec.ECDSA(hashes.SHA256()))

    return {
        "client_data_json": client_data_json,
        "authenticator_data": authenticator_data.hex(),
        "signature": signature.hex(),
        "public_key": pub,
        "private_key": priv
    }


# ==============================================================================
# 1. CHALLENGE GENERATION & LIFECYCLE TESTS
# ==============================================================================

def test_challenge_generation_properties():
    """Verifies that generated challenges are cryptographically random 32-byte nonces."""
    c1 = generate_auth_challenge()
    c2 = generate_auth_challenge()

    assert isinstance(c1, str)
    assert len(c1) == 64  # 32 bytes in hexadecimal
    assert all(c in "0123456789abcdefABCDEF" for c in c1)
    assert c1 != c2  # Cryptographic uniqueness


def test_challenge_expiry():
    """Verifies that challenges expire strictly after their TTL."""
    challenge = generate_auth_challenge(ttl_seconds=1)

    # Valid immediately
    sig = generate_fallback_signature(challenge)

    # Wait for challenge to expire
    time.sleep(1.1)

    success, msg = verify_fallback_signature(challenge, sig)
    assert success is False
    assert "expired" in msg.lower()


def test_challenge_replay_attack_prevention():
    """Verifies that a challenge cannot be reused once consumed."""
    challenge = generate_auth_challenge()
    sig = generate_fallback_signature(challenge)

    # First attempt: SUCCESS
    success1, token1 = verify_fallback_signature(challenge, sig)
    assert success1 is True
    assert token1.startswith("HUMAN_AUTH_TOKEN_")

    # Second attempt (replay): REJECTED
    success2, err2 = verify_fallback_signature(challenge, sig)
    assert success2 is False
    assert "replay" in err2.lower() or "consumed" in err2.lower()


# ==============================================================================
# 2. WEBAUTHN / PASSKEY ASSERTION VERIFICATION
# ==============================================================================

def test_webauthn_assertion_success_with_default_key():
    """Verifies end-to-end WebAuthn biometric assertion verification with default passkey."""
    challenge = generate_auth_challenge()
    assertion = build_test_assertion(challenge)

    success, token = verify_webauthn_assertion(
        challenge=challenge,
        client_data_json=assertion["client_data_json"],
        authenticator_data=assertion["authenticator_data"],
        signature=assertion["signature"]
    )

    assert success is True
    assert token.startswith("HUMAN_AUTH_TOKEN_")
    assert verify_cryptographic_token(token) is True


def test_webauthn_assertion_success_with_custom_registered_key():
    """Verifies assertion verification using a distinct registered ECC P-256 passkey."""
    custom_priv = ec.generate_private_key(ec.SECP256R1())
    custom_pub = custom_priv.public_key()
    register_credential("user-passkey-key-01", custom_pub)

    challenge = generate_auth_challenge()
    assertion = build_test_assertion(challenge, private_key=custom_priv)

    success, token = verify_webauthn_assertion(
        challenge=challenge,
        client_data_json=assertion["client_data_json"],
        authenticator_data=assertion["authenticator_data"],
        signature=assertion["signature"],
        public_key=custom_pub
    )

    assert success is True
    assert token.startswith("HUMAN_AUTH_TOKEN_")
    assert verify_cryptographic_token(token) is True


def test_webauthn_assertion_with_base64url_encoding():
    """Verifies assertion verification when clientDataJSON is base64url encoded."""
    challenge = generate_auth_challenge()
    assertion = build_test_assertion(challenge)

    # Encode client_data_json to base64url
    b64_client_data = base64.urlsafe_b64encode(assertion["client_data_json"].encode("utf-8")).decode("ascii")

    success, token = verify_webauthn_assertion(
        challenge=challenge,
        client_data_json=b64_client_data,
        authenticator_data=assertion["authenticator_data"],
        signature=assertion["signature"]
    )

    assert success is True
    assert token.startswith("HUMAN_AUTH_TOKEN_")


# ==============================================================================
# 3. WEBAUTHN NEGATIVE SPACE & ATTACK REJECTIONS
# ==============================================================================

def test_webauthn_rejects_tampered_challenge():
    """Rejects assertion if challenge inside clientDataJSON does not match expected challenge."""
    active_challenge = generate_auth_challenge()
    tampered_challenge = generate_auth_challenge()

    # Sign with tampered challenge
    assertion = build_test_assertion(challenge=tampered_challenge)

    # Attempt to verify against active challenge
    success, err = verify_webauthn_assertion(
        challenge=active_challenge,
        client_data_json=assertion["client_data_json"],
        authenticator_data=assertion["authenticator_data"],
        signature=assertion["signature"]
    )

    assert success is False
    assert "CHALLENGE_MISMATCH" in err


def test_webauthn_rejects_tampered_signature():
    """Rejects assertion if cryptographic signature is corrupted or tampered."""
    challenge = generate_auth_challenge()
    assertion = build_test_assertion(challenge)

    # Tamper with the DER signature bytes
    sig_bytes = bytes.fromhex(assertion["signature"])
    tampered_sig = bytes([sig_bytes[0] ^ 0xFF]) + sig_bytes[1:]

    success, err = verify_webauthn_assertion(
        challenge=challenge,
        client_data_json=assertion["client_data_json"],
        authenticator_data=assertion["authenticator_data"],
        signature=tampered_sig.hex()
    )

    assert success is False
    assert "SIGNATURE_REJECTED" in err


def test_webauthn_rejects_unauthorized_key():
    """Rejects assertion when signed by an adversary key instead of authorized user key."""
    adversary_priv = ec.generate_private_key(ec.SECP256R1())
    challenge = generate_auth_challenge()
    assertion = build_test_assertion(challenge, private_key=adversary_priv)

    # Attempt verification using default authorized public key
    success, err = verify_webauthn_assertion(
        challenge=challenge,
        client_data_json=assertion["client_data_json"],
        authenticator_data=assertion["authenticator_data"],
        signature=assertion["signature"],
        public_key=get_default_public_key()
    )

    assert success is False
    assert "SIGNATURE_REJECTED" in err


def test_webauthn_rejects_missing_user_present_flag():
    """Rejects assertion if authenticator flags byte lacks User Present (UP bit 0)."""
    challenge = generate_auth_challenge()
    # Flags = 0x00 (User Present = False)
    assertion = build_test_assertion(challenge, flags=0x00)

    success, err = verify_webauthn_assertion(
        challenge=challenge,
        client_data_json=assertion["client_data_json"],
        authenticator_data=assertion["authenticator_data"],
        signature=assertion["signature"]
    )

    assert success is False
    assert "User Present (UP) flag not asserted" in err


def test_webauthn_rejects_unknown_challenge():
    """Rejects assertion when the challenge was never generated."""
    fake_challenge = "a" * 64
    assertion = build_test_assertion(fake_challenge)

    success, err = verify_webauthn_assertion(
        challenge=fake_challenge,
        client_data_json=assertion["client_data_json"],
        authenticator_data=assertion["authenticator_data"],
        signature=assertion["signature"]
    )

    assert success is False
    assert "not found in active challenges" in err


# ==============================================================================
# 4. DETERMINISTIC FALLBACK TESTING
# ==============================================================================

def test_fallback_signature_lifecycle():
    """Verifies deterministic fallback signature verification for headless/automated test runners."""
    challenge = generate_auth_challenge()
    sig = generate_fallback_signature(challenge)

    success, token = verify_fallback_signature(challenge, sig)
    assert success is True
    assert token.startswith("HUMAN_AUTH_TOKEN_")
    assert verify_cryptographic_token(token) is True


def test_fallback_signature_rejects_tampered_signature():
    """Rejects invalid fallback signature."""
    challenge = generate_auth_challenge()
    success, err = verify_fallback_signature(challenge, "INVALID_FORGED_FALLBACK_SIG")
    assert success is False
    assert "SIGNATURE_REJECTED" in err


# ==============================================================================
# 5. CRYPTOGRAPHIC TOKEN VERIFICATION
# ==============================================================================

def test_verify_cryptographic_token_rules():
    """Verifies strict token validation and forgery resistance."""
    # 1. None or empty
    assert verify_cryptographic_token(None) is False
    assert verify_cryptographic_token("") is False

    # 2. Wrong prefix
    assert verify_cryptographic_token("BEARER_TOKEN_12345") is False
    assert verify_cryptographic_token("API_KEY_ABCD") is False

    # 3. Forged token with valid prefix but unissued
    assert verify_cryptographic_token("HUMAN_AUTH_TOKEN_FORGED_BOGUS_HASH") is False
    assert verify_cryptographic_token("HUMAN_AUTH_TOKEN_") is False

    # 4. Deterministic proof token
    assert verify_cryptographic_token(DETERMINISTIC_PROOF_TOKEN) is True

    # 5. Token issued via WebAuthn assertion
    c1 = generate_auth_challenge()
    a1 = build_test_assertion(c1)
    ok1, t1 = verify_webauthn_assertion(c1, a1["client_data_json"], a1["authenticator_data"], a1["signature"])
    assert ok1 is True
    assert verify_cryptographic_token(t1) is True

    # 6. Token issued via fallback
    c2 = generate_auth_challenge()
    ok2, t2 = verify_fallback_signature(c2, generate_fallback_signature(c2))
    assert ok2 is True
    assert verify_cryptographic_token(t2) is True


def test_token_expiry_rejection():
    """Verifies that issued tokens expire when their TTL elapses."""
    token = "HUMAN_AUTH_TOKEN_TEMP_EXPIRE"
    register_auth_token(token, ttl_seconds=1)

    assert verify_cryptographic_token(token) is True
    time.sleep(1.1)
    assert verify_cryptographic_token(token) is False


# ==============================================================================
# 6. AWS CEDAR DISPATCH GATE INTEGRATION
# ==============================================================================

def test_cedar_attorney_dispatch_gate_unseals_with_webauthn_token():
    """
    Verifies that CedarAttorney.enforce_dispatch_gate():
    - Blocks autonomous execution (None).
    - Blocks forged tokens.
    - Unseals ALLOW when presented with a verified WebAuthn token.
    """
    attorney = CedarAttorney()

    # 1. No token -> Hard Deny (403)
    allowed1, msg1 = attorney.enforce_dispatch_gate(None)
    assert allowed1 is False
    assert "EXPLICIT_DENY" in msg1

    # 2. Tampered token -> Hard Deny (403)
    allowed2, msg2 = attorney.enforce_dispatch_gate("HUMAN_AUTH_TOKEN_TAMPERED")
    assert allowed2 is False
    assert "EXPLICIT_DENY" in msg2

    # 3. Real WebAuthn Biometric Token -> Unseals Gate (ALLOW)
    challenge = generate_auth_challenge()
    assertion = build_test_assertion(challenge)
    ok, webauthn_token = verify_webauthn_assertion(
        challenge=challenge,
        client_data_json=assertion["client_data_json"],
        authenticator_data=assertion["authenticator_data"],
        signature=assertion["signature"]
    )
    assert ok is True

    allowed3, msg3 = attorney.enforce_dispatch_gate(webauthn_token)
    assert allowed3 is True
    assert "ALLOW" in msg3


def test_end_to_end_agent_tool_dispatch_gate():
    """
    Verifies end-to-end statutory dispute dispatch tool under Cedar least privilege.
    """
    packet = {
        "packet_id": "DISPUTE-PKT-2026-TEST",
        "claim_id": "CLM-2026-NCCI-TEST",
        "disputed_amount": 410.00
    }

    # Case A: Autonomous dispatch attempt without human token -> DENY
    res_unauth = dispatch_statutory_dispute(packet, human_signature_token=None)
    assert res_unauth["success"] is False
    assert res_unauth["error_code"] == 403
    assert res_unauth["cedar_decision"] == "EXPLICIT_DENY"

    # Case B: Adversary forged token -> DENY
    res_forged = dispatch_statutory_dispute(packet, human_signature_token="HUMAN_AUTH_TOKEN_FORGED_SIG")
    assert res_forged["success"] is False
    assert res_forged["error_code"] == 403
    assert res_forged["cedar_decision"] == "EXPLICIT_DENY"

    # Case C: Valid WebAuthn biometric assertion -> SUCCESS
    challenge = generate_auth_challenge()
    assertion = build_test_assertion(challenge)
    ok, token = verify_webauthn_assertion(
        challenge=challenge,
        client_data_json=assertion["client_data_json"],
        authenticator_data=assertion["authenticator_data"],
        signature=assertion["signature"]
    )
    assert ok is True

    res_auth = dispatch_statutory_dispute(packet, human_signature_token=token)
    assert res_auth["success"] is True
    assert res_auth["cedar_decision"] == "ALLOW"
    assert "certified" in res_auth["message"].lower()

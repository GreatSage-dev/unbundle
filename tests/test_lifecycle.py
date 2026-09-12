from datetime import datetime, timedelta, timezone
from src.lifecycle import StatutoryClockTracker, AppealLifecycleState, PayorResponse

def test_statutory_clock_lifecycle():
    # 1. Initialize tracker
    tracker = StatutoryClockTracker.create(
        packet_id="PKT-TEST-8912",
        claim_id="CLM-2026-NY-8912",
        patient_name="ELEANOR RIGBY",
        payor_name="UNITEDHEALTHCARE",
        disputed_amount=190.0
    )
    assert tracker.state == AppealLifecycleState.DRAFTED
    assert tracker.days_statutory_limit == 30

    # 2. Dispatch appeal -> opens 30-day statutory clock
    now = datetime.now(timezone.utc)
    status = tracker.record_dispatch(dispatch_time=now)
    assert status["state"] == AppealLifecycleState.PENDING_PAYOR_RESPONSE.value
    assert status["days_remaining"] == 30
    assert status["days_elapsed"] == 0

    # 3. Simulate day 15 status check
    day_15 = now + timedelta(days=15)
    status_15 = tracker.get_status(current_time=day_15)
    assert status_15["days_elapsed"] == 15
    assert status_15["days_remaining"] == 15
    assert status_15["is_past_deadline"] is False

    # 4. Simulate day 31 status check -> Deemed Exhausted
    day_31 = now + timedelta(days=31)
    status_31 = tracker.get_status(current_time=day_31)
    assert status_31["state"] == AppealLifecycleState.DEEMED_EXHAUSTED.value
    assert status_31["is_deemed_exhausted"] is True

    # 5. Escalate to State Department of Insurance (DOI)
    doi_result = tracker.escalate_to_doi(state_code="NY")
    assert "DOI-NY-" in doi_result["docket_number"]
    assert tracker.state == AppealLifecycleState.ESCALATED_DOI

def test_statutory_clock_reversal_scenario():
    tracker = StatutoryClockTracker.create(
        packet_id="PKT-TEST-8913",
        claim_id="CLM-2026-NY-8913",
        patient_name="ROBERT CHEN",
        payor_name="AETNA",
        disputed_amount=410.0
    )
    tracker.record_dispatch()
    res = tracker.record_payor_response(PayorResponse.OVERTURNED_FULL)
    assert res["state"] == AppealLifecycleState.REVERSAL_CONFIRMED.value
    assert tracker.reversal_amount == 410.0

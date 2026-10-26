"""Admin payment timing: defaults, storage, validation, audit, and the `settings.updated` event (task 1.2)."""

import json

import pytest

from acme.admin import PaymentTiming, admin_settings, load_payment_timing, save_payment_timing
from acme.payments import subscribe

DEFAULTS = {"delay_payments": True, "pay_at_end_of_day": False, "end_of_day_time": "17:00",
            "end_of_day_timezone": "America/Chicago", "pay_when_queue_empty": True}


def stored(db):
    return {r["key"]: json.loads(r["value"]) for r in db.execute("SELECT key, value FROM admin_settings")}


def audit_entries(db):
    return [json.loads(r["payload_json"]) for r in db.execute(
        "SELECT payload_json FROM audit_log WHERE agent = 'admin' AND event = 'settings.updated' ORDER BY id")]


@pytest.fixture
def emitted():
    seen = []
    unsubscribe = subscribe(lambda name, data: seen.append((name, data)))
    yield seen
    unsubscribe()


def test_defaults_on_an_empty_database(db):
    timing = load_payment_timing(db)
    assert timing.model_dump() == DEFAULTS
    assert not timing.end_of_day_on and timing.idle_on
    assert (timing.batch_time.hour, timing.batch_time.minute, str(timing.tz)) == (17, 0, "America/Chicago")
    assert admin_settings(db) == DEFAULTS | {"updated_by": None, "updated_at": None}


def test_round_trip(db, emitted):
    new = PaymentTiming(pay_at_end_of_day=True, end_of_day_time="08:30", end_of_day_timezone="America/New_York",
                        pay_when_queue_empty=False)
    view = save_payment_timing(new, "  Dana  ")
    assert load_payment_timing(db) == new
    assert stored(db) == new.model_dump()
    assert view == new.model_dump() | {"updated_by": "Dana", "updated_at": view["updated_at"]}
    assert admin_settings(db) == view and view["updated_at"]
    assert emitted == [("settings.updated", view)]


def test_partial_storage_keeps_defaults(db):
    db.execute("INSERT INTO admin_settings VALUES ('delay_payments', 'false', 'Dana', '2026-01-15T00:00:00+00:00')")
    db.commit()
    assert load_payment_timing(db).model_dump() == DEFAULTS | {"delay_payments": False}


@pytest.mark.parametrize("change, name, field", [
    ({"end_of_day_time": "25:00"}, "Dana", "end_of_day_time"),
    ({"end_of_day_time": "5pm"}, "Dana", "end_of_day_time"),
    ({"end_of_day_time": "5:00"}, "Dana", "end_of_day_time"),
    ({"end_of_day_timezone": "Mars/Olympus"}, "Dana", "end_of_day_timezone"),
    ({"end_of_day_timezone": ""}, "Dana", "end_of_day_timezone"),
    ({}, "   ", "updated_by"),
    ({}, "x" * 51, "updated_by"),
])
def test_validation_errors_save_nothing(db, emitted, change, name, field):
    with pytest.raises(ValueError, match=field):
        save_payment_timing(DEFAULTS | change, name)
    assert stored(db) == {} and audit_entries(db) == [] and emitted == []


def test_audit_entry_lists_old_and_new_values(db):
    save_payment_timing(PaymentTiming(pay_at_end_of_day=True), "Dana")
    save_payment_timing(PaymentTiming(pay_at_end_of_day=True, end_of_day_time="15:00"), "Dana")
    save_payment_timing(PaymentTiming(pay_at_end_of_day=True, end_of_day_time="15:00"), "Sam")  # identical
    assert audit_entries(db) == [
        {"by": "Dana", "changes": {"pay_at_end_of_day": [False, True]}},
        {"by": "Dana", "changes": {"end_of_day_time": ["17:00", "15:00"]}},
        {"by": "Sam", "changes": {}},
    ]
    assert admin_settings(db)["updated_by"] == "Sam"

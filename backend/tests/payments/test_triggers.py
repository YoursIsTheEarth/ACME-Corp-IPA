from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

from acme.admin import PaymentTiming
from acme.payments import RunActivity, end_of_day_due, idle_batch_due, load_runs_snapshot, next_batch_time, \
    payable_count
from acme.settings import get_settings

CT = ZoneInfo("America/Chicago")
ET = ZoneInfo("America/New_York")
DEFAULTS = PaymentTiming()
EOD = PaymentTiming(pay_at_end_of_day=True)  # end of day turned on at the default 17:00 America/Chicago


@pytest.fixture
def settings():
    return get_settings()


def test_defaults_schedule_no_end_of_day_batch():
    assert (DEFAULTS.delay_payments, DEFAULTS.pay_at_end_of_day, DEFAULTS.pay_when_queue_empty) == (True, False, True)
    for hour in range(24):
        now = datetime(2026, 1, 15, hour, 30, tzinfo=CT)
        assert next_batch_time(now, DEFAULTS) is None
        assert not end_of_day_due(now, None, DEFAULTS)


@pytest.mark.parametrize("timing", [PaymentTiming(delay_payments=False),
                                    PaymentTiming(delay_payments=False, pay_at_end_of_day=True)])
def test_no_end_of_day_batch_when_delay_is_off(timing):
    at = datetime(2026, 1, 15, 17, 0, tzinfo=CT)
    assert next_batch_time(at, timing) is None and not end_of_day_due(at, None, timing)


def test_custom_time_and_timezone():
    timing = PaymentTiming(pay_at_end_of_day=True, end_of_day_time="08:30", end_of_day_timezone="America/New_York")
    nxt = next_batch_time(datetime(2026, 1, 15, 9, 0, tzinfo=ET), timing)
    assert nxt == datetime(2026, 1, 16, 8, 30, tzinfo=ET) and nxt.tzinfo == ET
    assert next_batch_time(datetime(2026, 1, 15, 8, 0, tzinfo=ET), timing) == datetime(2026, 1, 15, 8, 30, tzinfo=ET)
    assert end_of_day_due(datetime(2026, 1, 15, 8, 30, tzinfo=ET), None, timing)
    assert not end_of_day_due(datetime(2026, 1, 15, 8, 29, tzinfo=ET), None, timing)


def test_next_batch_time_before_five_is_today():
    assert next_batch_time(datetime(2026, 1, 15, 14, 0, tzinfo=CT), EOD) == datetime(2026, 1, 15, 17, 0, tzinfo=CT)


def test_next_batch_time_after_five_is_tomorrow():
    nxt = next_batch_time(datetime(2026, 1, 15, 18, 0, tzinfo=CT), EOD)
    assert nxt == datetime(2026, 1, 16, 17, 0, tzinfo=CT) and nxt.tzinfo == CT


def test_next_batch_time_from_utc_input():
    # 23:30 UTC on Jan 15 is 5:30 PM Central -> tomorrow
    assert next_batch_time(datetime(2026, 1, 15, 23, 30, tzinfo=timezone.utc), EOD) == datetime(
        2026, 1, 16, 17, 0, tzinfo=CT)


def test_next_batch_time_across_dst_start():
    # DST starts 2026-03-08 in Chicago: 5 PM is 23:00 UTC the day before and 22:00 UTC that day
    nxt = next_batch_time(datetime(2026, 3, 7, 18, 0, tzinfo=CT), EOD)
    assert nxt == datetime(2026, 3, 8, 17, 0, tzinfo=CT)
    assert nxt.astimezone(timezone.utc) == datetime(2026, 3, 8, 22, 0, tzinfo=timezone.utc)
    assert nxt.astimezone(timezone.utc) - datetime(2026, 3, 7, 17, 0, tzinfo=CT).astimezone(timezone.utc) == timedelta(
        hours=23)


def test_end_of_day_due_once_per_day():
    before = datetime(2026, 1, 15, 16, 59, tzinfo=CT)
    at = datetime(2026, 1, 15, 17, 0, tzinfo=CT)
    assert not end_of_day_due(before, None, EOD)
    assert end_of_day_due(at, None, EOD)
    assert end_of_day_due(at, datetime(2026, 1, 14, 17, 0, tzinfo=CT), EOD)
    assert not end_of_day_due(at + timedelta(hours=1), at, EOD)
    assert end_of_day_due(datetime(2026, 1, 16, 17, 1, tzinfo=CT), at, EOD)


def test_end_of_day_respects_configured_time():
    timing = PaymentTiming(pay_at_end_of_day=True, end_of_day_time="09:30")
    assert end_of_day_due(datetime(2026, 1, 15, 9, 30, tzinfo=CT), None, timing)


NOW = datetime(2026, 1, 15, 12, 0, tzinfo=timezone.utc)


def ago(seconds):
    return NOW - timedelta(seconds=seconds)


def test_multi_file_upload_waits_for_all_files_and_the_delay(settings):
    first_done = RunActivity("Queued for payment", "Queued for payment", ago(90))
    runs = [first_done, RunActivity("Extracting", "Processing", ago(5)), RunActivity("Uploaded", "Uploaded", ago(95))]
    assert not idle_batch_due(NOW, runs, 1, False, settings, DEFAULTS)
    finished = [first_done, RunActivity("Queued for payment", None, ago(30)), RunActivity("Resolved", None, ago(20))]
    assert not idle_batch_due(NOW, finished, 2, False, settings, DEFAULTS)
    assert idle_batch_due(NOW + timedelta(seconds=40), finished, 2, False, settings, DEFAULTS)


def test_awaiting_review_does_not_block(settings):
    runs = [RunActivity("Awaiting review", "Awaiting review", ago(61)), RunActivity("Resolved", "Resolved", ago(120))]
    assert idle_batch_due(NOW, runs, 1, False, settings, DEFAULTS)


def test_resuming_run_blocks(settings):
    assert not idle_batch_due(NOW, [RunActivity("Awaiting review", "Resuming", ago(600))], 1, False, settings, DEFAULTS)


@pytest.mark.parametrize("timing", [PaymentTiming(pay_when_queue_empty=False), PaymentTiming(delay_payments=False)])
def test_idle_disabled(settings, timing):
    assert not idle_batch_due(NOW, [], 5, False, settings, timing)


def test_end_of_day_toggle_does_not_affect_idle(settings):
    assert idle_batch_due(NOW, [], 5, False, settings, EOD)


def test_empty_queue_and_running_batch(settings):
    runs = [RunActivity("Resolved", "Resolved", ago(600))]
    assert not idle_batch_due(NOW, runs, 0, False, settings, DEFAULTS)
    assert not idle_batch_due(NOW, runs, 3, True, settings, DEFAULTS)
    assert idle_batch_due(NOW, runs, 3, False, settings, DEFAULTS)


def test_configured_delay(monkeypatch):
    monkeypatch.setenv("PAYMENT_IDLE_DELAY_S", "10")
    get_settings.cache_clear()
    assert idle_batch_due(NOW, [RunActivity("Resolved", None, ago(11))], 1, False, get_settings(), DEFAULTS)


def test_snapshot_loaders(pdb):
    pdb.execute("INSERT INTO invoice_runs (id, file_name, uploaded_at, status, stage) VALUES "
                "('r1', 'a.txt', '2026-01-15T11:00:00+00:00', 'Awaiting review', 'Awaiting review'), "
                "('r2', 'b.txt', '2026-01-15T11:58:00', 'Processing', 'Validating')")
    pdb.execute("INSERT INTO audit_log (run_id, ts, event) VALUES ('r1', '2026-01-15T11:59:30+00:00', 'x')")
    pdb.execute("INSERT INTO payment_queue (run_id, invoice_number, vendor, amount_usd, kind, status, attempts, "
                "queued_at) VALUES ('r0', 'INV-1', 'V', '1.00', 'full', 'queued', 0, 'now'), "
                "('r0', 'INV-2', 'V', '1.00', 'full', 'failed', 3, 'now')")
    pdb.commit()
    snap = {r.stage: r for r in load_runs_snapshot(pdb)}
    assert snap["Awaiting review"].last_activity_at == ago(30)
    assert snap["Validating"].processing and snap["Validating"].last_activity_at == ago(120)
    assert payable_count(pdb, 3) == 1

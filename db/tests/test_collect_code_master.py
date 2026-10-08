"""Regression tests for institution registration/change master collection (mock API only)."""
import csv
import importlib.util
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "collect_code_master.py"
spec = importlib.util.spec_from_file_location("collect_code_master_tested", SCRIPT)
collector = importlib.util.module_from_spec(spec)
spec.loader.exec_module(collector)


@pytest.fixture
def conn(tmp_path, monkeypatch):
    monkeypatch.setattr(collector, "DB_FILE", tmp_path / "state.sqlite")
    monkeypatch.setattr(collector, "PAGE_SIZE", 2)
    connection = collector.connect_db()
    yield connection
    connection.close()


def institution(code, name, changed, registered="1992-02-12 00:00:00"):
    return {
        "dminsttCd": code, "dminsttNm": name,
        "chgDt": changed, "rgstDt": registered, "dltYn": "N",
    }


def test_registration_before_2000_and_independent_checkpoints(conn, monkeypatch):
    prior = collector.windows_for("institution", 2000, 2000)[0]
    collector.store_page(conn, "institution", prior[0], prior[1], 1, 0, [])
    previous = dict(conn.execute(
        "SELECT * FROM checkpoint WHERE dataset='institution' AND window_key='2000'"
    ).fetchone())
    assert [key for key, _ in collector.windows_for("institution", 1992, 1992)] == ["1992"]

    calls = []
    def fake_page(_conn, _session, _key, dataset, params, page, _limit):
        calls.append((dataset, params["inqryDiv"], params["inqryBgnDt"], page))
        return 1, [institution("1320000", "경찰청", "2026-09-17 09:47:34")]

    monkeypatch.setattr(collector, "request_page", fake_page)
    collector.plan_dataset(
        conn, None, "fake", "institution", 1992, 10, 0,
        institution_end_year=1992,
    )
    assert calls == [("institution", "1", "199201010000", 1)]
    assert dict(conn.execute(
        "SELECT * FROM checkpoint WHERE dataset='institution' AND window_key='2000'"
    ).fetchone()) == previous
    assert conn.execute("SELECT name FROM records WHERE code='1320000'").fetchone()[0] == "경찰청"

    collector.plan_dataset(
        conn, None, "fake", "institution", 2000, 10, 0,
        institution_query="change",
        change_from="2026-09-17",
        change_to="2026-09-17",
    )
    checkpoint = conn.execute(
        "SELECT window_key, complete FROM checkpoint WHERE dataset='institution' "
        "AND window_key LIKE 'change:%'"
    ).fetchone()
    assert tuple(checkpoint) == ("change:20260917-20260917", 1)
    assert calls[-1][1:3] == ("2", "202609170000")
    # Re-planning the same range is a no-op.
    collector.plan_dataset(
        conn, None, "fake", "institution", 2000, 10, 0,
        institution_query="change",
        change_from="2026-09-17",
        change_to="2026-09-17",
    )
    assert len(calls) == 2


def test_latest_changed_date_wins_conflict_and_export(conn, tmp_path, monkeypatch):
    old = institution("7002171", "구 명칭", "2020-03-26 19:42:02")
    new = institution("7002171", "신 명칭", "2026-09-17 09:47:34")
    later_old = institution("7002171", "이전 명칭", "2021-03-26 19:42:02")
    register = {"inqryDiv": "1"}
    change = {"inqryDiv": "2"}

    collector.store_page(conn, "institution", "1992", register, 1, 1, [old])
    collector.store_page(
        conn, "institution", "change:20260917-20260917", change, 1, 1, [new],
    )
    collector.store_page(conn, "institution", "2004", register, 1, 1, [later_old])
    record = conn.execute(
        "SELECT name, changed_at, source_window, raw_json FROM records WHERE code='7002171'"
    ).fetchone()
    assert record["name"] == "신 명칭"
    assert record["changed_at"] == "2026-09-17 09:47:34"
    assert record["source_window"] == "change:20260917-20260917"
    assert json.loads(record["raw_json"])["dminsttNm"] == "신 명칭"
    assert conn.execute(
        "SELECT COUNT(*) FROM records WHERE dataset='institution' AND code='7002171'"
    ).fetchone()[0] == 1
    assert conn.execute(
        "SELECT COUNT(*) FROM conflicts WHERE dataset='institution' AND code='7002171'"
    ).fetchone()[0] >= 1
    # The existing PostgreSQL importer expects the exact same 7-column CSV.
    monkeypatch.setattr(collector, "MASTER_DIR", tmp_path)
    monkeypatch.setattr(collector, "CONFLICT_DIR", tmp_path / "conflicts")
    (tmp_path / "conflicts").mkdir()
    collector.export_dataset(conn, "institution")
    with (tmp_path / "institution_codes.csv").open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        assert reader.fieldnames == [
            "code", "name", "active", "changed_at",
            "source_window", "collected_at", "raw_json",
        ]
        assert next(reader)["name"] == "신 명칭"


def test_equal_timestamp_change_query_wins_once(conn):
    timestamp = "2026-09-17 09:47:34"
    item = institution("1320000", "등록명", timestamp)
    changed = institution("1320000", "변경명", timestamp)
    collector.store_page(conn, "institution", "1992", {"inqryDiv": "1"}, 1, 1, [item])
    collector.store_page(
        conn, "institution", "change:20260917-20260917",
        {"inqryDiv": "2"}, 1, 1, [changed],
    )
    collector.store_page(
        conn, "institution", "2000", {"inqryDiv": "1"}, 1, 1, [item],
    )
    assert conn.execute(
        "SELECT name FROM records WHERE dataset='institution' AND code='1320000'"
    ).fetchone()[0] == "변경명"


def test_page_failure_resumes_without_early_completion(conn, monkeypatch):
    items = [
        institution("1000001", "기관1", "2026-09-17 09:00:01"),
        institution("1000002", "기관2", "2026-09-17 09:00:02"),
        institution("1000003", "기관3", "2026-09-17 09:00:03"),
    ]
    calls = []
    failure = [True]

    def fake_page(_conn, _session, _key, _dataset, _params, page, _limit):
        calls.append(page)
        if page == 2 and failure[0]:
            failure[0] = False
            raise collector.ApiError("temporary API failure")
        return 3, items[(page - 1) * 2:page * 2]

    monkeypatch.setattr(collector, "request_page", fake_page)
    collector.plan_dataset(
        conn, None, "fake", "institution", 2000, 10, 0,
        institution_query="change",
        change_from="2026-09-17", change_to="2026-09-17",
    )
    with pytest.raises(collector.ApiError, match="temporary"):
        collector.collect_dataset(
            conn, None, "fake", "institution", 10, 0,
            institution_query="change",
        )
    row = conn.execute(
        "SELECT next_page, complete FROM checkpoint WHERE window_key LIKE 'change:%'"
    ).fetchone()
    assert tuple(row) == (2, 0)
    collector.collect_dataset(
        conn, None, "fake", "institution", 10, 0,
        institution_query="change",
    )
    assert conn.execute(
        "SELECT COUNT(*) FROM records WHERE dataset='institution'"
    ).fetchone()[0] == 3
    assert tuple(conn.execute(
        "SELECT next_page, complete FROM checkpoint WHERE window_key LIKE 'change:%'"
    ).fetchone()) == (3, 1)
    assert calls == [1, 2, 2]
    # A second collect does not replay the finished range.
    collector.collect_dataset(
        conn, None, "fake", "institution", 10, 0,
        institution_query="change",
    )
    assert calls == [1, 2, 2]


def test_incomplete_page_not_marked_complete(conn):
    with pytest.raises(collector.ApiError, match="Incomplete API page"):
        collector.store_page(
            conn, "institution", "change:20260917-20260917",
            {"inqryDiv": "2"}, 1, 3,
            [institution("1000001", "기관1", "2026-09-17 09:00:01")],
        )
    assert conn.execute("SELECT COUNT(*) FROM checkpoint").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM records").fetchone()[0] == 0


def test_change_cursor_overlap_and_pending_block(conn):
    params = {
        "inqryDiv": "2",
        "inqryBgnDt": "202501010000",
        "inqryEndDt": "202501032359",
    }
    collector.store_page(
        conn, "institution", "change:20250101-20250103", params, 1, 0, [],
    )
    windows = collector.change_windows_for(conn, None, "2025-01-06", 2)
    assert [key for key, _ in windows] == [
        "change:20250103-20250104", "change:20250105-20250106",
    ]
    # A planned but unfinished window must be resumed, not skipped.
    conn.execute(
        "INSERT INTO checkpoint VALUES (?,?,?,?,?,?,?,?)",
        ("institution", "change:20250103-20250104",
         '{"inqryDiv":"2"}', 3, 2, 2, 0, "2025-01-04"),
    )
    conn.commit()
    assert collector.change_windows_for(conn, None, "2025-01-08", 2) == []



def test_total_count_drift_rewinds_incomplete_window(conn):
    params = {"inqryDiv": "2"}
    key = "change:20260917-20260917"
    first_page = [
        institution("1000001", "기관1", "2026-09-17 09:00:01"),
        institution("1000002", "기관2", "2026-09-17 09:00:02"),
    ]
    collector.store_page(conn, "institution", key, params, 1, 3, first_page)
    with pytest.raises(collector.ApiError, match="retry from page 1"):
        collector.store_page(conn, "institution", key, params, 2, 2, [])
    assert tuple(conn.execute(
        "SELECT next_page, complete FROM checkpoint WHERE window_key=?", (key,)
    ).fetchone()) == (1, 0)
    collector.store_page(conn, "institution", key, params, 1, 2, first_page)
    assert tuple(conn.execute(
        "SELECT next_page, complete FROM checkpoint WHERE window_key=?", (key,)
    ).fetchone()) == (2, 1)


def test_change_checkpoint_gap_not_silently_advanced(conn):
    collector.store_page(
        conn, "institution", "change:20250101-20250102",
        {"inqryDiv": "2"}, 1, 0, [],
    )
    collector.store_page(
        conn, "institution", "change:20250105-20250106",
        {"inqryDiv": "2"}, 1, 0, [],
    )
    with pytest.raises(ValueError, match="Gap"):
        collector.change_windows_for(conn, None, "2025-01-08", 7)

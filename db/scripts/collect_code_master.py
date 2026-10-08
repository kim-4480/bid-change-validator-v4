from __future__ import annotations

import argparse
import csv
import json
import math
import os
import sqlite3
import sys
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import unquote

import requests


PROJECT_ROOT = Path(__file__).resolve().parents[2]
ENV_FILE = PROJECT_ROOT / ".env"
DATA_DIR = PROJECT_ROOT / "data"
MASTER_DIR = DATA_DIR / "master"
STATE_DIR = DATA_DIR / "state"
CONFLICT_DIR = MASTER_DIR / "conflicts"
DB_FILE = STATE_DIR / "code_master_state.sqlite"

PAGE_SIZE = 999
REQUEST_TIMEOUT = 45
DEFAULT_DAILY_LIMIT = 9000

DATASETS = {
    "industry": {
        "base_url": "https://apis.data.go.kr/1230000/ao/IndstrytyBaseLawrgltInfoService",
        "operation": "getIndstrytyBaseLawrgltInfoList",
        "code_fields": ("indstrytyCd",),
        "name_fields": ("indstrytyNm",),
        "active_fields": ("indstrytyUseYn", "useYn"),
        "changed_fields": ("chgDt", "chgDate", "rgstDt"),
        "output": "industry_codes.csv",
    },
    "product": {
        "base_url": "https://apis.data.go.kr/1230000/ao/ThngListInfoService02",
        "operation": "getPrdctClsfcNoUnit10Info02",
        "code_fields": ("dtilPrdctClsfcNo",),
        "name_fields": ("dtilPrdctClsfcNoNm",),
        "active_fields": ("useYn",),
        "changed_fields": ("chgDate", "chgDt", "rgstDt"),
        "output": "product_codes.csv",
    },
    "institution": {
        "base_url": "https://apis.data.go.kr/1230000/ao/UsrInfoService02",
        "operation": "getDminsttInfo02",
        "code_fields": ("dminsttCd",),
        "name_fields": ("dminsttNm",),
        "active_fields": ("dltYn",),
        "changed_fields": ("chgDt", "rgstDt"),
        "output": "institution_codes.csv",
    },
}


class ApiError(RuntimeError):
    pass


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="나라장터 공식 전용 API 기반 코드 마스터 수집기"
    )
    parser.add_argument(
        "--mode",
        choices=("plan", "collect", "status"),
        default="status",
        help="plan: 첫 페이지로 호출량 산정, collect: 나머지 수집, status: 상태 출력",
    )
    parser.add_argument(
        "--datasets",
        nargs="+",
        choices=tuple(DATASETS),
        default=list(DATASETS),
    )
    parser.add_argument("--institution-start-year", type=int, default=2000)
    parser.add_argument("--institution-end-year", type=int)
    parser.add_argument(
        "--institution-query", choices=("registration", "change"),
        default="registration",
        help="registration uses inqryDiv=1; change uses inqryDiv=2",
    )
    parser.add_argument("--change-from", help="Start date (YYYY-MM-DD) for first or explicit change run")
    parser.add_argument("--change-to", help="End date (YYYY-MM-DD); defaults to yesterday (KST)")
    parser.add_argument("--change-window-days", type=int, default=7)
    parser.add_argument("--daily-limit", type=int, default=DEFAULT_DAILY_LIMIT)
    parser.add_argument("--request-delay", type=float, default=0.04)
    return parser.parse_args()


def ensure_dirs() -> None:
    for path in (MASTER_DIR, STATE_DIR, CONFLICT_DIR):
        path.mkdir(parents=True, exist_ok=True)


def load_service_key() -> str:
    raw = (os.getenv("G2B_SERVICE_KEY") or "").strip()
    if not raw and ENV_FILE.exists():
        for line in ENV_FILE.read_text(encoding="utf-8-sig").splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#") or "=" not in stripped:
                continue
            name, value = stripped.split("=", 1)
            if name.strip() == "G2B_SERVICE_KEY":
                raw = value.strip().strip('"').strip("'")
                break
    if not raw:
        raise RuntimeError(f"G2B_SERVICE_KEY가 없습니다: {ENV_FILE}")
    return unquote(raw)


def connect_db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS checkpoint (
            dataset TEXT NOT NULL,
            window_key TEXT NOT NULL,
            params_json TEXT NOT NULL,
            total_count INTEGER,
            total_pages INTEGER,
            next_page INTEGER NOT NULL DEFAULT 1,
            complete INTEGER NOT NULL DEFAULT 0,
            updated_at TEXT NOT NULL,
            PRIMARY KEY (dataset, window_key)
        );

        CREATE TABLE IF NOT EXISTS records (
            dataset TEXT NOT NULL,
            code TEXT NOT NULL,
            name TEXT NOT NULL,
            active TEXT,
            changed_at TEXT,
            raw_json TEXT NOT NULL,
            source_window TEXT NOT NULL,
            collected_at TEXT NOT NULL,
            PRIMARY KEY (dataset, code)
        );

        CREATE TABLE IF NOT EXISTS conflicts (
            dataset TEXT NOT NULL,
            code TEXT NOT NULL,
            old_name TEXT NOT NULL,
            new_name TEXT NOT NULL,
            old_raw_json TEXT NOT NULL,
            new_raw_json TEXT NOT NULL,
            observed_at TEXT NOT NULL,
            UNIQUE(dataset, code, old_name, new_name)
        );

        CREATE TABLE IF NOT EXISTS api_usage (
            usage_date TEXT PRIMARY KEY,
            calls INTEGER NOT NULL DEFAULT 0
        );
        """
    )
    return conn


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def local_date() -> str:
    return datetime.now().astimezone().date().isoformat()


def consume_call(conn: sqlite3.Connection, daily_limit: int) -> None:
    day = local_date()
    row = conn.execute(
        "SELECT calls FROM api_usage WHERE usage_date = ?", (day,)
    ).fetchone()
    used = int(row["calls"]) if row else 0
    if used >= daily_limit:
        raise RuntimeError(f"일일 안전한도 도달: {used}/{daily_limit}")
    conn.execute(
        """
        INSERT INTO api_usage(usage_date, calls) VALUES (?, 1)
        ON CONFLICT(usage_date) DO UPDATE SET calls = calls + 1
        """,
        (day,),
    )
    conn.commit()


def first_value(item: dict[str, Any], fields: Iterable[str]) -> str:
    for field in fields:
        value = item.get(field)
        if value is not None and str(value).strip():
            return str(value).strip()
    return ""


def extract_items(value: Any) -> list[dict[str, Any]]:
    if value is None:
        return []
    if isinstance(value, list):
        return [x for x in value if isinstance(x, dict)]
    if not isinstance(value, dict):
        return []
    for key in ("item", "items", "itemsElf"):
        if key in value:
            nested = extract_items(value[key])
            if nested:
                return nested
    if value and all(not isinstance(v, (dict, list)) for v in value.values()):
        return [value]
    for nested_value in value.values():
        nested = extract_items(nested_value)
        if nested:
            return nested
    return []


def parse_response(payload: Any) -> tuple[int, list[dict[str, Any]]]:
    if not isinstance(payload, dict):
        raise ApiError("JSON 최상위가 객체가 아닙니다")

    response = payload.get("response")
    if not isinstance(response, dict):
        for key, value in payload.items():
            if key.endswith("ResponseError") and isinstance(value, dict):
                header = value.get("header") or {}
                code = str(header.get("resultCode", ""))
                message = str(header.get("resultMsg", ""))
                if code == "03":
                    return 0, []
                raise ApiError(f"resultCode={code}, resultMsg={message}")
        if "header" in payload and "body" in payload:
            response = payload
        else:
            raise ApiError(f"response 객체가 없습니다: {list(payload)[:5]}")

    header = response.get("header") or {}
    result_code = str(header.get("resultCode", ""))
    result_msg = str(header.get("resultMsg", ""))
    if result_code not in ("", "00"):
        if result_code == "03":
            return 0, []
        raise ApiError(f"resultCode={result_code}, resultMsg={result_msg}")

    body = response.get("body") or {}
    try:
        total_count = int(body.get("totalCount") or 0)
    except (TypeError, ValueError):
        total_count = 0
    items = extract_items(body.get("items"))
    if not items:
        items = extract_items(body.get("itemsElf"))
    return total_count, items


def request_page(
    conn: sqlite3.Connection,
    session: requests.Session,
    service_key: str,
    dataset: str,
    params: dict[str, str],
    page: int,
    daily_limit: int,
) -> tuple[int, list[dict[str, Any]]]:
    config = DATASETS[dataset]
    url = f"{config['base_url']}/{config['operation']}"
    query = {
        "serviceKey": service_key,
        "pageNo": str(page),
        "numOfRows": str(PAGE_SIZE),
        "type": "json",
        **params,
    }
    prepared = requests.Request("GET", url, params=query).prepare()
    prepared_url = prepared.url or ""
    if any(token in prepared_url for token in ("%252B", "%252F", "%253D")):
        raise RuntimeError("serviceKey 이중 URL 인코딩이 감지됐습니다")

    consume_call(conn, daily_limit)
    response = session.send(prepared, timeout=REQUEST_TIMEOUT)
    if response.status_code != 200:
        raise ApiError(f"HTTP {response.status_code}: {dataset}, page={page}")
    try:
        payload = response.json()
    except ValueError as exc:
        raise ApiError(f"JSON 파싱 실패: {dataset}, page={page}") from exc
    return parse_response(payload)


def is_active(dataset: str, item: dict[str, Any]) -> str:
    raw = first_value(item, DATASETS[dataset]["active_fields"]).upper()
    if dataset == "institution":
        return "N" if raw == "Y" else "Y"
    if not raw:
        return ""
    return "Y" if raw in ("Y", "1", "TRUE") else "N"


def should_replace(
    old_changed: str,
    new_changed: str,
    old_source_window: str = "",
    new_source_window: str = "",
) -> bool:
    """Prefer newer API change timestamps, not whichever query ran last."""
    if old_source_window == new_source_window == "all":
        # Preserve legacy industry/product behavior outside the institution change.
        return not old_changed or bool(new_changed and new_changed >= old_changed)
    if not new_changed:
        return not old_changed and not old_source_window
    if not old_changed:
        return True
    # G2B uses YYYY-MM-DD HH:MM:SS; ISO dates compare in chronological order.
    if new_changed != old_changed:
        return new_changed > old_changed
    # Equal timestamps: change-query payload takes precedence over registration.
    return new_source_window.startswith("change:") and not old_source_window.startswith("change:")


def store_page(
    conn: sqlite3.Connection,
    dataset: str,
    window_key: str,
    params: dict[str, str],
    page: int,
    total_count: int,
    items: list[dict[str, Any]],
) -> None:
    config = DATASETS[dataset]
    total_pages = math.ceil(total_count / PAGE_SIZE) if total_count else 0
    checkpoint = conn.execute(
        "SELECT total_count, next_page, complete, params_json FROM checkpoint "
        "WHERE dataset=? AND window_key=?",
        (dataset, window_key),
    ).fetchone()
    if checkpoint:
        if json.loads(checkpoint["params_json"]) != params:
            raise ApiError(f"Checkpoint parameter conflict: {dataset} {window_key}")
        if page > 1 and int(checkpoint["total_count"]) != total_count:
            # The API is not a snapshot: replay this incomplete window from page 1
            # on the next collect invocation rather than silently losing shifted rows.
            with conn:
                conn.execute(
                    "UPDATE checkpoint SET total_count=?, total_pages=?, next_page=1, "
                    "complete=0, updated_at=? WHERE dataset=? AND window_key=?",
                    (total_count, max(1, total_pages), now_iso(), dataset, window_key),
                )
            raise ApiError(f"API total changed; retry from page 1: {dataset} {window_key}")
        if page != int(checkpoint["next_page"]):
            raise ApiError(f"Unexpected page for checkpoint: {dataset} {window_key} page={page}")
    elif page != 1:
        raise ApiError(f"Missing page-one checkpoint: {dataset} {window_key}")
    expected = min(PAGE_SIZE, max(0, total_count - (page - 1) * PAGE_SIZE))
    if page < 1 or (total_count and page > total_pages) or len(items) != expected:
        raise ApiError(
            f"Incomplete API page: {dataset} {window_key} "
            f"page={page}, expected={expected}, got={len(items)}, total={total_count}"
        )
    stamp = now_iso()
    with conn:
        for item in items:
            code = first_value(item, config["code_fields"])
            name = first_value(item, config["name_fields"])
            if not code or not name:
                continue
            raw_json = json.dumps(item, ensure_ascii=False, sort_keys=True)
            changed_at = first_value(item, config["changed_fields"])
            old = conn.execute(
                "SELECT name, changed_at, raw_json, source_window FROM records WHERE dataset=? AND code=?",
                (dataset, code),
            ).fetchone()
            if old and old["name"] != name:
                conn.execute(
                    """
                    INSERT OR IGNORE INTO conflicts(
                        dataset, code, old_name, new_name,
                        old_raw_json, new_raw_json, observed_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        dataset,
                        code,
                        old["name"],
                        name,
                        old["raw_json"],
                        raw_json,
                        stamp,
                    ),
                )
            if not old or should_replace(
                old["changed_at"] or "", changed_at,
                old["source_window"] or "", window_key,
            ):
                conn.execute(
                    """
                    INSERT INTO records(
                        dataset, code, name, active, changed_at,
                        raw_json, source_window, collected_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(dataset, code) DO UPDATE SET
                        name=excluded.name,
                        active=excluded.active,
                        changed_at=excluded.changed_at,
                        raw_json=excluded.raw_json,
                        source_window=excluded.source_window,
                        collected_at=excluded.collected_at
                    """,
                    (
                        dataset,
                        code,
                        name,
                        is_active(dataset, item),
                        changed_at,
                        raw_json,
                        window_key,
                        stamp,
                    ),
                )

        next_page = page + 1
        complete = 1 if total_pages == 0 or next_page > total_pages else 0
        conn.execute(
            """
            INSERT INTO checkpoint(
                dataset, window_key, params_json, total_count,
                total_pages, next_page, complete, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(dataset, window_key) DO UPDATE SET
                params_json=excluded.params_json,
                total_count=excluded.total_count,
                total_pages=excluded.total_pages,
                next_page=excluded.next_page,
                complete=excluded.complete,
                updated_at=excluded.updated_at
            """,
            (
                dataset,
                window_key,
                json.dumps(params, sort_keys=True),
                total_count,
                total_pages,
                next_page,
                complete,
                stamp,
            ),
        )


def windows_for(
    dataset: str, institution_start_year: int, institution_end_year: int | None = None
) -> list[tuple[str, dict[str, str]]]:
    if dataset != "institution":
        return [("all", {})]
    current_year = datetime.now().year
    end_year = institution_end_year if institution_end_year is not None else current_year
    if not 1 <= institution_start_year <= end_year <= current_year:
        raise ValueError("Invalid institution registration year range")
    windows: list[tuple[str, dict[str, str]]] = []
    # Keep legacy year-only checkpoint keys intact (e.g. 2000..2026).
    for year in range(end_year, institution_start_year - 1, -1):
        end = (
            datetime.now().astimezone().strftime("%Y%m%d%H%M")
            if year == current_year else f"{year}12312359"
        )
        windows.append(
            (str(year), {
                "inqryDiv": "1",
                "inqryBgnDt": f"{year}01010000",
                "inqryEndDt": end,
            })
        )
    return windows


def change_windows_for(
    conn: sqlite3.Connection,
    start_text: str | None,
    end_text: str | None,
    window_days: int,
) -> list[tuple[str, dict[str, str]]]:
    """Plan complete KST calendar days; resume from the last finished range."""
    if not 1 <= window_days <= 31:
        raise ValueError("--change-window-days must be between 1 and 31")

    def parse_day(value: str) -> date:
        try:
            parsed = date.fromisoformat(value)
        except ValueError as exc:
            raise ValueError(f"Invalid date: {value} (expected YYYY-MM-DD)") from exc
        if parsed.isoformat() != value:
            raise ValueError(f"Invalid date: {value} (expected YYYY-MM-DD)")
        return parsed

    # Closed days only by default: do not checkpoint an unfinished current day.
    today_kst = datetime.now(timezone(timedelta(hours=9))).date()
    end = parse_day(end_text) if end_text else today_kst - timedelta(days=1)
    if end > today_kst:
        raise ValueError("--change-to cannot be in the future")

    existing = conn.execute(
        "SELECT window_key, complete FROM checkpoint "
        "WHERE dataset='institution' AND window_key LIKE 'change:%' "
        "ORDER BY window_key"
    ).fetchall()
    if start_text:
        start = parse_day(start_text)
    elif not existing:
        raise ValueError("First change run requires --change-from YYYY-MM-DD")
    else:
        # Never advance the automatic cursor past a failed or unfinished interval.
        if any(not row["complete"] for row in existing):
            print("PLAN change: unfinished checkpoints exist; run --mode collect first")
            return []
        intervals = []
        for row in existing:
            key = row["window_key"]
            first, last = key.removeprefix("change:").split("-")
            intervals.append((date.fromisoformat(first), date.fromisoformat(last)))
        intervals.sort()
        last_end = intervals[0][1]
        for first, last in intervals[1:]:
            if first > last_end + timedelta(days=1):
                raise ValueError("Gap in change checkpoints: explicitly backfill it first")
            last_end = max(last_end, last)
        # Re-read the last completed day to protect boundary/late API updates.
        start = last_end
    if start > end:
        return []

    windows = []
    cursor = start
    while cursor <= end:
        last = min(end, cursor + timedelta(days=window_days - 1))
        first_key, last_key = cursor.strftime("%Y%m%d"), last.strftime("%Y%m%d")
        windows.append((
            f"change:{first_key}-{last_key}",
            {
                "inqryDiv": "2",
                "inqryBgnDt": f"{first_key}0000",
                "inqryEndDt": f"{last_key}2359",
            },
        ))
        cursor = last + timedelta(days=1)
    return windows


def plan_dataset(
    conn: sqlite3.Connection,
    session: requests.Session,
    service_key: str,
    dataset: str,
    institution_start_year: int,
    daily_limit: int,
    request_delay: float,
    *,
    institution_end_year: int | None = None,
    institution_query: str = "registration",
    change_from: str | None = None,
    change_to: str | None = None,
    change_window_days: int = 7,
) -> None:
    windows = (
        change_windows_for(conn, change_from, change_to, change_window_days)
        if dataset == "institution" and institution_query == "change"
        else windows_for(dataset, institution_start_year, institution_end_year)
    )
    for index, (window_key, params) in enumerate(windows, start=1):
        existing = conn.execute(
            "SELECT total_count FROM checkpoint WHERE dataset=? AND window_key=?",
            (dataset, window_key),
        ).fetchone()
        if existing is not None:
            continue
        try:
            total_count, items = request_page(
                conn, session, service_key, dataset, params, 1, daily_limit
            )
        except ApiError as exc:
            if "resultCode=03" in str(exc):
                total_count, items = 0, []
            else:
                raise
        store_page(conn, dataset, window_key, params, 1, total_count, items)
        if dataset != "institution" or total_count or index % 10 == 0:
            pages = math.ceil(total_count / PAGE_SIZE) if total_count else 0
            print(
                f"PLAN {dataset} window={window_key} total={total_count} pages={pages}",
                flush=True,
            )
        if request_delay:
            time.sleep(request_delay)


def collect_dataset(
    conn: sqlite3.Connection,
    session: requests.Session,
    service_key: str,
    dataset: str,
    daily_limit: int,
    request_delay: float,
    *,
    institution_query: str = "registration",
    institution_start_year: int = 2000,
    institution_end_year: int | None = None,
) -> None:
    if dataset == "institution" and institution_query == "change":
        rows = conn.execute(
            "SELECT * FROM checkpoint WHERE dataset=? AND complete=0 "
            "AND window_key LIKE 'change:%' ORDER BY window_key",
            (dataset,),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM checkpoint WHERE dataset=? AND complete=0 "
            "AND window_key NOT LIKE 'change:%' ORDER BY CAST(window_key AS INTEGER) DESC",
            (dataset,),
        ).fetchall()
        if dataset == "institution" and (
            institution_start_year != 2000 or institution_end_year is not None
        ):
            end_year = institution_end_year or datetime.now().year
            rows = [
                row for row in rows
                if row["window_key"].isdigit()
                and institution_start_year <= int(row["window_key"]) <= end_year
            ]
    if not rows:
        print(f"COLLECT {dataset}: 남은 페이지 없음", flush=True)
        return
    for row in rows:
        params = json.loads(row["params_json"])
        page = int(row["next_page"])
        total_pages = int(row["total_pages"] or 0)
        while page <= total_pages:
            total_count, items = request_page(
                conn, session, service_key, dataset, params, page, daily_limit
            )
            store_page(
                conn,
                dataset,
                row["window_key"],
                params,
                page,
                total_count,
                items,
            )
            print(
                f"COLLECT {dataset} window={row['window_key']} page={page}/{total_pages} items={len(items)}",
                flush=True,
            )
            page += 1
            if request_delay:
                time.sleep(request_delay)


def write_csv_atomic(path: Path, fieldnames: list[str], rows: Iterable[dict[str, Any]]) -> None:
    temp = path.with_suffix(path.suffix + ".tmp")
    with temp.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    temp.replace(path)


def export_dataset(conn: sqlite3.Connection, dataset: str) -> None:
    config = DATASETS[dataset]
    records = conn.execute(
        """
        SELECT code, name, active, changed_at, source_window,
               collected_at, raw_json
        FROM records WHERE dataset=? ORDER BY code
        """,
        (dataset,),
    ).fetchall()
    output = MASTER_DIR / config["output"]
    write_csv_atomic(
        output,
        [
            "code",
            "name",
            "active",
            "changed_at",
            "source_window",
            "collected_at",
            "raw_json",
        ],
        (dict(row) for row in records),
    )

    conflicts = conn.execute(
        """
        SELECT code, old_name, new_name, observed_at,
               old_raw_json, new_raw_json
        FROM conflicts WHERE dataset=? ORDER BY code, observed_at
        """,
        (dataset,),
    ).fetchall()
    conflict_path = CONFLICT_DIR / f"{dataset}_name_conflicts.csv"
    write_csv_atomic(
        conflict_path,
        [
            "code",
            "old_name",
            "new_name",
            "observed_at",
            "old_raw_json",
            "new_raw_json",
        ],
        (dict(row) for row in conflicts),
    )


def status(conn: sqlite3.Connection, datasets: list[str]) -> None:
    for dataset in datasets:
        aggregate = conn.execute(
            """
            SELECT COUNT(*) AS windows,
                   COALESCE(SUM(total_count), 0) AS total_count,
                   COALESCE(SUM(total_pages), 0) AS total_pages,
                   COALESCE(SUM(CASE WHEN complete=1 THEN 1 ELSE 0 END), 0) AS complete_windows,
                   COALESCE(SUM(CASE WHEN complete=0 THEN total_pages-next_page+1 ELSE 0 END), 0) AS remaining_calls
            FROM checkpoint WHERE dataset=?
            """,
            (dataset,),
        ).fetchone()
        records = conn.execute(
            "SELECT COUNT(*) AS count FROM records WHERE dataset=?",
            (dataset,),
        ).fetchone()["count"]
        print(
            f"STATUS {dataset}: records={records}, windows={aggregate['windows']}, "
            f"complete={aggregate['complete_windows']}/{aggregate['windows']}, "
            f"reported_total={aggregate['total_count']}, "
            f"pages={aggregate['total_pages']}, remaining_calls={aggregate['remaining_calls']}",
            flush=True,
        )
    usage = conn.execute(
        "SELECT calls FROM api_usage WHERE usage_date=?", (local_date(),)
    ).fetchone()
    print(f"STATUS api_calls_today={int(usage['calls']) if usage else 0}", flush=True)


def main() -> int:
    args = parse_args()
    if args.institution_query == "change" and args.datasets != ["institution"]:
        raise ValueError("Change query requires --datasets institution")
    if (args.change_from or args.change_to) and args.institution_query != "change":
        raise ValueError("--change-from/--change-to require --institution-query change")
    ensure_dirs()
    conn = connect_db()
    try:
        if args.mode == "status":
            status(conn, args.datasets)
            return 0

        service_key = load_service_key()
        with requests.Session() as session:
            session.headers["User-Agent"] = "bid-change-validator-code-master/1.0"
            if args.mode == "plan":
                for dataset in args.datasets:
                    plan_dataset(
                        conn,
                        session,
                        service_key,
                        dataset,
                        args.institution_start_year,
                        args.daily_limit,
                        args.request_delay,
                        institution_end_year=args.institution_end_year,
                        institution_query=args.institution_query,
                        change_from=args.change_from,
                        change_to=args.change_to,
                        change_window_days=args.change_window_days,
                    )
            elif args.mode == "collect":
                for dataset in args.datasets:
                    collect_dataset(
                        conn,
                        session,
                        service_key,
                        dataset,
                        args.daily_limit,
                        args.request_delay,
                        institution_query=args.institution_query,
                        institution_start_year=args.institution_start_year,
                        institution_end_year=args.institution_end_year,
                    )

        for dataset in args.datasets:
            export_dataset(conn, dataset)
        status(conn, args.datasets)
        return 0
    except (ApiError, requests.RequestException, RuntimeError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        status(conn, args.datasets)
        return 1
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())

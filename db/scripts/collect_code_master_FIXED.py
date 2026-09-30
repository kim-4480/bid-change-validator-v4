from __future__ import annotations

from argparse import ArgumentParser
from datetime import datetime, timedelta, timezone
from math import ceil
from pathlib import Path
from urllib.parse import unquote
import json
import os
import re

import pandas as pd
import requests
from dotenv import load_dotenv


# =============================================================================
# 목적
# =============================================================================
#
# 나라장터 검색/매칭용 "코드 ↔ 명칭" 기준표(master) 수집
#
# 기본 실행:
#   - 참가제한지역 코드표: API 호출 0회
#   - 면허/업종 코드표: getBidPblancListInfoLicenseLimit
#
# 옵션:
#   --include-products
#   - 세부품명번호/세부품명, 기관코드/기관명:
#     getBidPblancListInfoThngPurchsObjPrdct
#
# 호출량 절약:
#   - 물품 검색조건 공고조회 API는 사용하지 않음
#   - numOfRows=999
#   - 기본 31일 단위로 묶어서 조회
#   - totalCount를 보고 필요한 페이지만 호출
#   - 마지막 완료시각/페이지를 state에 저장해서 재실행 시 이어받음
#   - KST 기준 일일 로컬 안전한도 기본 700회
#     (공식 1000회 중 최소 300회를 다른 테스트/직접 호출용으로 남김)
#
# =============================================================================


# =============================================================================
# 기본 설정
# =============================================================================

KST = timezone(timedelta(hours=9))

BASE_URL = "https://apis.data.go.kr/1230000/ad/BidPublicInfoService"

LICENSE_ENDPOINT = "getBidPblancListInfoLicenseLimit"
PRODUCT_ENDPOINT = "getBidPblancListInfoThngPurchsObjPrdct"

PAGE_SIZE = 999
DEFAULT_WINDOW_DAYS = 31
DEFAULT_DAILY_SAFE_LIMIT = 700
REQUEST_TIMEOUT = 60
OVERLAP_MINUTES = 10

# 현재 OpenAPI 참고자료 기준 서비스 시작일
SERVICE_START = "202501060000"


# =============================================================================
# 공식 고정 코드
# =============================================================================

REGION_CODES = [
    ("00", "전국"),
    ("11", "서울특별시"),
    ("12", "전남광주통합특별시"),
    ("26", "부산광역시"),
    ("27", "대구광역시"),
    ("28", "인천광역시"),
    ("29", "광주광역시"),
    ("30", "대전광역시"),
    ("31", "울산광역시"),
    ("36", "세종특별자치시"),
    ("41", "경기도"),
    ("42", "강원도"),
    ("43", "충청북도"),
    ("44", "충청남도"),
    ("45", "전라북도"),
    ("46", "전라남도"),
    ("47", "경상북도"),
    ("48", "경상남도"),
    ("50", "제주도"),
    ("51", "강원특별자치도"),
    ("52", "전북특별자치도"),
    ("99", "기타"),
]

INTERNATIONAL_DIVISION_CODES = [
    ("1", "국내"),
    ("2", "국제"),
]


# =============================================================================
# 경로
# =============================================================================

PROJECT_ROOT = Path(__file__).resolve().parents[2]

ENV_PATH = PROJECT_ROOT / ".env"

DATA_DIR = PROJECT_ROOT / "data"
MASTER_DIR = DATA_DIR / "master"
STATE_DIR = DATA_DIR / "state"
CONFLICT_DIR = MASTER_DIR / "conflicts"

STATE_FILE = STATE_DIR / "code_master_state.json"
USAGE_FILE = STATE_DIR / "g2b_call_usage.json"

for directory in (
    MASTER_DIR,
    STATE_DIR,
    CONFLICT_DIR,
):
    directory.mkdir(parents=True, exist_ok=True)


# =============================================================================
# 환경변수 / API Key
# =============================================================================

load_dotenv(ENV_PATH)

SERVICE_KEY_RAW = os.getenv("G2B_SERVICE_KEY")

if not SERVICE_KEY_RAW:
    raise RuntimeError(
        "G2B_SERVICE_KEY가 없습니다.\n"
        f".env 경로: {ENV_PATH}"
    )

# 공공데이터포털 Encoding Key:
#   abc%2Bdef%2F...
#
# Decoding Key:
#   abc+def/...
#
# 어느 쪽을 넣어도 decoded 상태로 정규화한 뒤,
# requests가 URL encoding을 딱 한 번만 수행하게 한다.
SERVICE_KEY = unquote(SERVICE_KEY_RAW.strip())


# =============================================================================
# 예외
# =============================================================================

class DailyBudgetReached(RuntimeError):
    pass


class ApiError(RuntimeError):
    pass


# =============================================================================
# 공통 유틸
# =============================================================================

def now_kst() -> datetime:
    return datetime.now(KST)


def clean(value) -> str:
    if value is None:
        return ""
    return str(value).strip()


def fmt12(value: datetime) -> str:
    return value.strftime("%Y%m%d%H%M")


def parse12(value: str) -> datetime:
    return datetime.strptime(
        value,
        "%Y%m%d%H%M",
    ).replace(tzinfo=KST)


def load_json(path: Path, default=None):
    if default is None:
        default = {}

    if not path.exists():
        return default.copy()

    try:
        return json.loads(
            path.read_text(encoding="utf-8")
        )
    except (json.JSONDecodeError, OSError):
        return default.copy()


def save_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)

    temp_path = path.with_suffix(
        path.suffix + ".tmp"
    )

    temp_path.write_text(
        json.dumps(
            data,
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    temp_path.replace(path)


# state 폴더/파일을 실행 시작 즉시 생성한다.
state = load_json(STATE_FILE)
save_json(STATE_FILE, state)


# =============================================================================
# 호출량 관리
# =============================================================================

def load_usage() -> dict:
    today = now_kst().date().isoformat()

    usage = load_json(
        USAGE_FILE,
        {
            "date": today,
            "used": 0,
        },
    )

    if usage.get("date") != today:
        usage = {
            "date": today,
            "used": 0,
        }

    save_json(USAGE_FILE, usage)

    return usage


# usage 파일도 실행 시작 즉시 생성
load_usage()


def consume_call(daily_limit: int) -> None:
    usage = load_usage()

    used = int(
        usage.get("used", 0)
    )

    if used >= daily_limit:
        raise DailyBudgetReached(
            f"오늘 이 스크립트의 안전한도 "
            f"{daily_limit}회에 도달했습니다."
        )

    # HTTP/API 오류도 실제 요청 1회로 계산될 수 있으므로
    # 요청을 보내기 전에 증가시킨다.
    usage["used"] = used + 1

    save_json(
        USAGE_FILE,
        usage,
    )


def usage_summary(daily_limit: int) -> str:
    usage = load_usage()

    used = int(
        usage.get("used", 0)
    )

    return (
        f"{used}/{daily_limit}회 "
        f"(공식 1000회 중 최소 "
        f"{1000 - daily_limit}회 예비)"
    )


# =============================================================================
# API
# =============================================================================

def normalize_items(data: dict):
    if "OpenAPI_ServiceResponse" in data:
        raise ApiError(
            "공공데이터포털 오류:\n"
            + json.dumps(
                data["OpenAPI_ServiceResponse"],
                ensure_ascii=False,
                indent=2,
            )
        )

    response = data.get(
        "response",
        {},
    )

    header = response.get(
        "header",
        {},
    )

    result_code = str(
        header.get("resultCode", "")
    )

    result_msg = clean(
        header.get("resultMsg")
    )

    if result_code not in ("00", "0"):
        raise ApiError(
            f"API 오류: "
            f"{result_code} / {result_msg}"
        )

    body = response.get(
        "body",
        {},
    )

    total_count = int(
        body.get("totalCount") or 0
    )

    returned_rows = int(
        body.get("numOfRows")
        or PAGE_SIZE
    )

    items = body.get(
        "items",
        [],
    )

    if items is None:
        items = []

    if isinstance(items, dict):
        if "item" in items:
            items = items["item"]
        else:
            items = [items]

    if not isinstance(items, list):
        items = [items]

    return (
        items,
        total_count,
        returned_rows,
    )


def api_request(
    endpoint: str,
    params: dict,
    daily_limit: int,
):
    consume_call(
        daily_limit
    )

    url = (
        f"{BASE_URL}/{endpoint}"
    )

    request_params = {
        "ServiceKey": SERVICE_KEY,
        "type": "json",
        **params,
    }

    try:
        response = requests.get(
            url,
            params=request_params,
            timeout=REQUEST_TIMEOUT,
        )
    except requests.RequestException as exc:
        raise ApiError(
            f"{endpoint} 요청 실패: {exc}"
        ) from exc

    if response.status_code != 200:
        raise ApiError(
            f"{endpoint} HTTP "
            f"{response.status_code}\n"
            f"{response.text[:3000]}"
        )

    try:
        data = response.json()
    except requests.exceptions.JSONDecodeError as exc:
        raise ApiError(
            f"{endpoint} JSON 파싱 실패\n"
            f"{response.text[:3000]}"
        ) from exc

    return normalize_items(
        data
    )


# =============================================================================
# Master 저장
# =============================================================================

def dataframe_from_pairs(
    pairs: list[tuple[str, str]],
):
    if not pairs:
        return pd.DataFrame(
            columns=["code", "name"]
        )

    df = pd.DataFrame(
        pairs,
        columns=["code", "name"],
    )

    df["code"] = (
        df["code"]
        .astype(str)
        .str.strip()
    )

    df["name"] = (
        df["name"]
        .astype(str)
        .str.strip()
    )

    df = df[
        (df["code"] != "")
        & (df["name"] != "")
    ]

    return df.drop_duplicates()


def merge_master(
    filename: str,
    pairs: list[tuple[str, str]],
):
    path = (
        MASTER_DIR
        / filename
    )

    new_df = dataframe_from_pairs(
        pairs
    )

    if path.exists():
        old_df = pd.read_csv(
            path,
            dtype=str,
            keep_default_na=False,
        )

        old_df = old_df[
            ["code", "name"]
        ]

        merged = pd.concat(
            [
                old_df,
                new_df,
            ],
            ignore_index=True,
        )
    else:
        merged = new_df.copy()

    if merged.empty:
        final_df = pd.DataFrame(
            columns=["code", "name"]
        )
    else:
        merged["code"] = (
            merged["code"]
            .astype(str)
            .str.strip()
        )

        merged["name"] = (
            merged["name"]
            .astype(str)
            .str.strip()
        )

        merged = merged[
            (merged["code"] != "")
            & (merged["name"] != "")
        ]

        # 완전히 같은 code/name 제거
        merged = (
            merged
            .drop_duplicates(
                subset=[
                    "code",
                    "name",
                ],
                keep="last",
            )
        )

        # 동일 code에 서로 다른 name이 관측된 경우
        # master에서 조용히 날리지 않고 conflicts에 보존
        name_counts = (
            merged
            .groupby("code")["name"]
            .nunique()
        )

        conflict_codes = (
            name_counts[
                name_counts > 1
            ].index
        )

        conflict_path = (
            CONFLICT_DIR
            / (
                f"{Path(filename).stem}"
                "_conflicts.csv"
            )
        )

        if len(conflict_codes) > 0:
            conflicts = (
                merged[
                    merged["code"].isin(
                        conflict_codes
                    )
                ]
                .sort_values(
                    [
                        "code",
                        "name",
                    ]
                )
            )

            conflicts.to_csv(
                conflict_path,
                index=False,
                encoding="utf-8-sig",
            )
        elif conflict_path.exists():
            conflict_path.unlink()

        # 본 master에는 같은 코드 1건만 유지
        # 새 관측값이 뒤에 붙으므로 최신 관측 명칭 우선
        final_df = (
            merged
            .drop_duplicates(
                subset=["code"],
                keep="last",
            )
            .sort_values(
                [
                    "code",
                    "name",
                ]
            )
            .reset_index(drop=True)
        )

    final_df.to_csv(
        path,
        index=False,
        encoding="utf-8-sig",
    )

    return len(final_df)


# =============================================================================
# 코드 파싱
# =============================================================================

# 예:
#   정보통신공사업/0036
#   [업종A/0003,업종B/1494]
#
# 업종코드는 참고자료 기준 4자리
NAME_CODE_RE = re.compile(
    r"([^,\[\]]+?)/(\d{4})(?=[,\]\s]|$)"
)


def extract_name_code_pairs(value):
    text = clean(value)

    if not text:
        return []

    pairs = []

    for name, code in (
        NAME_CODE_RE.findall(text)
    ):
        name = (
            clean(name)
            .strip("[]")
        )

        code = clean(code)

        if name and code:
            pairs.append(
                (
                    code,
                    name,
                )
            )

    return pairs


def handle_license_items(
    items: list[dict],
):
    license_pairs = []
    industry_pairs = []

    for item in items:
        # 면허제한명
        # 예: 정보통신공사업/0036
        current_pairs = (
            extract_name_code_pairs(
                item.get("lcnsLmtNm")
            )
        )

        license_pairs.extend(
            current_pairs
        )

        # 검색용 업종코드 후보에도 포함
        industry_pairs.extend(
            current_pairs
        )

        # 허용업종목록
        # 예: [업종명/코드,업종명/코드]
        industry_pairs.extend(
            extract_name_code_pairs(
                item.get(
                    "permsnIndstrytyList"
                )
            )
        )

    license_count = merge_master(
        "license_codes.csv",
        license_pairs,
    )

    industry_count = merge_master(
        "industry_codes.csv",
        industry_pairs,
    )

    print(
        f"    master: "
        f"license={license_count}, "
        f"industry={industry_count}"
    )


def handle_product_items(
    items: list[dict],
):
    # 실제 검색조건으로 쓸 10자리 세부품명번호
    product_pairs = []

    # 필요시 기관 검색에 재활용
    institution_pairs = []

    for item in items:
        code = clean(
            item.get(
                "dtilPrdctClsfcNo"
            )
        )

        name = clean(
            item.get(
                "dtilPrdctClsfcNoNm"
            )
        )

        if code and name:
            product_pairs.append(
                (
                    code,
                    name,
                )
            )

        code = clean(
            item.get(
                "dminsttCd"
            )
        )

        name = clean(
            item.get(
                "dminsttNm"
            )
        )

        if code and name:
            institution_pairs.append(
                (
                    code,
                    name,
                )
            )

    product_count = merge_master(
        "product_codes.csv",
        product_pairs,
    )

    institution_count = merge_master(
        "institution_codes.csv",
        institution_pairs,
    )

    print(
        f"    master: "
        f"product={product_count}, "
        f"institution={institution_count}"
    )


# =============================================================================
# 조회 상태
# =============================================================================

def get_dataset_state(
    dataset_key: str,
):
    global state

    if dataset_key not in state:
        state[dataset_key] = {}

    return state[dataset_key]


def save_state():
    save_json(
        STATE_FILE,
        state,
    )


def master_mtime_start(
    filenames: list[str],
):
    """
    이전 버전으로 이미 master를 만든 상태인데 state가 없는 경우:
    master 파일의 최신 수정시각을 임시 checkpoint로 사용한다.

    정확한 과거 coverage를 증명하는 값은 아니므로 10분 overlap을 둔다.
    현재 사용자처럼 방금 구버전 수집을 끝낸 상태에서
    동일 7일을 다시 긁는 낭비를 막기 위한 호환 처리.
    """
    mtimes = []

    for filename in filenames:
        path = (
            MASTER_DIR
            / filename
        )

        if path.exists():
            mtimes.append(
                path.stat().st_mtime
            )

    if not mtimes:
        return None

    latest = max(mtimes)

    return (
        datetime.fromtimestamp(
            latest,
            tz=KST,
        )
        - timedelta(
            minutes=OVERLAP_MINUTES
        )
    ).replace(
        second=0,
        microsecond=0,
    )


def determine_start(
    dataset_key: str,
    explicit_start: str | None,
    master_files: list[str],
):
    dataset_state = (
        get_dataset_state(
            dataset_key
        )
    )

    if explicit_start:
        return parse12(
            explicit_start
        )

    completed_until = (
        dataset_state.get(
            "completed_until"
        )
    )

    if completed_until:
        return (
            parse12(
                completed_until
            )
            - timedelta(
                minutes=OVERLAP_MINUTES
            )
        )

    # 구버전으로 master는 이미 있는데
    # 새 state 파일만 없는 경우 중복 대량호출 방지
    inferred = master_mtime_start(
        master_files
    )

    if inferred is not None:
        print(
            f"  기존 master 감지: "
            f"파일 수정시각 기준 "
            f"{OVERLAP_MINUTES}분 overlap부터 이어받습니다."
        )

        return inferred

    # 완전 최초 실행
    return parse12(
        SERVICE_START
    )


# =============================================================================
# 기간 / 페이지 수집
# =============================================================================

def iter_windows(
    start: datetime,
    end: datetime,
    window_days: int,
):
    cursor = start

    while cursor <= end:
        window_end = min(
            end,
            (
                cursor
                + timedelta(
                    days=window_days
                )
                - timedelta(
                    minutes=1
                )
            ),
        )

        yield (
            cursor,
            window_end,
        )

        cursor = (
            window_end
            + timedelta(minutes=1)
        )


def collect_one_window(
    *,
    dataset_key: str,
    endpoint: str,
    start: datetime,
    end: datetime,
    handler,
    daily_limit: int,
):
    """
    한 기간 묶음 수집.

    page 단위로 resume 정보를 저장하므로
    안전한도 도달/강제 종료 후 다음 실행에서 이어받을 수 있다.
    """
    dataset_state = (
        get_dataset_state(
            dataset_key
        )
    )

    start_s = fmt12(start)
    end_s = fmt12(end)

    resume = (
        dataset_state.get(
            "resume"
        )
        or {}
    )

    same_window_resume = (
        resume.get("start")
        == start_s
        and resume.get("end")
        == end_s
        and int(
            resume.get(
                "next_page",
                0,
            )
        ) >= 2
        and int(
            resume.get(
                "total_pages",
                0,
            )
        ) >= 1
    )

    if same_window_resume:
        next_page = int(
            resume["next_page"]
        )

        total_pages = int(
            resume["total_pages"]
        )

        print(
            f"    재개: "
            f"page {next_page}/"
            f"{total_pages}"
        )

    else:
        params = {
            "inqryDiv": "1",
            "inqryBgnDt": start_s,
            "inqryEndDt": end_s,
            "pageNo": 1,
            "numOfRows": PAGE_SIZE,
        }

        items, total_count, returned_rows = (
            api_request(
                endpoint,
                params,
                daily_limit,
            )
        )

        handler(
            items
        )

        total_pages = (
            ceil(
                total_count
                / max(
                    1,
                    returned_rows,
                )
            )
            if total_count > 0
            else 1
        )

        print(
            f"    page 1/"
            f"{total_pages}: "
            f"{len(items)}건 "
            f"(totalCount="
            f"{total_count})"
        )

        next_page = 2

        dataset_state[
            "resume"
        ] = {
            "start": start_s,
            "end": end_s,
            "next_page": next_page,
            "total_pages": total_pages,
        }

        save_state()

    while (
        next_page
        <= total_pages
    ):
        params = {
            "inqryDiv": "1",
            "inqryBgnDt": start_s,
            "inqryEndDt": end_s,
            "pageNo": next_page,
            "numOfRows": PAGE_SIZE,
        }

        items, _, _ = (
            api_request(
                endpoint,
                params,
                daily_limit,
            )
        )

        handler(
            items
        )

        print(
            f"    page "
            f"{next_page}/"
            f"{total_pages}: "
            f"{len(items)}건"
        )

        next_page += 1

        dataset_state[
            "resume"
        ] = {
            "start": start_s,
            "end": end_s,
            "next_page": next_page,
            "total_pages": total_pages,
        }

        save_state()

    # 이 window 완주
    dataset_state[
        "completed_until"
    ] = end_s

    dataset_state.pop(
        "resume",
        None,
    )

    save_state()


def collect_dataset(
    *,
    dataset_key: str,
    endpoint: str,
    start: datetime,
    end: datetime,
    handler,
    window_days: int,
    daily_limit: int,
):
    dataset_state = (
        get_dataset_state(
            dataset_key
        )
    )

    # 중간 페이지 resume가 있으면
    # 그 window를 무조건 먼저 이어받는다.
    resume = (
        dataset_state.get(
            "resume"
        )
        or {}
    )

    if (
        resume.get("start")
        and resume.get("end")
    ):
        resume_start = parse12(
            resume["start"]
        )

        resume_end = parse12(
            resume["end"]
        )

        print(
            f"  미완료 구간 재개: "
            f"{resume['start']} "
            f"~ {resume['end']}"
        )

        collect_one_window(
            dataset_key=dataset_key,
            endpoint=endpoint,
            start=resume_start,
            end=resume_end,
            handler=handler,
            daily_limit=daily_limit,
        )

        start = (
            resume_end
            + timedelta(minutes=1)
        )

    if start > end:
        print(
            "  새로 조회할 기간이 없습니다."
        )
        return

    for window_start, window_end in (
        iter_windows(
            start,
            end,
            window_days,
        )
    ):
        print(
            f"  조회: "
            f"{fmt12(window_start)} "
            f"~ {fmt12(window_end)}"
        )

        collect_one_window(
            dataset_key=dataset_key,
            endpoint=endpoint,
            start=window_start,
            end=window_end,
            handler=handler,
            daily_limit=daily_limit,
        )


# =============================================================================
# 인자
# =============================================================================

def parse_args():
    parser = ArgumentParser(
        description=(
            "나라장터 검색/매칭용 "
            "코드-명칭 master 수집"
        )
    )

    parser.add_argument(
        "--start",
        default=None,
        help=(
            "강제로 조회 시작시각 지정 "
            "YYYYMMDDHHMM. "
            "미지정 시 state 기준 증분 수집."
        ),
    )

    parser.add_argument(
        "--end",
        default=fmt12(
            now_kst()
        ),
        help=(
            "조회 종료시각 "
            "YYYYMMDDHHMM "
            "(기본: 현재)"
        ),
    )

    parser.add_argument(
        "--window-days",
        type=int,
        default=DEFAULT_WINDOW_DAYS,
        help=(
            "한 요청 기간 묶음 일수 "
            f"(기본 {DEFAULT_WINDOW_DAYS}일)"
        ),
    )

    parser.add_argument(
        "--daily-limit",
        type=int,
        default=DEFAULT_DAILY_SAFE_LIMIT,
        help=(
            "이 스크립트의 KST 일일 "
            "안전한도 "
            f"(기본 {DEFAULT_DAILY_SAFE_LIMIT}회)"
        ),
    )

    parser.add_argument(
        "--include-products",
        action="store_true",
        help=(
            "세부품명번호/기관 master도 "
            "추가 수집. 기본은 호출하지 않음."
        ),
    )

    return parser.parse_args()


# =============================================================================
# main
# =============================================================================

def main():
    global state

    args = parse_args()

    if args.window_days < 1:
        raise ValueError(
            "--window-days는 "
            "1 이상이어야 합니다."
        )

    if not (
        1
        <= args.daily_limit
        <= 999
    ):
        raise ValueError(
            "--daily-limit는 "
            "1~999 사이여야 합니다."
        )

    end = parse12(
        args.end
    )

    # API 0회
    region_count = merge_master(
        "region_codes.csv",
        REGION_CODES,
    )

    intl_count = merge_master(
        "international_division_codes.csv",
        INTERNATIONAL_DIVISION_CODES,
    )

    print("=" * 80)
    print(
        "나라장터 코드-명칭 Master 수집"
    )
    print("=" * 80)

    print(
        f"프로젝트       : "
        f"{PROJECT_ROOT}"
    )

    print(
        f"페이지당       : "
        f"{PAGE_SIZE}건"
    )

    print(
        f"기간 묶음      : "
        f"{args.window_days}일"
    )

    print(
        f"호출량         : "
        f"{usage_summary(args.daily_limit)}"
    )

    print(
        f"고정 코드       : "
        f"region={region_count}, "
        f"international={intl_count} "
        f"(API 0회)"
    )

    print()

    try:
        # ---------------------------------------------------------------------
        # 면허 / 업종
        # ---------------------------------------------------------------------

        print(
            "[1] 면허 / 업종 코드"
        )

        license_start = (
            determine_start(
                "license",
                args.start,
                [
                    "license_codes.csv",
                    "industry_codes.csv",
                ],
            )
        )

        print(
            f"  대상: "
            f"{fmt12(license_start)} "
            f"~ {fmt12(end)}"
        )

        collect_dataset(
            dataset_key="license",
            endpoint=LICENSE_ENDPOINT,
            start=license_start,
            end=end,
            handler=handle_license_items,
            window_days=args.window_days,
            daily_limit=args.daily_limit,
        )

        # ---------------------------------------------------------------------
        # 물품 세부품명 / 기관 - 선택 실행
        # ---------------------------------------------------------------------

        if args.include_products:
            print()
            print(
                "[2] 세부품명 / 기관 코드"
            )

            product_start = (
                determine_start(
                    "product",
                    args.start,
                    [
                        "product_codes.csv",
                        "institution_codes.csv",
                    ],
                )
            )

            print(
                f"  대상: "
                f"{fmt12(product_start)} "
                f"~ {fmt12(end)}"
            )

            collect_dataset(
                dataset_key="product",
                endpoint=PRODUCT_ENDPOINT,
                start=product_start,
                end=end,
                handler=handle_product_items,
                window_days=args.window_days,
                daily_limit=args.daily_limit,
            )

    except DailyBudgetReached as exc:
        print()
        print("=" * 80)
        print(
            "일일 안전한도 도달 - 정상 중단"
        )
        print("=" * 80)
        print(exc)
        print(
            "현재 페이지/기간은 state에 저장되어 "
            "다음 실행에서 이어받습니다."
        )

    except ApiError as exc:
        print()
        print("=" * 80)
        print(
            "API 오류 - 추가 호출 중단"
        )
        print("=" * 80)
        print(exc)
        print(
            "인증/할당량/요청 오류 상태에서 "
            "자동 재시도하지 않습니다."
        )

    finally:
        print()
        print("=" * 80)
        print(
            "현재 상태"
        )
        print("=" * 80)

        print(
            f"호출량 : "
            f"{usage_summary(args.daily_limit)}"
        )

        print(
            f"Master : "
            f"{MASTER_DIR}"
        )

        print(
            f"State  : "
            f"{STATE_DIR}"
        )


if __name__ == "__main__":
    main()

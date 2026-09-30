from dataclasses import dataclass
from datetime import datetime
import json
from typing import Any
from zoneinfo import ZoneInfo

import requests

from ..schemas import BusinessType, NoticeInquiryType
from .json_safety import sanitize_json_value


KST = ZoneInfo("Asia/Seoul")

ENDPOINT_BY_BUSINESS_TYPE = {
    BusinessType.SERVICE: "getBidPblancListInfoServc",
    BusinessType.GOODS: "getBidPblancListInfoThng",
    BusinessType.CONSTRUCTION: "getBidPblancListInfoCnstwk",
    BusinessType.FOREIGN: "getBidPblancListInfoFrgcpt",
    BusinessType.OTHER: "getBidPblancListInfoEtc",
}

CHANGE_HISTORY_ENDPOINT_BY_BUSINESS_TYPE = {
    BusinessType.SERVICE: "getBidPblancListInfoChgHstryServc",
    BusinessType.GOODS: "getBidPblancListInfoChgHstryThng",
    BusinessType.CONSTRUCTION: "getBidPblancListInfoChgHstryCnstwk",
}

INQUIRY_DIVISION = {
    NoticeInquiryType.REGISTERED: "1",
    NoticeInquiryType.NOTICE_NUMBER: "2",
    NoticeInquiryType.CHANGED: "3",
}


class G2BApiError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(f"{code}: {message}")


@dataclass(frozen=True)
class G2BPage:
    items: list[dict[str, Any]]
    total_count: int
    page_number: int
    page_size: int
    endpoint: str


def _format_query_datetime(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=KST)
    else:
        value = value.astimezone(KST)
    return value.strftime("%Y%m%d%H%M")


class G2BClient:
    def __init__(
        self,
        service_key: str,
        base_url: str,
        timeout_seconds: float = 30.0,
        session: requests.Session | None = None,
    ) -> None:
        if not service_key.strip():
            raise ValueError("G2B_SERVICE_KEY is not configured")
        self._service_key = service_key
        self._base_url = base_url.rstrip("/")
        self._timeout_seconds = timeout_seconds
        self._session = session or requests.Session()

    def fetch_page(
        self,
        *,
        business_type: BusinessType,
        inquiry_type: NoticeInquiryType,
        page_number: int,
        page_size: int,
        window_started_at: datetime | None = None,
        window_ended_at: datetime | None = None,
        bid_notice_no: str | None = None,
    ) -> G2BPage:
        endpoint = ENDPOINT_BY_BUSINESS_TYPE[business_type]
        params: dict[str, str | int] = {
            "serviceKey": self._service_key,
            "pageNo": page_number,
            "numOfRows": page_size,
            "type": "json",
            "inqryDiv": INQUIRY_DIVISION[inquiry_type],
        }
        if inquiry_type == NoticeInquiryType.NOTICE_NUMBER:
            if bid_notice_no is None:
                raise ValueError("bid_notice_no is required")
            params["bidNtceNo"] = bid_notice_no
        else:
            if window_started_at is None or window_ended_at is None:
                raise ValueError("collection window is required")
            params["inqryBgnDt"] = _format_query_datetime(window_started_at)
            params["inqryEndDt"] = _format_query_datetime(window_ended_at)

        return self._fetch_json_page(endpoint=endpoint, params=params)

    def fetch_change_history_page(
        self,
        *,
        business_type: BusinessType,
        page_number: int = 1,
        page_size: int = 100,
        bid_notice_no: str | None = None,
        window_started_at: datetime | None = None,
        window_ended_at: datetime | None = None,
    ) -> G2BPage:
        """Fetch G2B's authoritative field-level change history for one notice."""

        endpoint = CHANGE_HISTORY_ENDPOINT_BY_BUSINESS_TYPE.get(business_type)
        if endpoint is None:
            raise ValueError(
                "change history is available only for SERVICE, GOODS, and CONSTRUCTION"
            )
        params: dict[str, str | int] = {
            "serviceKey": self._service_key,
            "pageNo": page_number,
            "numOfRows": page_size,
            "type": "json",
        }
        if bid_notice_no is not None:
            params["inqryDiv"] = "2"
            params["bidNtceNo"] = bid_notice_no
        else:
            if window_started_at is None or window_ended_at is None:
                raise ValueError("bid_notice_no or collection window is required")
            params["inqryDiv"] = "1"
            params["inqryBgnDt"] = _format_query_datetime(window_started_at)
            params["inqryEndDt"] = _format_query_datetime(window_ended_at)
        return self._fetch_json_page(endpoint=endpoint, params=params)

    def _fetch_json_page(
        self,
        *,
        endpoint: str,
        params: dict[str, str | int],
    ) -> G2BPage:
        page_number = int(params["pageNo"])
        page_size = int(params["numOfRows"])
        try:
            response = self._session.get(
                f"{self._base_url}/{endpoint}",
                params=params,
                timeout=self._timeout_seconds,
            )
            response.raise_for_status()
            # The API declares UTF-8, but relying on guessed encoding can corrupt
            # Korean text on some Windows environments.
            payload = sanitize_json_value(
                json.loads(response.content.decode("utf-8"))
            )
        except (requests.RequestException, UnicodeDecodeError, ValueError) as error:
            # Request exception strings can contain the service key in the URL.
            raise G2BApiError(
                "G2B_TRANSPORT_ERROR",
                f"나라장터 API 호출 또는 응답 해석에 실패했습니다. ({type(error).__name__})",
            ) from error

        root = payload.get("response", {}) if isinstance(payload, dict) else {}
        header = root.get("header", {}) or {}
        result_code = str(header.get("resultCode", ""))
        if result_code != "00":
            raise G2BApiError(
                result_code or "G2B_INVALID_RESPONSE",
                str(header.get("resultMsg") or "나라장터 API 응답 형식이 올바르지 않습니다."),
            )

        body = root.get("body", {}) or {}
        raw_items = body.get("items", [])
        if isinstance(raw_items, dict):
            raw_items = raw_items.get("item", raw_items)
        if isinstance(raw_items, dict):
            items = [raw_items]
        elif isinstance(raw_items, list):
            items = [item for item in raw_items if isinstance(item, dict)]
        else:
            items = []

        return G2BPage(
            items=items,
            total_count=int(body.get("totalCount") or 0),
            page_number=int(body.get("pageNo") or page_number),
            page_size=int(body.get("numOfRows") or page_size),
            endpoint=endpoint,
        )

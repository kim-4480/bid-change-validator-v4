"""Client hints select references; backend receipts establish their freshness."""

import re
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StrictInt, field_validator

from .contracts import ProductProvenance, RevalidationProvenance


class ProductReceipt(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["product"] = "product"
    provenance: ProductProvenance


class RevalidationReceipt(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["revalidation"] = "revalidation"
    provenance: RevalidationProvenance


ReadReceipt = Annotated[ProductReceipt | RevalidationReceipt, Field(discriminator="kind")]


class ConversationContext(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_id: UUID | None = None
    context_revision: StrictInt = Field(default=0, ge=0)
    source_page: Literal["QUALIFICATION", "ASK_BACK", "EVIDENCE", "CHANGES"] | None = None
    last_response_intent: str | None = Field(default=None, max_length=64)
    visible_requirement_keys: list[str] = Field(default_factory=list, max_length=100)
    last_read_receipt: ReadReceipt | None = None

    @field_validator("visible_requirement_keys")
    @classmethod
    def valid_keys(cls, keys):
        if len(set(keys)) != len(keys) or any(not k.strip() or len(k) > 200 for k in keys):
            raise ValueError("visible requirement keys must be unique, nonempty and bounded")
        return keys


class ReplyContext(BaseModel):
    request_id: UUID | None = None
    context_revision: int = 0
    status: Literal["RESOLVED", "NEEDS_CONTEXT", "NEEDS_TARGET", "STALE_CONTEXT", "UNSUPPORTED"] = "RESOLVED"
    requirement_key: str | None = None
    visible_requirement_keys: list[str] = Field(default_factory=list)
    last_read_receipt: ReadReceipt | None = None


def read_receipt(provenance):
    if isinstance(provenance, ProductProvenance):
        return ProductReceipt(provenance=provenance)
    return RevalidationReceipt(provenance=provenance)


def compact(text: str) -> str:
    return re.sub(r"\s+", "", text).strip("?.!。？！")


ORDINAL = re.compile(r"([+-]?\d+(?:\.\d+)?|[가-힣]+)번째")
ORDINAL_WORDS = {word: i for i, word in enumerate(("첫", "두", "세", "네", "다섯", "여섯", "일곱", "여덟", "아홉", "열"), 1)}


def depends_on_context(message: str) -> bool:
    text = compact(message)
    return "번째" in text or text in ("왜", "왜그래", "이유는", "그러면", "그럼") or any(
        word in text for word in ("그조건", "그요건", "그항목", "그등록", "그중", "그것", "이조건", "해당요건")
    )


def resolve_context(message, requirement_key, hints, provenance, valid_keys):
    """Never reinterpret an old ordinal against a freshly sorted backend list."""
    reply = ReplyContext(
        request_id=hints.request_id if hints else None,
        context_revision=hints.context_revision if hints else 0,
        last_read_receipt=read_receipt(provenance),
        visible_requirement_keys=list(dict.fromkeys(valid_keys))[:100],
    )
    if depends_on_context(message):
        if not hints or not hints.last_read_receipt:
            reply.status = "NEEDS_CONTEXT"
            return reply
        if hints.last_read_receipt.kind != reply.last_read_receipt.kind:
            reply.status = "NEEDS_CONTEXT"
            return reply
        if hints.last_read_receipt != reply.last_read_receipt:
            reply.status = "STALE_CONTEXT"
            return reply
        if not set(hints.visible_requirement_keys) <= set(valid_keys):
            reply.status = "NEEDS_TARGET"
            return reply
        text = compact(message)
        if "번째" in text:
            # Detection and parsing share normalization. A detected but unparsed
            # ordinal must never become a focus/single-candidate fallback.
            ordinals = ORDINAL.findall(text)
            numbers = [int(n) if re.fullmatch(r"[+-]?\d+", n) else ORDINAL_WORDS.get(n, 0) for n in ordinals]
            if (len(numbers) != text.count("번째") or len(set(numbers)) != 1
                    or not 1 <= numbers[0] <= len(hints.visible_requirement_keys)):
                reply.status = "NEEDS_TARGET"
                return reply
            selected = hints.visible_requirement_keys[numbers[0] - 1]
            if requirement_key and requirement_key != selected:
                reply.status = "NEEDS_TARGET"
                return reply
            requirement_key = selected
        elif compact(message) not in ("왜", "왜그래", "이유는", "그러면", "그럼") and not requirement_key:
            if len(hints.visible_requirement_keys) != 1:
                reply.status = "NEEDS_TARGET"
                return reply
            requirement_key = hints.visible_requirement_keys[0]
    if requirement_key and requirement_key not in valid_keys:
        reply.status = "NEEDS_TARGET"
        return reply
    reply.requirement_key = requirement_key
    return reply

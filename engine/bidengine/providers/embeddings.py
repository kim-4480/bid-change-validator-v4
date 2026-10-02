"""Embedding adapters for clause matching.

Two places need to know whether two pieces of Korean legal text are about the
same thing:

1. Matching a clause in a notice against the standard clause it should be
   compared with (clause review, path A).
2. Aligning clauses of an old notice version against a corrected one, where
   matching by clause number is useless — inserting one clause renumbers
   everything after it.

Neither use decides anything. Embeddings only select *which* text to compare;
the comparison itself stays in code.

A character-bigram hashing vector is the built-in default, so the pipeline runs
with no API key and no network at all. `OpenAIEmbedder` is wired in by a caller
that wants better matching, following the same injection pattern as the
structured extractor.
"""

from __future__ import annotations

import hashlib
import math
import os
from collections.abc import Callable, Sequence
from typing import Any


Embedder = Callable[[list[str]], list[list[float]]]

_NGRAM_DIM = 4096

ClientFactory = Callable[[str], Any]


def ngram_vectors(texts: list[str], *, n: int = 2) -> list[list[float]]:
    """Hash character n-grams into a fixed-width vector.

    Crude next to a real embedding, but deterministic, free and offline, which is
    what makes it the right default: a missing API key degrades matching quality
    instead of stopping the review.
    """
    vectors: list[list[float]] = []
    for text in texts:
        vector = [0.0] * _NGRAM_DIM
        squashed = "".join((text or "").split())
        for index in range(max(0, len(squashed) - n + 1)):
            gram = squashed[index : index + n]
            slot = int(hashlib.md5(gram.encode("utf-8")).hexdigest(), 16) % _NGRAM_DIM
            vector[slot] += 1.0
        vectors.append(vector)
    return vectors


def _default_client_factory(api_key: str) -> Any:
    try:
        from openai import OpenAI
    except ImportError as error:  # pragma: no cover - depends on runtime extras
        raise RuntimeError(
            "OpenAI embedder requires the optional `openai` package at runtime"
        ) from error
    return OpenAI(api_key=api_key)


class OpenAIEmbedder:
    """Callable adapter returning one embedding vector per input text."""

    # Matching only needs the opening of a clause; sending the whole text costs
    # more and does not improve which clause is selected.
    max_input_chars = 4000

    def __init__(
        self,
        *,
        api_key: str | None = None,
        model: str | None = None,
        client_factory: ClientFactory | None = None,
    ) -> None:
        self.api_key = api_key or os.getenv("OPENAI_API_KEY")
        self.model = model or os.getenv("OPENAI_EMBED_MODEL") or "text-embedding-3-small"
        self._client_factory = client_factory or _default_client_factory
        self._client: Any | None = None

    @property
    def available(self) -> bool:
        return bool(self.api_key)

    def _get_client(self) -> Any:
        if not self.api_key:
            raise RuntimeError("OPENAI_API_KEY is not configured")
        if self._client is None:
            self._client = self._client_factory(self.api_key)
        return self._client

    def __call__(self, texts: list[str]) -> list[list[float]]:
        trimmed = [(text or " ")[: self.max_input_chars] for text in texts]
        response = self._get_client().embeddings.create(model=self.model, input=trimmed)
        data = getattr(response, "data", None)
        if not data:
            raise RuntimeError("OpenAI embedding response did not contain any data")
        return [item.embedding for item in data]


def cosine(left: Sequence[float], right: Sequence[float]) -> float:
    dot = sum(x * y for x, y in zip(left, right))
    left_norm = math.sqrt(sum(x * x for x in left))
    right_norm = math.sqrt(sum(x * x for x in right))
    if left_norm == 0 or right_norm == 0:
        return 0.0
    return dot / (left_norm * right_norm)


def similarity_matrix(
    texts_a: Sequence[str],
    texts_b: Sequence[str],
    *,
    embed: Embedder | None = None,
) -> tuple[list[list[float]], str]:
    """Cosine similarity of every a against every b, plus the method actually used.

    The method is returned rather than logged because a caller comparing scores
    needs to know whether they came from real embeddings or from the offline
    fallback — the two are not on the same scale.
    """
    all_texts = list(texts_a) + list(texts_b)
    if embed is None:
        vectors, method = ngram_vectors(all_texts), "ngram"
    else:
        vectors, method = embed(all_texts), "embedder"

    left = vectors[: len(texts_a)]
    right = vectors[len(texts_a) :]
    return [[cosine(a, b) for b in right] for a in left], method

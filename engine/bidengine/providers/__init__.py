"""Runtime provider adapters for the AI integration package.

Providers are intentionally isolated from Backend services/configuration. Importing
this package must not require an external SDK; concrete providers use lazy imports
when an actual network call is made.
"""

# NOTE(LLM/RAG 이식): 두 줄 다 이번에 추가했습니다.
#
# embeddings — 조항검토가 정규식으로 후보 청크를 여러 개 잡았을 때 표준 조문과
#   가까운 것을 고르는 데 씁니다. 기본 경로는 `ngram_vectors`(오프라인)라 모델을
#   부르지 않습니다. `OpenAIEmbedder`는 주입 지점만 열어둔 것이고 호출부가 없습니다
#   — 유사도가 판정 근거에 섞이면 "왜 이렇게 판정했나"를 설명할 수 없어서입니다.
# openai.OpenAINarrator — 요약·브리핑·질의응답처럼 모델이 산문을 쓰는 경로용입니다.
#   기존 StructuredExtractor는 JSON 스키마 고정 출력 전용이라 분리했습니다.
from bidengine.providers.embeddings import Embedder, OpenAIEmbedder, ngram_vectors, similarity_matrix
from bidengine.providers.openai import OpenAINarrator, OpenAIStructuredExtractor

__all__ = [
    "OpenAIStructuredExtractor",
    "OpenAINarrator",
    "OpenAIEmbedder",
    "Embedder",
    "ngram_vectors",
    "similarity_matrix",
]

"""LangChain adapters over the existing scoped store and model budget.

This module owns no credential, retry, persistence, or judgment path.  The
Copilot gateway keeps those boundaries while LangChain supplies the retriever
and prompt/runnable composition required by the project architecture.
"""

import json
from time import monotonic
from typing import Any

from langchain_core.documents import Document
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.retrievers import BaseRetriever
from langchain_core.runnables import RunnableLambda
from pydantic import Field


PROMPT_VERSION = "copilot-guided-grounded-v1"


class CurrentVersionRetriever(BaseRetriever):
    readiness: Any
    broad: bool = False
    details: dict = Field(default_factory=dict)

    def _get_relevant_documents(self, query, *, run_manager):
        from bidengine.rag.readiness import read_passages

        started = monotonic()
        records, details = read_passages(self.readiness, query, broad=self.broad)
        self.details = {
            **details,
            "retriever": "langchain.CurrentVersionRetriever",
            "retrieval_ms": round((monotonic() - started) * 1000),
        }
        return [
            Document(page_content=record.text, metadata=record.metadata.model_dump(mode="json"))
            for record in records
        ]


def retrieve_current(readiness, question, *, broad=False):
    from bidengine.rag.store import DocumentChunkRecord

    retriever = CurrentVersionRetriever(readiness=readiness, broad=broad)
    documents = retriever.invoke(
        question, config={"run_name": "copilot.current_version_retrieval"}
    )
    return [
        DocumentChunkRecord(text=document.page_content, metadata=document.metadata)
        for document in documents
    ], retriever.details


def structured_messages(system: str, payload: str, *, examples: bool = False):
    messages = [SystemMessage(content=system)]
    if examples:
        example = {
            "goal": "제출 자료의 기한과 준비 순서를 알려줘.",
            "evidence": {"facts": [
                {"fact_id": "F1", "source_quotes": [{"quote": "신청서는 2030년 4월 2일 15시까지 방문 제출한다."}]},
                {"fact_id": "F2", "source_quotes": [{"quote": "선정된 업체는 계약 체결 전에 보안계획서를 제출한다."}]},
            ]},
        }
        answer = {"claims": [
            {"claim_id": "example-1", "text": "신청서를 2030년 4월 2일 15시까지 방문 제출해야 합니다.", "fact_ids": ["F1"], "source_ids": ["S1"]},
            {"claim_id": "example-2", "text": "선정된 경우 보안계획서는 계약 체결 전에 제출해야 하며 날짜는 확인할 수 없습니다.", "fact_ids": ["F2"], "source_ids": ["S2"]},
        ]}
        messages.extend([
            HumanMessage(content=json.dumps(example, ensure_ascii=False)),
            AIMessage(content=json.dumps(answer, ensure_ascii=False)),
        ])
    messages.append(("human", "{payload}"))
    return ChatPromptTemplate.from_messages(messages).invoke({"payload": payload})


def invoke_structured(client, *, model, prompt, schema, output_limit, timeout):
    def send(prompt_value):
        roles = {"system": "system", "human": "user", "ai": "assistant"}
        return client.with_options(max_retries=0, timeout=timeout).chat.completions.parse(
            model=model,
            messages=[
                {"role": roles[message.type], "content": message.content}
                for message in prompt_value.to_messages()
            ],
            response_format=schema,
            max_completion_tokens=output_limit,
        )

    return RunnableLambda(send, name="copilot.budgeted_structured_model").invoke(prompt)

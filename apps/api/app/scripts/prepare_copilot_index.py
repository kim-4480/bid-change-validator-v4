"""Explicit single-version indexing. Default is read-only dry-run, never invoked by chat."""
import argparse
import json
from uuid import UUID


class ExplicitEmbeddings:
    """Untrimmed document embedding with one attempt and a total input cap."""
    def __init__(self, max_tokens):
        from openai import OpenAI
        self.client = OpenAI(max_retries=0, timeout=60)
        self.max_tokens = max_tokens
        self.used_upper = 0
        self.calls = []

    def embed_documents(self, texts):
        upper = sum(len(t.encode('utf-8')) for t in texts)
        if self.used_upper + upper > self.max_tokens:
            raise ValueError('EMBEDDING_BUDGET')
        self.used_upper += upper
        call = {'model': 'text-embedding-3-small', 'input_upper': upper, 'usage': None, 'status': 'started'}
        self.calls.append(call)
        try:
            result = self.client.embeddings.create(model=call['model'], input=texts)
            call.update(status='succeeded', usage=result.usage.model_dump())
            return [r.embedding for r in result.data]
        except Exception as error:
            call.update(status='failed', error=type(error).__name__)
            raise

    def embed_query(self, text):
        raise RuntimeError('Explicit build does not run query embeddings')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--version', required=True, type=UUID)
    parser.add_argument('--index-root', required=True)
    parser.add_argument('--execute-fingerprint')
    parser.add_argument('--max-embedding-tokens', type=int, default=0)
    args = parser.parse_args()
    from ..database import SessionLocal
    from ..document_rag.service import load_notice_version_for_rag
    from bidengine.rag.readiness import snapshot_sources, build_plan, publish_index
    with SessionLocal() as db:
        snapshot = snapshot_sources(load_notice_version_for_rag(db, args.version))
        print(json.dumps(build_plan(snapshot, args.index_root), ensure_ascii=False, indent=2))
        if args.execute_fingerprint:
            embeddings = ExplicitEmbeddings(args.max_embedding_tokens)
            try:
                generation = publish_index(snapshot, args.index_root, embeddings,
                                       expected_fingerprint=args.execute_fingerprint,
                                       max_embedding_tokens=args.max_embedding_tokens)
                print(json.dumps({'generation': generation}))
            finally:
                print(json.dumps({'embedding_calls': embeddings.calls}))


if __name__ == '__main__':
    main()

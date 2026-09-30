"""One bounded model attempt per call; retries and usage are never hidden."""
import json
import os
from time import monotonic

QUALITY_STAGES = {'generate', 'validate', 'repair', 'revalidate'}
LARGE_INPUT_BYTES = 240000
LARGE_OUTPUT_TOKENS = 6000


class BudgetExceeded(RuntimeError):
    pass


class ModelGateway:
    def __init__(self, *, client=None, model=None, deadline_seconds=45):
        self.started = monotonic()
        self.deadline = self.started + deadline_seconds
        self.model = model or os.getenv('COPILOT_MODEL') or os.getenv('OPENAI_MODEL_DEFAULT') or 'gpt-5.6-luna'
        self.client = client
        self.calls = []
        self.enabled = True
        self.allow_large_context = False
        self.large_context = False

    def call_limits(self, stage):
        if self.large_context and stage in QUALITY_STAGES:
            return LARGE_INPUT_BYTES, LARGE_OUTPUT_TOKENS
        return 16000, 3000

    @property
    def available(self):
        return self.client is not None or bool(os.getenv('OPENAI_API_KEY'))

    def remaining(self):
        return max(0, self.deadline - monotonic())

    def call(self, stage, system, body, schema):
        if not self.enabled:
            raise RuntimeError('MODEL_PROCESSING_DISABLED')
        quality = [c for c in self.calls if c['stage'] in QUALITY_STAGES]
        if (stage in QUALITY_STAGES and len(quality) >= 4) or self.remaining() < 1:
            raise BudgetExceeded('TURN_BUDGET')
        if stage == 'plan' and any(c['stage'] == 'plan' for c in self.calls):
            raise BudgetExceeded('PLAN_BUDGET')
        if stage == 'repair' and self.remaining() < 8:
            raise BudgetExceeded('REPAIR_AND_VALIDATION_BUDGET')
        from bidengine.rag.langchain_pipeline import PROMPT_VERSION, invoke_structured, structured_messages
        payload = json.dumps(body, ensure_ascii=False, default=str)
        prompt = structured_messages(system, payload, examples=stage in {'generate', 'repair'})
        # UTF-8 bytes is a conservative token upper bound; include the response schema.
        upper = len((
            ''.join(str(message.content) for message in prompt.to_messages())
            + json.dumps(schema.model_json_schema())
        ).encode('utf-8')) + 512
        if stage in QUALITY_STAGES and self.allow_large_context and upper > 16000:
            self.large_context = True
        input_limit, output_limit = self.call_limits(stage)
        if upper > input_limit:
            raise BudgetExceeded('INPUT_BUDGET')
        if not self.available:
            raise RuntimeError('MODEL_UNAVAILABLE')
        if self.client is None:
            from openai import OpenAI
            self.client = OpenAI(max_retries=0)
        entry = {'stage': stage, 'model': self.model, 'input_token_upper_bound': upper,
                 'usage': None, 'status': 'started', 'pipeline': 'langchain',
                 'prompt_version': PROMPT_VERSION, 'few_shot': stage in {'generate', 'repair'}}
        self.calls.append(entry)
        start = monotonic()
        try:
            response = invoke_structured(
                self.client,
                model=self.model,
                prompt=prompt,
                schema=schema,
                output_limit=output_limit,
                timeout=self.remaining(),
            )
            entry['usage'] = response.usage.model_dump() if response.usage else None
            if self.remaining() <= 0:
                raise BudgetExceeded('LATE_MODEL_RESULT')
            parsed = response.choices[0].message.parsed
            if parsed is None:
                raise RuntimeError('MODEL_REFUSAL')
            entry['status'] = 'succeeded'
            return schema.model_validate(parsed)
        except Exception as error:
            entry['status'] = 'failed'
            entry['error'] = type(error).__name__
            raise
        finally:
            entry['elapsed_ms'] = round((monotonic() - start) * 1000)

    def embed_query(self, text):
        if not self.enabled or not self.available or self.remaining() < 1 or len(text.encode('utf-8')) > 8000:
            raise BudgetExceeded('QUERY_EMBEDDING_BUDGET')
        if sum(c['stage'] == 'query_embedding' for c in self.calls) >= 3:
            raise BudgetExceeded('QUERY_EMBEDDING_CALLS')
        if self.client is None:
            from openai import OpenAI
            self.client = OpenAI(max_retries=0)
        entry = {'stage': 'query_embedding', 'model': 'text-embedding-3-small', 'usage': None, 'status': 'started'}
        self.calls.append(entry)
        start = monotonic()
        try:
            response = self.client.with_options(max_retries=0, timeout=self.remaining()).embeddings.create(
                model=entry['model'], input=[text])
            entry['usage'] = response.usage.model_dump() if response.usage else None
            if self.remaining() <= 0:
                raise BudgetExceeded('LATE_QUERY_EMBEDDING')
            entry['status'] = 'succeeded'
            return response.data[0].embedding
        except Exception as error:
            entry.update(status='failed', error=type(error).__name__)
            raise
        finally:
            entry['elapsed_ms'] = round((monotonic() - start) * 1000)

    def embed_documents(self, texts):
        raise RuntimeError('Chat cannot embed documents')

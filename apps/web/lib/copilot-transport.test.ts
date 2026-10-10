import assert from 'node:assert/strict';
import test from 'node:test';
import { buildCopilotTransport } from './copilot-transport.ts';

const request = { case_id: 'case-1', message: '공고문 근거를 설명해줘' };

void test('document-only consent uses public-document QA without semantic consent', () => {
  const { body, headers } = buildCopilotTransport({ ...request, document_processing: true });
  assert.equal(body.response_version, 'legacy');
  assert.equal(body.allow_external_processing, true);
  assert.equal(body.public_document_question, request.message);
  assert.equal(headers['X-Copilot-Semantic-Processing'], undefined);
});

void test('both consents retain the v3.1 conversation path', () => {
  const { body, headers } = buildCopilotTransport({
    ...request, semantic_processing: true, document_processing: true,
  });
  assert.equal(body.response_version, '3.1');
  assert.equal(body.allow_external_processing, true);
  assert.equal(headers['X-Copilot-Semantic-Processing'], 'true');
});

void test('semantic-only and no-consent requests do not send documents', () => {
  const semantic = buildCopilotTransport({ ...request, semantic_processing: true });
  const plain = buildCopilotTransport(request);
  assert.equal(semantic.body.response_version, '3.1');
  assert.equal(semantic.body.allow_external_processing, undefined);
  assert.equal(plain.body.response_version, '3.1');
  assert.equal(plain.body.allow_external_processing, undefined);
  assert.equal(plain.headers['X-Copilot-Semantic-Processing'], undefined);
});

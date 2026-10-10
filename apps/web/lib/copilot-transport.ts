import type { CopilotChatRequest } from './copilot-api';

export type CopilotTransportRequest = CopilotChatRequest & {
  semantic_processing?: boolean;
  document_processing?: boolean;
};

export function buildCopilotTransport(request: CopilotTransportRequest) {
  const { semantic_processing, document_processing, ...payload } = request;
  const body: CopilotChatRequest = document_processing ? {
    ...payload,
    public_document_question: payload.public_document_question ?? payload.message,
    allow_external_processing: true,
  } : payload;

  // Document consent covers only the public question and notice text. The legacy
  // document QA path keeps company/profile facts out of model input without
  // silently enabling the separate semantic-processing consent.
  const response_version = document_processing && !semantic_processing ? 'legacy' : '3.1';
  return {
    body: { ...body, response_version } satisfies CopilotChatRequest,
    headers: {
      'Content-Type': 'application/json',
      ...(semantic_processing ? { 'X-Copilot-Semantic-Processing': 'true' } : {}),
    },
  };
}

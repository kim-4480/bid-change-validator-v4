"""Bounded, single-process demo storage with owner checks and optimistic commits."""
from collections import OrderedDict
from threading import RLock
from time import monotonic
from uuid import uuid4

from ..errors import ApiError
from .v31_contracts import ConversationState


class ConversationRepository:
    def __init__(self, capacity=256, ttl=3600):
        self.capacity, self.ttl = capacity, ttl
        self._states = OrderedDict()
        self._lock = RLock()

    def load(self, owner, scope, conversation_id=None, revision=None):
        with self._lock:
            now = monotonic()
            for key, (_, touched) in list(self._states.items()):
                if now - touched > self.ttl:
                    del self._states[key]
            if conversation_id is None:
                state = ConversationState(conversation_id=uuid4(), owner=owner, scope=scope)
                self._states[state.conversation_id] = (state, now)
                while len(self._states) > self.capacity:
                    self._states.popitem(last=False)
                return state.model_copy(deep=True)
            record = self._states.get(conversation_id)
            if record is None:
                raise ApiError(409, 'CONVERSATION_EXPIRED', '대화가 만료되었습니다. 새 대화를 시작해 주세요.')
            state = record[0]
            if state.owner != owner or state.scope.case_id != scope.case_id or state.scope.company_id != scope.company_id:
                raise ApiError(403, 'CONVERSATION_ACCESS_DENIED', '이 대화에 접근할 수 없습니다.')
            if revision != state.context_revision:
                raise ApiError(409, 'CONVERSATION_STALE', '다른 질문이 먼저 처리되었습니다. 최신 대화에서 다시 질문해 주세요.')
            self._states.move_to_end(conversation_id)
            return state.model_copy(deep=True)

    def commit(self, state, expected_revision):
        with self._lock:
            current = self._states.get(state.conversation_id)
            if current is None or current[0].context_revision != expected_revision:
                raise ApiError(409, 'CONVERSATION_STALE', '대화 기준이 바뀌어 늦게 도착한 답변을 버렸습니다.')
            state.context_revision = expected_revision + 1
            state.messages = state.messages[-12:]
            # Keep several answer lists, not an unbounded copy of old evidence.
            state.targets = state.targets[-100:]
            self._states[state.conversation_id] = (state.model_copy(deep=True), monotonic())


conversations = ConversationRepository()


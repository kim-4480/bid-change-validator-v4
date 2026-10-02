import type { CanonicalRequirement, RequirementChange } from '@/lib/qualification-api';

function normText(value: unknown) {
  if (value == null) return '';
  const text = typeof value === 'string'
    ? value
    : typeof value === 'number' || typeof value === 'boolean' || typeof value === 'bigint'
      ? `${value}`
      : JSON.stringify(value);
  return (text ?? '').toLocaleLowerCase().replace(/\s+/g, '');
}

function rawSkeleton(requirement: CanonicalRequirement) {
  let raw = normText(requirement.raw);
  const value = normText(requirement.value);
  if (value) raw = raw.split(value).join('<value>');
  return raw
    .replace(/\d+(?:[.,]\d+)*/g, '<n>')
    .replace(/(?:억원|만원|원|개월|년|건|명)/g, '<unit>');
}

function semanticIdentity(requirement: CanonicalRequirement) {
  const stableScope = ['kind', 'role', 'source', 'client_requirement']
    .flatMap((key) => {
      const value = requirement.scope?.[key];
      return value == null || value === '' ? [] : [`${key}=${normText(value)}`];
    });
  return [requirement.type, ...stableScope, rawSkeleton(requirement)].join('|');
}

function stableValue(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(stableValue);
  if (value && typeof value === 'object') {
    return Object.fromEntries(
      Object.entries(value as Record<string, unknown>)
        .sort(([left], [right]) => left.localeCompare(right))
        .map(([key, child]) => [key, stableValue(child)]),
    );
  }
  return value;
}

export function sameRequirementScope(
  before: Record<string, unknown> | null | undefined,
  after: Record<string, unknown> | null | undefined,
) {
  return JSON.stringify(stableValue(before ?? {})) === JSON.stringify(stableValue(after ?? {}));
}

function decisionPayload(requirement: CanonicalRequirement) {
  return JSON.stringify(stableValue({
    type: requirement.type,
    operator: requirement.operator,
    value: requirement.value,
    unit: requirement.unit,
    period_months: requirement.period_months,
    scope: requirement.scope,
    required: requirement.required,
    requirement_role: requirement.requirement_role,
    condition_complexity: requirement.condition_complexity,
    group_operator: requirement.group_operator,
    raw: normText(requirement.raw),
  }));
}

/**
 * 화면에서 말하는 「구조화 값」의 동일성이다. 원문(raw)은 제외하고 백엔드의
 * decision_payload 필드를 비교한다. 값이 같아도 연산자나 적용 범위가 바뀌면 false다.
 */
export function sameStructuredRequirement(
  before: CanonicalRequirement | null,
  after: CanonicalRequirement | null,
) {
  if (!before || !after) return false;
  const structuredPayload = (requirement: CanonicalRequirement) => JSON.stringify(stableValue({
    type: requirement.type,
    operator: requirement.operator,
    value: requirement.value,
    unit: requirement.unit,
    period_months: requirement.period_months,
    scope: requirement.scope,
    required: requirement.required,
    requirement_role: requirement.requirement_role,
    condition_complexity: requirement.condition_complexity,
    group_operator: requirement.group_operator,
  }));
  return structuredPayload(before) === structuredPayload(after);
}

/**
 * 읽기 전용 변경 화면용 비교다. 백엔드 requirement_diff.py와 같은 순서로
 * 고유한 의미 식별자를 먼저 맞추고, 남은 요건만 requirement_key로 맞춘다.
 * 재검증을 실행하기 전에도 이미 저장된 기준/현재 분석으로 변경값을 보여준다.
 */
export function diffCanonicalRequirements(
  baseline: CanonicalRequirement[],
  current: CanonicalRequirement[],
): RequirementChange[] {
  const baselineByKey = new Map(baseline.map((item) => [item.requirement_key, item]));
  const currentByKey = new Map(current.map((item) => [item.requirement_key, item]));
  const matchedBaseline = new Set<string>();
  const matchedCurrent = new Set<string>();
  const pairs: Array<[CanonicalRequirement, CanonicalRequirement, string]> = [];

  const baselineByIdentity = new Map<string, CanonicalRequirement[]>();
  const currentByIdentity = new Map<string, CanonicalRequirement[]>();
  for (const item of baseline) {
    const identity = semanticIdentity(item);
    baselineByIdentity.set(identity, [...(baselineByIdentity.get(identity) ?? []), item]);
  }
  for (const item of current) {
    const identity = semanticIdentity(item);
    currentByIdentity.set(identity, [...(currentByIdentity.get(identity) ?? []), item]);
  }

  const sharedIdentities = [...baselineByIdentity.keys()]
    .filter((identity) => currentByIdentity.has(identity))
    .sort();
  for (const identity of sharedIdentities) {
    const before = baselineByIdentity.get(identity) ?? [];
    const after = currentByIdentity.get(identity) ?? [];
    if (before.length !== 1 || after.length !== 1) continue;
    pairs.push([before[0], after[0], `semantic:${identity}`]);
    matchedBaseline.add(before[0].requirement_key);
    matchedCurrent.add(after[0].requirement_key);
  }

  const sharedKeys = [...baselineByKey.keys()]
    .filter((key) => currentByKey.has(key))
    .sort();
  for (const key of sharedKeys) {
    if (matchedBaseline.has(key) || matchedCurrent.has(key)) continue;
    const before = baselineByKey.get(key)!;
    const after = currentByKey.get(key)!;
    if (before.type !== after.type) continue;
    pairs.push([before, after, `key:${key}`]);
    matchedBaseline.add(key);
    matchedCurrent.add(key);
  }

  const changes: RequirementChange[] = pairs.map(([before, after, identity]) => ({
    change_type: decisionPayload(before) === decisionPayload(after) ? 'UNCHANGED' : 'MODIFIED',
    identity,
    baseline_key: before.requirement_key,
    current_key: after.requirement_key,
    baseline: before,
    current: after,
  }));
  for (const before of baseline) {
    if (matchedBaseline.has(before.requirement_key)) continue;
    changes.push({
      change_type: 'REMOVED',
      identity: `removed:${semanticIdentity(before)}`,
      baseline_key: before.requirement_key,
      current_key: null,
      baseline: before,
      current: null,
    });
  }
  for (const after of current) {
    if (matchedCurrent.has(after.requirement_key)) continue;
    changes.push({
      change_type: 'ADDED',
      identity: `added:${semanticIdentity(after)}`,
      baseline_key: null,
      current_key: after.requirement_key,
      baseline: null,
      current: after,
    });
  }

  const order = { MODIFIED: 0, ADDED: 1, REMOVED: 2, UNCHANGED: 3 } as const;
  return changes.sort((left, right) => (
    order[left.change_type] - order[right.change_type]
    || (left.current_key ?? left.baseline_key ?? left.identity)
      .localeCompare(right.current_key ?? right.baseline_key ?? right.identity)
  ));
}

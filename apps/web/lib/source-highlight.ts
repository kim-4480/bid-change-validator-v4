/*
  공고 원문 위에 엔진이 고른 조항을 칠한다.

  조항 원문(requirement.raw, 공백 조항)은 추출 블록을 이어 붙인 것이라 문서 텍스트와 띄어쓰기·줄바꿈이 다르다.
  그래서 띄어쓰기를 지운 문자열끼리 찾고, 찾은 자리를 원래 텍스트 위치로 되돌린다.
  조항이 통째로 없으면(청크 경계에서 잘렸거나 표 안에서 순서가 바뀐 경우) 앞부분이 맞는 만큼만 칠한다.
  여러 조항이 겹치면 종류 우선순위가 높은 쪽이 이긴다.
*/

export type HighlightKind = 'VERDICT' | 'GAP_BLOCKING' | 'CHECKLIST' | 'GAP_CHECKLIST' | 'NOTE';

export type HighlightSource = {
  text: string;
  kind: HighlightKind;
  /** 마우스를 올렸을 때 보일 설명(예: '업종 · 0040'). */
  label: string;
};

export type HighlightSegment = {
  text: string;
  kind: HighlightKind | null;
  label: string | null;
  /** 같은 조항 조각을 묶는 번호 — '다음 조항' 이동에 쓴다. 칠하지 않은 조각은 null. */
  index: number | null;
};

export const HIGHLIGHT_PRIORITY: HighlightKind[] = ['VERDICT', 'GAP_BLOCKING', 'CHECKLIST', 'GAP_CHECKLIST', 'NOTE'];

// 이보다 짧으면 흔한 낱말("업체", "입찰참가자격")에 잘못 붙는다. "다. 공동수급 불가"(8자)는 칠해야 한다.
const MIN_MATCH = 8;

/** 띄어쓰기를 지운 문자열과, 그 각 글자가 원문 몇 번째 글자였는지. */
function compactIndex(text: string) {
  const chars: string[] = [];
  const positions: number[] = [];
  for (let index = 0; index < text.length; index += 1) {
    const char = text[index];
    if (/\s/.test(char)) continue;
    chars.push(char);
    positions.push(index);
  }
  return { compact: chars.join(''), positions };
}

function compactOf(text: string) {
  return text.replace(/\s+/g, '');
}

/** 조항이 문서에서 차지하는 구간들 [시작, 끝) — 띄어쓰기를 지운 위치 기준. */
function findRanges(haystack: string, needle: string): Array<[number, number]> {
  if (needle.length < MIN_MATCH) return [];
  const ranges: Array<[number, number]> = [];
  let from = 0;
  for (;;) {
    const at = haystack.indexOf(needle, from);
    if (at < 0) break;
    ranges.push([at, at + needle.length]);
    from = at + needle.length;
  }
  if (ranges.length) return ranges;
  // 통째로 없으면 앞부분으로 자리를 잡고, 그 뒤로 글자가 같은 만큼만 칠한다.
  // 앞부분은 24자부터 MIN_MATCH 자까지 줄여 가며 찾는다(짧은 조항은 앞부분이 곧 조항 전체라 그대로는 못 찾는다).
  let prefix = '';
  let at = -1;
  for (let length = Math.min(needle.length - 1, 24); length >= MIN_MATCH && at < 0; length -= 1) {
    prefix = needle.slice(0, length);
    at = haystack.indexOf(prefix);
  }
  while (at >= 0) {
    let length = prefix.length;
    while (at + length < haystack.length && length < needle.length && haystack[at + length] === needle[length]) length += 1;
    if (length >= MIN_MATCH) ranges.push([at, at + length]);
    at = haystack.indexOf(prefix, at + length);
  }
  return ranges;
}

export function highlightSegments(text: string, sources: HighlightSource[]): HighlightSegment[] {
  if (!text) return [];
  const { compact, positions } = compactIndex(text);
  const owner = new Int32Array(text.length).fill(-1);
  const rank = (kind: HighlightKind) => HIGHLIGHT_PRIORITY.indexOf(kind);
  // 우선순위가 낮은 것부터 칠해 높은 것이 덮어쓰게 한다.
  const ordered = sources
    .map((source, index) => ({ source, index }))
    .sort((a, b) => rank(b.source.kind) - rank(a.source.kind));
  for (const { source, index } of ordered) {
    for (const [start, end] of findRanges(compact, compactOf(source.text))) {
      const from = positions[start];
      const to = positions[end - 1] + 1;
      for (let at = from; at < to; at += 1) owner[at] = index;
    }
  }
  const segments: HighlightSegment[] = [];
  let start = 0;
  for (let at = 1; at <= text.length; at += 1) {
    if (at < text.length && owner[at] === owner[start]) continue;
    const who = owner[start];
    const source = who >= 0 ? sources[who] : null;
    segments.push({ text: text.slice(start, at), kind: source?.kind ?? null, label: source?.label ?? null, index: who >= 0 ? who : null });
    start = at;
  }
  return segments;
}

/** 종류별로 실제 문서에서 찾은 조항 수(같은 조항이 여러 곳에 칠해져도 하나). */
export function highlightCounts(segments: HighlightSegment[]): Record<HighlightKind, number> {
  const seen = new Map<HighlightKind, Set<number>>();
  for (const segment of segments) {
    if (segment.kind === null || segment.index === null) continue;
    if (!seen.has(segment.kind)) seen.set(segment.kind, new Set());
    seen.get(segment.kind)!.add(segment.index);
  }
  return Object.fromEntries(HIGHLIGHT_PRIORITY.map((kind) => [kind, seen.get(kind)?.size ?? 0])) as Record<HighlightKind, number>;
}

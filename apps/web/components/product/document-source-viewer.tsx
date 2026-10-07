'use client';

import { useEffect, useMemo, useRef, useState } from 'react';
import { ChevronDown, LoaderCircle } from 'lucide-react';

import { Button } from '@/components/ui/button';
import { NativeSelect, NativeSelectOption } from '@/components/ui/native-select';
import { getDocumentText, type NoticeDocument, type NoticeDocumentText } from '@/lib/api';
import {
  HIGHLIGHT_PRIORITY,
  highlightCounts,
  highlightSegments,
  type HighlightKind,
  type HighlightSource,
} from '@/lib/source-highlight';

/* 종류별 색과 이름. 판정 표·확인할 항목 섹션과 같은 말을 쓴다. */
const KIND_META: Record<HighlightKind, { label: string; mark: string; chip: string }> = {
  VERDICT: { label: '핵심 자격', mark: 'bg-emerald-100 ring-emerald-300', chip: 'border-emerald-300 bg-emerald-50 text-emerald-800' },
  GAP_BLOCKING: { label: '핵심 자격 중 확인 필요', mark: 'bg-amber-200/70 ring-amber-400', chip: 'border-amber-300 bg-amber-50 text-amber-800' },
  CHECKLIST: { label: '확인할 항목', mark: 'bg-sky-100 ring-sky-300', chip: 'border-sky-300 bg-sky-50 text-sky-800' },
  GAP_CHECKLIST: { label: '요건으로 정리하지 못한 조항', mark: 'bg-violet-100 ring-violet-300', chip: 'border-violet-300 bg-violet-50 text-violet-800' },
  NOTE: { label: '참고 정보', mark: 'bg-slate-200/80 ring-slate-300', chip: 'border-slate-300 bg-slate-50 text-slate-700' },
};

function documentText(document: NoticeDocumentText) {
  if (document.text) return document.text;
  return (document.blocks ?? [])
    .map((block) => (typeof block.text === 'string' ? block.text : ''))
    .filter(Boolean)
    .join('\n');
}

type Props = {
  documents: NoticeDocument[];
  highlights: HighlightSource[];
};

/**
 * 판정 페이지 하단의 공고 문서 원문. 펼칠 때 원문을 불러오고, 엔진이 고른 조항을 종류별 색으로 칠한다.
 * 칠한 조각에 마우스를 올리면 어떤 요건·조항인지 보이고, 「다음 조항」으로 칠한 곳을 차례로 옮겨 다닌다.
 * 차수·분석이 바뀌면 부르는 쪽이 key 를 바꿔 새로 만든다(불러온 원문·선택을 버린다).
 */
export function DocumentSourceViewer({ documents, highlights }: Props) {
  const [open, setOpen] = useState(false);
  const [documentId, setDocumentId] = useState(documents[0]?.id ?? '');
  const [loaded, setLoaded] = useState<Record<string, NoticeDocumentText | 'error'>>({});
  const [hidden, setHidden] = useState<Set<HighlightKind>>(new Set());
  const [cursor, setCursor] = useState(-1);
  const scrollRef = useRef<HTMLDivElement>(null);


  const selected = documents.find((item) => item.id === documentId) ?? documents[0] ?? null;
  const current = selected ? loaded[selected.id] : undefined;

  useEffect(() => {
    if (!open || !selected || current !== undefined) return;
    let alive = true;
    getDocumentText(selected.text_url)
      .then((text) => { if (alive) setLoaded((prev) => ({ ...prev, [selected.id]: text })); })
      .catch(() => { if (alive) setLoaded((prev) => ({ ...prev, [selected.id]: 'error' })); });
    return () => { alive = false; };
  }, [open, selected, current]);

  const text = current && current !== 'error' ? documentText(current) : '';
  const segments = useMemo(() => highlightSegments(text, highlights), [text, highlights]);
  const counts = useMemo(() => highlightCounts(segments), [segments]);
  // '다음 조항' 이동 대상: 보이는 종류의 칠한 조각마다 첫 조각 하나.
  const stops = useMemo(() => {
    const seen = new Set<string>();
    const out: number[] = [];
    segments.forEach((segment, position) => {
      if (segment.kind === null || segment.index === null || hidden.has(segment.kind)) return;
      const key = `${segment.kind}-${segment.index}`;
      if (seen.has(key)) return;
      seen.add(key);
      out.push(position);
    });
    return out;
  }, [segments, hidden]);

  const goNext = () => {
    if (!stops.length) return;
    const next = (cursor + 1) % stops.length;
    setCursor(next);
    const node = scrollRef.current?.querySelector(`[data-seg="${stops[next]}"]`);
    node?.scrollIntoView({ behavior: 'smooth', block: 'center' });
  };

  const toggle = (kind: HighlightKind) => setHidden((prev) => {
    const next = new Set(prev);
    if (next.has(kind)) next.delete(kind); else next.add(kind);
    return next;
  });

  return (
    <section className="mt-10 rounded-[20px] border border-[var(--product-line)] bg-white">
      <button
        type="button"
        aria-expanded={open}
        onClick={() => setOpen((value) => !value)}
        className="flex w-full items-center justify-between gap-3 px-6 py-4 text-left"
      >
        <span>
          <span className="block text-[18px] font-extrabold text-[var(--product-ink)]">공고 문서 원문</span>
          <span className="mt-0.5 block text-[13px] text-[var(--product-muted)]">첨부 {documents.length}개 · 엔진이 고른 조항을 종류별 색으로 표시합니다.</span>
        </span>
        <ChevronDown className={`size-5 shrink-0 text-[var(--product-muted)] transition-transform ${open ? 'rotate-180' : ''}`} />
      </button>

      {open && (
        <div className="border-t border-[var(--product-line)] px-6 pb-6 pt-4">
          {!documents.length ? (
            <p className="text-[14px] text-[var(--product-muted)]">이 차수에는 수집된 첨부 문서가 없습니다.</p>
          ) : (
            <>
              <div className="flex flex-wrap items-center gap-3">
                <NativeSelect
                  id="source-document"
                  aria-label="원문 문서 선택"
                  value={selected?.id ?? ''}
                  onChange={(event) => { setDocumentId(event.target.value); setCursor(-1); }}
                  className="min-w-0 max-w-full"
                >
                  {documents.map((item) => <NativeSelectOption key={item.id} value={item.id}>{item.name}</NativeSelectOption>)}
                </NativeSelect>
                <Button type="button" variant="outline" size="sm" onClick={goNext} disabled={!stops.length}>
                  다음 조항{stops.length ? ` (${cursor < 0 ? 0 : cursor + 1}/${stops.length})` : ''}
                </Button>
              </div>

              <fieldset className="mt-3 flex flex-wrap gap-2 border-0 p-0">
                <legend className="sr-only">표시할 조항 종류</legend>
                {HIGHLIGHT_PRIORITY.map((kind) => (
                  <button
                    key={kind}
                    type="button"
                    aria-pressed={!hidden.has(kind)}
                    onClick={() => toggle(kind)}
                    className={`rounded-full border px-2.5 py-1 text-[12px] font-semibold transition-opacity ${KIND_META[kind].chip} ${hidden.has(kind) ? 'opacity-40' : ''}`}
                  >
                    {KIND_META[kind].label} {counts[kind]}
                  </button>
                ))}
              </fieldset>

              <div ref={scrollRef} className="mt-4 max-h-[70vh] overflow-y-auto rounded-[14px] border border-[var(--product-line-2)] bg-[var(--product-tint)] px-5 py-4">
                {current === undefined ? (
                  <p className="flex items-center gap-2 text-[14px] text-[var(--product-muted)]"><LoaderCircle className="size-4 animate-spin" />원문을 불러오고 있습니다.</p>
                ) : current === 'error' ? (
                  <p className="text-[14px] text-rose-700">원문을 불러오지 못했습니다. 잠시 후 다시 열어 주세요.</p>
                ) : !text ? (
                  <p className="text-[14px] text-[var(--product-muted)]">이 문서에서 읽어 낸 텍스트가 없습니다(추출 상태: {current.extraction_status}).</p>
                ) : (
                  <div className="whitespace-pre-wrap break-words text-[14px] leading-7 text-[var(--product-body)]">
                    {segments.map((segment, position) => (
                      segment.kind && !hidden.has(segment.kind) ? (
                        <mark
                          key={position}
                          data-seg={position}
                          title={`${KIND_META[segment.kind].label} · ${segment.label ?? ''}`}
                          className={`rounded-[3px] px-0.5 text-inherit ring-1 ${KIND_META[segment.kind].mark} ${stops[cursor] === position ? 'outline outline-2 outline-offset-1 outline-[var(--product-accent)]' : ''}`}
                        >
                          {segment.text}
                        </mark>
                      ) : (
                        <span key={position} data-seg={position}>{segment.text}</span>
                      )
                    ))}
                  </div>
                )}
              </div>
            </>
          )}
        </div>
      )}
    </section>
  );
}

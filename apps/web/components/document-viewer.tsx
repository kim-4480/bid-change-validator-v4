'use client';

import { useEffect, useRef, useState } from 'react';
import { ChevronLeft, ChevronRight, FileQuestion, LoaderCircle } from 'lucide-react';
import type { HwpDocument } from '@rhwp/core';

import { Button } from '@/components/ui/button';
import { absoluteApiUrl, getDocumentText, type ViewableDocument } from '@/lib/api';

let rhwpInitialization: Promise<unknown> | null = null;

async function initializeRhwp() {
  const runtime = globalThis as typeof globalThis & {
    measureTextWidth?: (font: string, text: string) => number;
  };
  if (!runtime.measureTextWidth) {
    runtime.measureTextWidth = (font, text) => {
      const context = document.createElement('canvas').getContext('2d');
      if (!context) return text.length * 8;
      context.font = font;
      return context.measureText(text).width;
    };
  }
  const rhwp = await import('@rhwp/core');
  rhwpInitialization ??= rhwp.default({ module_or_path: '/rhwp_bg.wasm' });
  await rhwpInitialization;
  return rhwp;
}

function HwpViewer({ sourceUrl }: { sourceUrl: string }) {
  const documentRef = useRef<HwpDocument | null>(null);
  const [page, setPage] = useState(0);
  const [pageCount, setPageCount] = useState(0);
  const [svg, setSvg] = useState('');
  const [error, setError] = useState('');

  useEffect(() => {
    let cancelled = false;

    void (async () => {
      try {
        const [rhwp, response] = await Promise.all([
          initializeRhwp(),
          fetch(absoluteApiUrl(sourceUrl)),
        ]);
        if (!response.ok) throw new Error('HWP 원본을 불러오지 못했습니다.');
        const instance = new rhwp.HwpDocument(new Uint8Array(await response.arrayBuffer()));
        if (cancelled) {
          instance.free();
          return;
        }
        documentRef.current = instance;
        const total = instance.pageCount();
        setPageCount(total);
        setSvg(total ? instance.renderPageSvg(0) : '');
      } catch (cause) {
        if (!cancelled) {
          setError(cause instanceof Error ? cause.message : 'HWP 렌더링에 실패했습니다.');
        }
      }
    })();

    return () => {
      cancelled = true;
      documentRef.current?.free();
      documentRef.current = null;
    };
  }, [sourceUrl]);

  function movePage(nextPage: number) {
    const instance = documentRef.current;
    if (!instance || nextPage < 0 || nextPage >= pageCount) return;
    setPage(nextPage);
    setSvg(instance.renderPageSvg(nextPage));
  }

  if (error) return <ViewerMessage icon={FileQuestion} message={error} />;
  if (!svg) return <ViewerMessage icon={LoaderCircle} message="HWP 원문 렌더링 중…" spin />;

  const isolatedPage = `<!doctype html><html><head><meta charset="utf-8"><style>html,body{margin:0;background:#fff}svg{display:block;width:100%;height:auto}</style></head><body>${svg}</body></html>`;

  return (
    <div className="relative flex min-h-0 flex-1 flex-col bg-zinc-200/70">
      <div className="flex min-h-0 flex-1 items-start justify-center overflow-auto p-3">
        <iframe
          className="hwp-page aspect-[210/297] w-full max-w-[760px] bg-white shadow-sm"
          sandbox=""
          srcDoc={isolatedPage}
          title={`HWP ${page + 1}페이지`}
        />
      </div>
      <div className="flex h-10 items-center justify-center gap-2 border-t bg-card">
        <Button size="icon-xs" variant="ghost" aria-label="이전 페이지" onClick={() => movePage(page - 1)} disabled={page === 0}>
          <ChevronLeft />
        </Button>
        <span className="min-w-16 text-center text-xs text-muted-foreground">{page + 1} / {pageCount}</span>
        <Button size="icon-xs" variant="ghost" aria-label="다음 페이지" onClick={() => movePage(page + 1)} disabled={page + 1 >= pageCount}>
          <ChevronRight />
        </Button>
      </div>
    </div>
  );
}

function TextViewer({ textUrl }: { textUrl: string }) {
  const [text, setText] = useState('');
  const [error, setError] = useState('');

  useEffect(() => {
    let cancelled = false;
    void getDocumentText(textUrl)
      .then((result) => {
        if (!cancelled) setText(result.text || '추출된 텍스트가 없습니다.');
      })
      .catch((cause) => {
        if (!cancelled) setError(cause instanceof Error ? cause.message : '텍스트를 불러오지 못했습니다.');
      });
    return () => {
      cancelled = true;
    };
  }, [textUrl]);

  if (error) return <ViewerMessage icon={FileQuestion} message={error} />;
  if (!text) return <ViewerMessage icon={LoaderCircle} message="텍스트 불러오는 중…" spin />;
  return <pre className="min-h-0 flex-1 overflow-auto whitespace-pre-wrap p-5 font-sans text-sm leading-7">{text}</pre>;
}

function ViewerMessage({
  icon: Icon,
  message,
  spin = false,
}: {
  icon: typeof FileQuestion;
  message: string;
  spin?: boolean;
}) {
  return (
    <div className="grid min-h-0 flex-1 place-items-center p-8 text-center text-sm text-muted-foreground">
      <div>
        <Icon className={`mx-auto mb-3 size-7 opacity-50 ${spin ? 'animate-spin' : ''}`} />
        {message}
      </div>
    </div>
  );
}

export function DocumentViewer({
  document,
  emptyMessage,
}: {
  document: ViewableDocument | null;
  emptyMessage: string;
}) {
  if (!document) return <ViewerMessage icon={FileQuestion} message={emptyMessage} />;
  if (document.viewer_type === 'RHWP') {
    return <HwpViewer key={document.render_source_url} sourceUrl={document.render_source_url} />;
  }
  if (document.viewer_type === 'PDF') {
    return (
      <iframe
        className="min-h-0 flex-1 bg-white"
        src={absoluteApiUrl(document.preview_url ?? document.render_source_url)}
        title={document.name}
      />
    );
  }
  return <TextViewer key={document.text_url} textUrl={document.text_url} />;
}

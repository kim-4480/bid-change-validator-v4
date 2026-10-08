export const NOTICE_PAGE_SIZE = 10;

export type NoticeListOptions = {
  limit?: number;
  offset?: number;
  businessType?: string;
};

export function noticeListParams(query: string, options: NoticeListOptions = {}): URLSearchParams {
  const search = new URLSearchParams({
    // Existing callers outside /notices still rely on the former 100-item default.
    limit: String(options.limit ?? 100),
    offset: String(options.offset ?? 0),
  });
  if (query.trim()) search.set('q', query.trim());
  if (options.businessType && options.businessType !== 'all') {
    search.set('business_type', options.businessType);
  }
  return search;
}

export function noticePageRange(total: number, page: number, pageSize = NOTICE_PAGE_SIZE) {
  const pageCount = Math.ceil(total / pageSize);
  const start = total === 0 ? 0 : page * pageSize + 1;
  const end = total === 0 ? 0 : Math.min(total, (page + 1) * pageSize);
  return { start, end, pageCount, hasPrevious: page > 0, hasNext: page + 1 < pageCount };
}

'use client';

import { QueryClient } from '@tanstack/react-query';

export const STALE_MS = 90_000;

// Module-level browser cache only. Never share a server-side cache between users.
let browserClient: QueryClient | undefined;
export function sharedQueryClient(): QueryClient {
  if (typeof window === 'undefined') return createQueryClient();
  return (browserClient ??= createQueryClient());
}
export function createQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: { queries: { staleTime: STALE_MS, gcTime: 15 * 60_000, retry: false, refetchOnWindowFocus: false } },
  });
}

export function queryKeyForGet(path: string) {
  return ['api-get', path] as const;
}
export function sharedRead<T>(path: string, network: () => Promise<T>): Promise<T> {
  return sharedQueryClient().fetchQuery({ queryKey: queryKeyForGet(path), queryFn: network });
}
export function cachedGet<T>(path: string): T | undefined {
  return sharedQueryClient().getQueryData<T>(queryKeyForGet(path));
}
// Cache safe metadata and immutable judgment snapshots, not live analyses, jobs, or polling.
export function mayCacheGet(path: string) {
  return /^\/api\/v1\/(?:companies(?:\?.*)?|notices(?:\?.*)?|notices\/[^/?]+(?:\/versions)?|preflight-cases(?:\?.*)?|preflight-cases\/[^/?]+|qualification-judgment-runs\/[^/?]+|master-codes\/industries(?:\?.*)?)$/.test(path);
}
export function clearSharedData() {
  if (typeof window !== 'undefined') sharedQueryClient().clear();
}
export function invalidateSharedData() {
  if (typeof window !== 'undefined') {
    sharedQueryClient().removeQueries({ queryKey: ['view'] });
    void sharedQueryClient().invalidateQueries();
  }
}
export function removeShared(path: string) {
  sharedQueryClient().removeQueries({ queryKey: queryKeyForGet(path), exact: true });
}

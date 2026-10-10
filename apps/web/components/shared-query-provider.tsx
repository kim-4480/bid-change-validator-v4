'use client';

import { QueryClientProvider } from '@tanstack/react-query';
import { sharedQueryClient } from '@/lib/shared-query-cache';
import type { ReactNode } from 'react';

// A single provider is mounted above AppShell and survives client navigation.
export function SharedQueryProvider({ children }: { children: ReactNode }) {
  return <QueryClientProvider client={sharedQueryClient()}>{children}</QueryClientProvider>;
}

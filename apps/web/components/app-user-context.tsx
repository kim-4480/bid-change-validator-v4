'use client';

import { createContext, useContext, type ReactNode } from 'react';
import type { AuthUser } from '@/lib/auth';

// AppShell is the sole owner of session verification across protected routes.
const AppUserContext = createContext<AuthUser | null | undefined>(undefined);

export function AppUserProvider({ user, children }: { user: AuthUser | null; children: ReactNode }) {
  return <AppUserContext.Provider value={user}>{children}</AppUserContext.Provider>;
}

export function useAppUser(): AuthUser | null {
  const user = useContext(AppUserContext);
  if (user === undefined) throw new Error('useAppUser must be used under AppUserProvider');
  return user;
}

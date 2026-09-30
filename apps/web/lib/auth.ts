import { apiFetch, ApiError } from '@/lib/api';

export type AuthUser = {
  id: string;
  username: string;
  role: string;
  company_id: string | null;
  company_name: string | null;
};

export type LoginResponse = {
  access_token: string;
  token_type: 'bearer';
  expires_at: string;
  user: AuthUser;
};

async function authRequest<T>(path: string, init?: RequestInit): Promise<T> {
  const headers = new Headers(init?.headers);
  if (init?.body) headers.set('Content-Type', 'application/json');
  const response = await apiFetch(path, {
    ...init,
    credentials: 'include',
    headers,
  });
  if (!response.ok) {
    const payload = (await response.json().catch(() => null)) as {
      error?: { message?: string; code?: string };
    } | null;
    throw new ApiError(
      payload?.error?.message ?? `요청에 실패했습니다. (${response.status})`,
      response.status,
      payload?.error?.code ?? 'HTTP_ERROR',
    );
  }
  if (response.status === 204) return undefined as T;
  return response.json() as Promise<T>;
}

export function login(username: string, password: string) {
  return authRequest<LoginResponse>('/api/v1/auth/login', {
    method: 'POST',
    body: JSON.stringify({ username, password }),
  });
}

export function getCurrentUser() {
  return authRequest<AuthUser | null>('/api/v1/auth/me');
}

export function logout() {
  return authRequest<void>('/api/v1/auth/logout', { method: 'POST' });
}

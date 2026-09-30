import type { ActionState } from './copilot-actions';
import type { Conversation } from './copilot-conversation';

const KEY = 'bidcheck:copilot-navigation-handoff:v1';
const TTL_MS = 2 * 60 * 1000;

export type CopilotNavigationHandoff = {
  version: 1;
  caseId: string;
  destination: string;
  expiresAt: number;
  reopenPanel: boolean;
  conversation: Conversation | null;
  action: ActionState | null;
};

function destinationOf(href: string) {
  const url = new URL(href, window.location.href);
  return `${url.pathname}${url.search}`;
}

export function saveCopilotNavigationHandoff(
  href: string,
  caseId: string,
  conversation: Conversation | null,
  action: ActionState | null,
  reopenPanel = false,
) {
  if (!caseId || (!conversation && !action)) return;
  try {
    const payload: CopilotNavigationHandoff = {
      version: 1,
      caseId,
      destination: destinationOf(href),
      expiresAt: Date.now() + TTL_MS,
      reopenPanel,
      conversation,
      action,
    };
    window.sessionStorage.setItem(KEY, JSON.stringify(payload));
  } catch {
    // Navigation must still work when storage is unavailable or full.
  }
}

export function takeCopilotNavigationHandoff(): CopilotNavigationHandoff | null {
  try {
    const raw = window.sessionStorage.getItem(KEY);
    if (!raw) return null;
    window.sessionStorage.removeItem(KEY);
    const payload = JSON.parse(raw) as Partial<CopilotNavigationHandoff>;
    const current = `${window.location.pathname}${window.location.search}`;
    if (payload.version !== 1 || typeof payload.caseId !== 'string' ||
        typeof payload.destination !== 'string' || payload.destination !== current ||
        typeof payload.expiresAt !== 'number' || payload.expiresAt < Date.now()) return null;
    return {
      ...payload,
      reopenPanel: payload.reopenPanel === true,
    } as CopilotNavigationHandoff;
  } catch {
    try { window.sessionStorage.removeItem(KEY); } catch { /* unavailable */ }
    return null;
  }
}

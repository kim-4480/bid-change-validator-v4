'use client';
import { createContext, useContext, useEffect, useState, useSyncExternalStore, type ReactNode } from 'react';
import { ConversationStore } from '@/lib/copilot-conversation';
import { ActionController } from '@/lib/copilot-actions';
import { saveCopilotNavigationHandoff, takeCopilotNavigationHandoff } from '@/lib/copilot-navigation-handoff';
import { navigateTo } from '@/lib/navigation';

const Context = createContext<{ store: ConversationStore; controller: ActionController } | null>(null);
export function CopilotProvider({ children }: { children: ReactNode }) {
  const [value] = useState(() => {
    const store = new ConversationStore();
    return { store, controller: new ActionController(undefined, undefined, (id, response) => store.publish(id, response)) };
  });
  useEffect(() => {
    const handoff = takeCopilotNavigationHandoff();
    if (!handoff) return;
    if (handoff.conversation) value.store.restore(handoff.caseId, handoff.conversation);
    if (handoff.action) value.controller.restore(handoff.caseId, handoff.action);
    if (handoff.reopenPanel) {
      // The destination page renders a fresh CopilotPanel after document navigation.
      // Reuse its public launcher rather than duplicating dialog state here.
      window.requestAnimationFrame(() => {
        const launcher = document.querySelector<HTMLButtonElement>('.copilot-launch[aria-expanded="false"]');
        launcher?.click();
      });
    }
  }, [value]);
  return <Context.Provider value={value}>{children}</Context.Provider>;
}
function useStores() {
  const stores = useContext(Context);
  if (!stores) throw new Error('CopilotProvider required');
  return stores;
}
export function useCopilot(caseId: string) {
  const { store } = useStores();
  const state = useSyncExternalStore(store.subscribe, () => store.get(caseId), () => store.get(caseId));
  return { store, state };
}
export function useActions(caseId: string) {
  const { controller } = useStores();
  const action = useSyncExternalStore(controller.subscribe, () => controller.get(caseId), () => controller.get(caseId));
  return { controller, action };
}
export function useCopilotNavigation(caseId: string) {
  const { store, controller } = useStores();
  const stage = (destination: string, reopenPanel = false) => saveCopilotNavigationHandoff(
    destination,
    caseId,
    store.snapshot(caseId),
    controller.snapshot(caseId),
    reopenPanel,
  );
  return {
    stage,
    navigate: (destination: string, reopenPanel = true) => {
      stage(destination, reopenPanel);
      navigateTo(destination);
    },
  };
}

'use client';

import type { AnchorHTMLAttributes, MouseEvent } from 'react';
import { NavigationLink } from '@/components/navigation-link';
import { useCopilotNavigation } from './provider';

type Props = AnchorHTMLAttributes<HTMLAnchorElement> & { href: string; caseId: string };

export function CopilotNavigationLink({ caseId, href, onClick, ...props }: Props) {
  const { stage } = useCopilotNavigation(caseId);
  const handleClick = (event: MouseEvent<HTMLAnchorElement>) => {
    onClick?.(event);
    if (!event.defaultPrevented) {
      const reopenPanel = Boolean(event.currentTarget.closest('#copilot-panel[open]'));
      stage(href, reopenPanel);
    }
  };
  return <NavigationLink {...props} href={href} onClick={handleClick} />;
}

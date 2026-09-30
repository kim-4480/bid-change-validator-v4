import type { AnchorHTMLAttributes } from 'react';

/**
 * Internal navigation that deliberately uses the browser's document navigation.
 *
 * The self-hosted Vinext runtime currently fails while handling Next.js RSC client
 * transitions. A native anchor keeps normal link semantics and lets the server
 * render the destination route directly.
 */
export function NavigationLink(props: AnchorHTMLAttributes<HTMLAnchorElement>) {
  const { children, ...anchorProps } = props;
  return <a {...anchorProps}>{children}</a>;
}

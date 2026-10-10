'use client';

import Link from 'next/link';
import type { AnchorHTMLAttributes } from 'react';

export function NavigationLink({ href, children, ...props }: AnchorHTMLAttributes<HTMLAnchorElement>) {
  if (!href) return <a {...props}>{children}</a>;
  if (href.startsWith('#') || /^(?:[a-z][a-z0-9+.-]*:|\/\/)/i.test(href)) {
    return <a href={href} {...props}>{children}</a>;
  }
  return <Link href={href} {...props}>{children}</Link>;
}

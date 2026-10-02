import type { HTMLAttributes, ReactNode } from 'react';

import { cn } from '@/lib/utils';

type PageContainerProps = HTMLAttributes<HTMLDivElement> & {
  children: ReactNode;
};

export function PageContainer({ children, className, ...props }: PageContainerProps) {
  return (
    <div className={cn('app-shell-container', className)} {...props}>
      {children}
    </div>
  );
}

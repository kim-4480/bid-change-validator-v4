import type { Metadata } from 'next';
import { Geist_Mono, Gothic_A1 } from 'next/font/google';

import { AppShell } from '@/components/app-shell';

import './globals.css';
import '@/components/product/product.css';

const gothicA1 = Gothic_A1({
  variable: '--font-product-sans',
  subsets: ['latin'],
  weight: ['400', '500', '600', '700', '800'],
});

const geistMono = Geist_Mono({
  variable: '--font-geist-mono',
  subsets: ['latin'],
});

export const metadata: Metadata = {
  title: '비드체크 · 입찰 참가자격 확인',
  description: '공고 원문 근거와 회사 프로필을 함께 확인하는 입찰 참가자격 검토 서비스',
  /* 탭 아이콘도 헤더 마크와 같은 그림을 쓴다. 별도 파일 없이 data URI로 둔다. */
  icons: { icon: "data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 32 32'><rect width='32' height='32' rx='10' fill='%234a3fd4'/><path d='M9.5 16.8l4.4 4.4L22.5 12' stroke='%23fff' stroke-width='3.2' stroke-linecap='round' stroke-linejoin='round' fill='none'/></svg>" },
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="ko">
      <body className={`${gothicA1.variable} ${geistMono.variable} antialiased`}>
        <AppShell>{children}</AppShell>
      </body>
    </html>
  );
}

import './globals.css';
import type { Metadata } from 'next';

export const metadata: Metadata = {
  title: 'Kosdaqpi Dashboard',
  description: 'Trading dashboard for kosdaqpi_bot_tr_best',
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="ko">
      <body>{children}</body>
    </html>
  );
}

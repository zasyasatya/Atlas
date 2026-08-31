import type { Metadata } from 'next';
import { BRAND_DEFAULTS } from '@/lib/brand-defaults';
import './globals.css';

// Static metadata is the pre-hydration shell. It reads the shared fallback
// constants (a server component may not dot into the 'use client' brand module -
// Next rejects it at build time) and is corrected from GET /api/config once the
// page is live, so a rebranded deployment needs no rebuild and no edit here.
export const metadata: Metadata = {
  title: `${BRAND_DEFAULTS.name} - ${BRAND_DEFAULTS.tagline}`,
  description: BRAND_DEFAULTS.subtitle,
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}

// The fallback half of the brand: no React, no 'use client', no fetch.
//
// It lives apart from `brand.ts` because the two have different consumers. The
// hook in brand.ts is client-only, but `app/layout.tsx` renders metadata on the
// server during `next build`, and Next refuses to let a server component dot into
// a client module ("Cannot access tagline.toString on the server"). A plain module
// like this one is readable from both sides, which keeps the static export and the
// hydrated page saying the same thing instead of disagreeing for a frame.
//
// These values must equal the defaults in backend/app/core/config.py;
// tests/branding.py compares them so the pair cannot drift apart silently.

export type Brand = {
  name: string;
  tagline: string;
  label: string;
  subtitle: string;
  docs_url: string;
};

export const BRAND_DEFAULTS: Brand = {
  name: 'ATLAS',
  tagline: 'Applied AI & Data Research Platform',
  label: 'Applied AI Platform',
  subtitle: 'Datasets, models and live apps in one place - from the first notebook to a deployed app on your own domain.',
  docs_url: '',
};

'use client';

// Brand identity, with exactly one owner per side.
//
// The server is the source of truth (ATLAS_APP_NAME / ATLAS_APP_TAGLINE /
// ATLAS_APP_TAGLINE_SHORT / ATLAS_APP_SUBTITLE), because rebranding a deployment
// is an env change and not a rebuild of the UI bundle - a static export cannot
// know a client's name at compile time. The values here are only what the first
// paint falls back to, so a rebrand never flashes the old name under text the
// reader has already seen. The fallbacks live in ./brand-defaults so the server
// renderer can share them.
//
// tests/branding.py checks the fallbacks equal the backend defaults, and that no
// component hardcodes the wordmark any more.

import React from 'react';
import { API_BASE } from './api';
import { BRAND_DEFAULTS, Brand } from './brand-defaults';

export type { Brand };
export { BRAND_DEFAULTS };

let current: Brand = BRAND_DEFAULTS;
let prefix = 'app';
const listeners = new Set<(b: Brand) => void>();
let requested = false;

export function getBrand(): Brand {
  return current;
}

/** The path deployed apps are mounted under, as the server configured it. */
export function getAppPrefix(): string {
  return prefix;
}

function applyDocument(b: Brand) {
  if (typeof document === 'undefined') return;
  // Part of the product, not of the build: the tab title and description follow the
  // deployment's brand instead of the strings compiled into the static export.
  document.title = `${b.name} - ${b.tagline}`;
  const meta = document.querySelector('meta[name="description"]');
  if (meta) meta.setAttribute('content', b.subtitle);
}

/** Fetch GET /api/config once per page load, then tell everyone who is listening. */
export function loadBrand(): Promise<Brand> {
  if (requested) return Promise.resolve(current);
  requested = true;
  return fetch(`${API_BASE}/api/config`)
    .then((r) => (r.ok ? r.json() : null))
    .then((c: any) => {
      if (c?.brand) {
        current = { ...BRAND_DEFAULTS, ...c.brand };
        if (c.app_prefix) prefix = String(c.app_prefix).replace(/^\/+|\/+$/g, '');
        listeners.forEach((fn) => fn(current));
        applyDocument(current);
      }
      return current;
    })
    .catch(() => current);
}

/** Subscribe a component to the brand. Falls back to the defaults until loaded. */
export function useBrand(): Brand {
  const [brand, setBrand] = React.useState<Brand>(current);
  React.useEffect(() => {
    let mounted = true;
    const fn = (b: Brand) => { if (mounted) setBrand(b); };
    listeners.add(fn);
    loadBrand().then((b) => { if (mounted) setBrand(b); });
    return () => { mounted = false; listeners.delete(fn); };
  }, []);
  return brand;
}

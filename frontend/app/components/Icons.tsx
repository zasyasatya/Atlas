'use client';
import React from 'react';

type P = { className?: string; size?: number; stroke?: number };
const S = ({ className = '', size = 18, stroke = 1.6, children }: P & { children: React.ReactNode }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor"
       strokeWidth={stroke} strokeLinecap="round" strokeLinejoin="round" className={className}>
    {children}
  </svg>
);

export const IcGrid = (p: P) => <S {...p}><rect x="3" y="3" width="7" height="7" rx="1.5"/><rect x="14" y="3" width="7" height="7" rx="1.5"/><rect x="3" y="14" width="7" height="7" rx="1.5"/><rect x="14" y="14" width="7" height="7" rx="1.5"/></S>;
export const IcBook = (p: P) => <S {...p}><path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20"/><path d="M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2z"/></S>;
export const IcFlask = (p: P) => <S {...p}><path d="M9 3h6"/><path d="M10 3v6.5L4.5 19a2 2 0 0 0 1.7 3h11.6a2 2 0 0 0 1.7-3L14 9.5V3"/><path d="M7 15h10"/></S>;
export const IcDatabase = (p: P) => <S {...p}><ellipse cx="12" cy="5" rx="8" ry="3"/><path d="M4 5v6c0 1.7 3.6 3 8 3s8-1.3 8-3V5"/><path d="M4 11v6c0 1.7 3.6 3 8 3s8-1.3 8-3v-6"/></S>;
export const IcRocket = (p: P) => <S {...p}><path d="M4.5 16.5c-1.5 1.3-2 5-2 5s3.7-.5 5-2c.7-.8.7-2.1-.1-2.9a2 2 0 0 0-2.9-.1z"/><path d="M12 15l-3-3a22 22 0 0 1 2-3.9A12.9 12.9 0 0 1 22 2c0 2.7-.8 7.7-6 11a22 22 0 0 1-4 2z"/><path d="M9 12H5s.5-2.8 2-4c1.7-1.3 5 0 5 0"/><path d="M12 15v4s2.8-.5 4-2c1.3-1.7 0-5 0-5"/></S>;
export const IcApps = (p: P) => <S {...p}><rect x="2" y="4" width="20" height="16" rx="2"/><path d="M2 9h20M6 6.5h.01M9 6.5h.01"/></S>;
export const IcUsers = (p: P) => <S {...p}><path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M22 21v-2a4 4 0 0 0-3-3.9"/><path d="M16 3.1a4 4 0 0 1 0 7.8"/></S>;
export const IcActivity = (p: P) => <S {...p}><path d="M22 12h-4l-3 9L9 3l-3 9H2"/></S>;
export const IcScan = (p: P) => <S {...p}><path d="M3 7V5a2 2 0 0 1 2-2h2M17 3h2a2 2 0 0 1 2 2v2M21 17v2a2 2 0 0 1-2 2h-2M7 21H5a2 2 0 0 1-2-2v-2"/><path d="M7 12h10"/></S>;
export const IcLayers = (p: P) => <S {...p}><path d="M12 2 2 7l10 5 10-5-10-5z"/><path d="m2 17 10 5 10-5"/><path d="m2 12 10 5 10-5"/></S>;
export const IcFileText = (p: P) => <S {...p}><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><path d="M14 2v6h6M16 13H8M16 17H8M10 9H8"/></S>;
export const IcTrend = (p: P) => <S {...p}><path d="m22 7-8.5 8.5-5-5L2 17"/><path d="M16 7h6v6"/></S>;
export const IcChat = (p: P) => <S {...p}><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/></S>;
export const IcSpark = (p: P) => <S {...p}><path d="M12 3v4M12 17v4M3 12h4M17 12h4M5.6 5.6l2.8 2.8M15.6 15.6l2.8 2.8M18.4 5.6l-2.8 2.8M8.4 15.6l-2.8 2.8"/></S>;
export const IcPlay = (p: P) => <S {...p}><path d="m5 3 14 9-14 9V3z"/></S>;
export const IcCheck = (p: P) => <S {...p}><path d="M20 6 9 17l-5-5"/></S>;
export const IcX = (p: P) => <S {...p}><path d="M18 6 6 18M6 6l12 12"/></S>;
export const IcAlert = (p: P) => <S {...p}><path d="M12 9v4M12 17h.01"/><path d="M10.3 3.9 1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0z"/></S>;
export const IcUpload = (p: P) => <S {...p}><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><path d="M17 8l-5-5-5 5M12 3v12"/></S>;
export const IcDownload = (p: P) => <S {...p}><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><path d="M7 10l5 5 5-5M12 15V3"/></S>;
export const IcPlus = (p: P) => <S {...p}><path d="M12 5v14M5 12h14"/></S>;
export const IcTrash = (p: P) => <S {...p}><path d="M3 6h18M8 6V4a1 1 0 0 1 1-1h6a1 1 0 0 1 1 1v2M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6"/></S>;
export const IcEdit = (p: P) => <S {...p}><path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"/><path d="M18.5 2.5a2.1 2.1 0 0 1 3 3L12 15l-4 1 1-4z"/></S>;
export const IcArrowRight = (p: P) => <S {...p}><path d="M5 12h14M12 5l7 7-7 7"/></S>;
export const IcArrowLeft = (p: P) => <S {...p}><path d="M19 12H5M12 19l-7-7 7-7"/></S>;
export const IcExternal = (p: P) => <S {...p}><path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"/><path d="M15 3h6v6M10 14 21 3"/></S>;
export const IcClock = (p: P) => <S {...p}><circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/></S>;
export const IcGpu = (p: P) => <S {...p}><rect x="2" y="6" width="20" height="12" rx="2"/><path d="M6 10h4v4H6zM14 10h4M14 14h4"/></S>;
export const IcCpu = (p: P) => <S {...p}><rect x="5" y="5" width="14" height="14" rx="2"/><rect x="9" y="9" width="6" height="6"/><path d="M9 2v3M15 2v3M9 19v3M15 19v3M2 9h3M2 15h3M19 9h3M19 15h3"/></S>;
export const IcMenu = (p: P) => <S {...p}><path d="M3 12h18M3 6h18M3 18h18"/></S>;
export const IcLogout = (p: P) => <S {...p}><path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4"/><path d="m16 17 5-5-5-5M21 12H9"/></S>;
export const IcSettings = (p: P) => <S {...p}><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 1 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06A1.65 1.65 0 0 0 4.6 15a1.65 1.65 0 0 0-1.51-1H3a2 2 0 1 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06A1.65 1.65 0 0 0 9 4.6a1.65 1.65 0 0 0 1-1.51V3a2 2 0 1 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06A1.65 1.65 0 0 0 19.4 9v0a1.65 1.65 0 0 0 1.51 1H21a2 2 0 1 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z"/></S>;
export const IcSlides = (p: P) => <S {...p}><rect x="2" y="3" width="20" height="14" rx="2"/><path d="M8 21h8M12 17v4"/></S>;
export const IcTrophy = (p: P) => <S {...p}><path d="M6 9H4.5a2.5 2.5 0 0 1 0-5H6M18 9h1.5a2.5 2.5 0 0 0 0-5H18"/><path d="M6 2h12v7a6 6 0 0 1-12 0V2z"/><path d="M9 22h6M12 15v7"/></S>;
export const IcTarget = (p: P) => <S {...p}><circle cx="12" cy="12" r="9"/><circle cx="12" cy="12" r="5"/><circle cx="12" cy="12" r="1.5"/></S>;
export const IcCode = (p: P) => <S {...p}><path d="m16 18 6-6-6-6M8 6l-6 6 6 6"/></S>;
export const IcImage = (p: P) => <S {...p}><rect x="3" y="3" width="18" height="18" rx="2"/><circle cx="9" cy="9" r="2"/><path d="m21 15-5-5L5 21"/></S>;
export const IcHelp = (p: P) => <S {...p}><circle cx="12" cy="12" r="9"/><path d="M9.1 9a3 3 0 0 1 5.8 1c0 2-3 3-3 3M12 17h.01"/></S>;
export const IcRefresh = (p: P) => <S {...p}><path d="M3 12a9 9 0 0 1 15-6.7L21 8"/><path d="M21 3v5h-5M21 12a9 9 0 0 1-15 6.7L3 16"/><path d="M3 21v-5h5"/></S>;
export const IcCloud = (p: P) => <S {...p}><path d="M17.5 19a4.5 4.5 0 1 0-1.4-8.8A6 6 0 1 0 6.3 19z"/></S>;
export const IcLock = (p: P) => <S {...p}><rect x="3" y="11" width="18" height="11" rx="2"/><path d="M7 11V7a5 5 0 0 1 10 0v4"/></S>;

export const ICON_MAP: Record<string, (p: P) => JSX.Element> = {
  activity: IcActivity, scan: IcScan, 'file-text': IcFileText, 'trending-up': IcTrend,
  'message-square': IcChat, layers: IcLayers, sparkles: IcSpark, database: IcDatabase,
  rocket: IcRocket, book: IcBook, target: IcTarget, flask: IcFlask,
};

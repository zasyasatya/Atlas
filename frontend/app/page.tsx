'use client';
import { useRouter } from 'next/navigation';
import { useEffect } from 'react';
import { auth } from '@/lib/api';

export default function Home() {
  const router = useRouter();
  useEffect(() => { router.replace(auth.token() ? '/dashboard' : '/login'); }, [router]);
  return <div className="min-h-screen grid place-items-center bg-paper text-[13px] text-ink-faint">ATLAS</div>;
}

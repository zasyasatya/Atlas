import type { Metadata } from 'next';
import './globals.css';

export const metadata: Metadata = {
  title: 'ATLAS - AI Internship Operating System',
  description:
    'Author AI curriculum, run GPU notebooks, ship Streamlit and Gradio apps, and prove graduation readiness.',
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}

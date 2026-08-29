import type { Config } from 'tailwindcss';

const config: Config = {
  content: ['./app/**/*.{ts,tsx}', './lib/**/*.{ts,tsx}'],
  theme: {
    extend: {
      fontFamily: {
        sans: ['var(--font-sans)', 'ui-sans-serif', 'system-ui', 'sans-serif'],
      },
      colors: {
        paper:   { DEFAULT: '#F6F8F6', deep: '#EEF2EE', card: '#FFFFFF' },
        ink:     { DEFAULT: '#12160F', soft: '#3E463A', muted: '#6E7669', faint: '#9AA394' },
        sage:    { 50:'#F0F5F1', 100:'#DDE8DF', 200:'#BCD1C1', 300:'#94B69D',
                   400:'#6E9A7B', 500:'#5B8C6E', 600:'#487058', 700:'#3A5A47',
                   800:'#2E4739', 900:'#22352B' },
        line:    { DEFAULT: '#E2E8E2', strong: '#CBD5CB' },
        signal:  { ok:'#4C8C5C', warn:'#B8862F', bad:'#B4533F', info:'#4F7D8C', idle:'#8A9285' },
      },
      borderRadius: { xl: '14px', '2xl': '20px', '3xl': '28px' },
      boxShadow: {
        soft: '0 1px 2px rgba(18,22,15,0.04), 0 8px 24px -12px rgba(18,22,15,0.10)',
        lift: '0 2px 6px rgba(18,22,15,0.06), 0 20px 40px -20px rgba(18,22,15,0.18)',
      },
      letterSpacing: { eyebrow: '0.16em' },
      keyframes: {
        rise: { '0%': { opacity:'0', transform:'translateY(8px)' }, '100%': { opacity:'1', transform:'translateY(0)' } },
        pulseSoft: { '0%,100%': { opacity:'1' }, '50%': { opacity:'0.45' } },
      },
      animation: { rise: 'rise .4s cubic-bezier(.2,.7,.3,1) both', pulseSoft: 'pulseSoft 1.8s ease-in-out infinite' },
    },
  },
  plugins: [],
};
export default config;

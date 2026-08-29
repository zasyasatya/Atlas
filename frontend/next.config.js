/** @type {import('next').NextConfig} */
const isExport = process.env.BUILD_EXPORT === '1';

const nextConfig = {
  ...(isExport ? { output: 'export' } : {}),
  images: { unoptimized: true },
  eslint: { ignoreDuringBuilds: true },
  typescript: { ignoreBuildErrors: true },
  ...(isExport ? {} : {
    async rewrites() {
      return [{ source: '/api/:path*', destination: 'http://127.0.0.1:8000/api/:path*' }];
    },
  }),
};
module.exports = nextConfig;

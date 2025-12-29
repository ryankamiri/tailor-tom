import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  /* config options here */
  // Disable Turbopack to use webpack (which handles path aliases better)
  // This ensures @/ path aliases work correctly in Vercel builds
  experimental: {
    turbo: {},
  },
};

export default nextConfig;

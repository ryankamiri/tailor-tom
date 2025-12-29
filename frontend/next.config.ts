import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  /* config options here */
  // Ensure path aliases work correctly with Turbopack
  experimental: {
    turbo: {
      resolveAlias: {
        "@": "./",
      },
    },
  },
};

export default nextConfig;

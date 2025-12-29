import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  /* config options here */
  // Configure Turbopack to properly resolve path aliases
  experimental: {
    turbo: {
      resolveAlias: {
        "@": "./",
      },
    },
  },
};

export default nextConfig;

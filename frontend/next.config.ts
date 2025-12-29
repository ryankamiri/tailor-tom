import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Disable Turbopack to fix path alias resolution issues with Root Directory
  experimental: {
    turbo: false,
  },
};

export default nextConfig;

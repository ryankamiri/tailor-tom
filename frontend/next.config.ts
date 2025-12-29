import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Use webpack instead of Turbopack to fix path alias resolution issues with Vercel Root Directory
  webpack: (config) => {
    return config;
  },
};

export default nextConfig;

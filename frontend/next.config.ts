import type { NextConfig } from "next";
import path from "path";

const nextConfig: NextConfig = {
  // Use webpack instead of Turbopack to fix path alias resolution issues with Vercel Root Directory
  webpack: (config, { dir }) => {
    // Explicitly resolve path aliases for webpack using the build directory
    config.resolve.alias = {
      ...config.resolve.alias,
      '@': path.resolve(dir),
    };
    return config;
  },
};

export default nextConfig;

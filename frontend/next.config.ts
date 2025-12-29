import type { NextConfig } from "next";
import path from "path";

const nextConfig: NextConfig = {
  /* config options here */
  // Explicitly configure for Turbopack path resolution
  // This helps Vercel's Turbopack resolve @/ path aliases correctly
  typescript: {
    // Let TypeScript handle path resolution
  },
  // Ensure baseUrl is respected
  experimental: {
    // Turbopack should read from tsconfig.json, but we ensure it's explicit
  },
};

export default nextConfig;

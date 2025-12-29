import type { NextConfig } from "next";
import path from "path";

const nextConfig: NextConfig = {
  // Use webpack instead of Turbopack to fix path alias resolution issues with Vercel Root Directory
  webpack: (config, { dir }) => {
    // Ensure webpack resolves modules from the current directory (frontend/)
    config.resolve.modules = [
      path.resolve(dir),
      'node_modules',
      ...(config.resolve.modules || []),
    ];
    
    // Add file extensions for TypeScript
    config.resolve.extensions = [
      '.tsx',
      '.ts',
      '.jsx',
      '.js',
      ...(config.resolve.extensions || []),
    ];
    
    return config;
  },
};

export default nextConfig;

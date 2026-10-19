import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // The Docker image runs the minimal standalone server; local builds skip it (on Windows
  // it needs symlink privileges).
  output: process.env.NEXT_STANDALONE === "1" ? "standalone" : undefined,
  poweredByHeader: false,
  cacheComponents: true,
  partialPrefetching: true,
  turbopack: {
    rules: {
      "*.css": {
        loaders: ["@tailwindcss/turbopack"],
        as: "*.css",
      },
    },
  },
};

export default nextConfig;

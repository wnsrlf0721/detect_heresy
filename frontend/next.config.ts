import type { NextConfig } from "next";

const apiInternalUrl = process.env.API_INTERNAL_URL;

const nextConfig: NextConfig = {
  ...(apiInternalUrl && {
    output: "standalone",
    async rewrites() {
      return [{ source: "/api/:path*", destination: `${apiInternalUrl}/:path*` }];
    },
  }),
  cacheComponents: true,
  partialPrefetching: true,
  experimental: {
    agentUpgrade: "security",
  },
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

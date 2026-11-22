import type { NextConfig } from "next";

const API = process.env.LIFEOS_API_URL ?? "http://127.0.0.1:8765";

const nextConfig: NextConfig = {
  // The browser only talks to Next; Next proxies /api to the localhost FastAPI service.
  async rewrites() {
    return [{ source: "/api/:path*", destination: `${API}/api/:path*` }];
  },
  experimental: { optimizePackageImports: ["@mantine/core", "@mantine/hooks", "@tabler/icons-react"] },
};

export default nextConfig;

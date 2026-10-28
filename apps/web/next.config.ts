import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  reactStrictMode: true,
  // The repo does not ship an ESLint config for apps/web yet; type safety is
  // enforced by `tsc --noEmit` (see the `typecheck` script) and by `next build`.
  eslint: { ignoreDuringBuilds: true },
};

export default nextConfig;

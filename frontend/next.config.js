/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  experimental: {
    typedRoutes: true,
  },
  async rewrites() {
    return [
      { source: "/api/provisioning/:path*", destination: "http://localhost:8000/:path*" },
      { source: "/api/subscriptions/:path*", destination: "http://localhost:8212/:path*" },
      { source: "/api/entitlements/:path*", destination: "http://localhost:8003/:path*" },
      { source: "/api/catalog/:path*", destination: "http://localhost:8005/:path*" },
      { source: "/api/pricing/:path*", destination: "http://localhost:8007/:path*" },
      { source: "/api/payments/:path*", destination: "http://localhost:8216/:path*" },
      { source: "/api/orders/:path*", destination: "http://localhost:8213/:path*" },
      { source: "/api/identity/:path*", destination: "http://localhost:8217/:path*" },
      { source: "/api/ledger/:path*", destination: "http://localhost:8218/:path*" },
      { source: "/api/notifications/:path*", destination: "http://localhost:8220/:path*" },
      { source: "/api/events/:path*", destination: "http://localhost:8221/:path*" },
      { source: "/api/usage/:path*", destination: "http://localhost:8222/:path*" }
    ];
  },
};

module.exports = nextConfig;



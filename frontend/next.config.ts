import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Product images are served from frontend/public/product-images, so no remote
  // hosts are needed. If NEXT_PUBLIC_PRODUCT_IMAGE_BASE_URL is pointed at a CDN,
  // add that host to images.remotePatterns here.
};

export default nextConfig;

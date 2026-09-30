"use client";

import { useRouter } from "next/navigation";

/**
 * Uses history back rather than `<Link href="/">` so the listing's filters,
 * search query or vector search are still applied on return, instead of
 * landing back on the unfiltered "/" listing.
 */
export default function BackToProductsButton() {
  const router = useRouter();

  return (
    <button
      type="button"
      onClick={() => router.back()}
      className="inline-flex items-center gap-2 rounded-full border border-violet-200 px-4 py-2 text-sm font-medium text-violet-800 transition-colors hover:bg-violet-50"
    >
      <span aria-hidden>←</span>
      Back to products
    </button>
  );
}

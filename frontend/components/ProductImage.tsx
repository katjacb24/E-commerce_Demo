"use client";

import Image from "next/image";
import { useState } from "react";

import { resolveImageUrl } from "@/lib/products";

type ProductImageProps = {
  image: string;
  name: string;
  color: string;
  sizes: string;
  priority?: boolean;
  className?: string;
};

/**
 * Seed documents reference a bare image filename. The asset may not be present
 * in `public/product-images/`, so fall back to a swatch tinted with the
 * product's own colour rather than rendering a broken image.
 */
const COLOR_SWATCHES: Record<string, string> = {
  black: "#1c1c1c",
  charcoal: "#36393d",
  grey: "#9aa0a6",
  gray: "#9aa0a6",
  white: "#f4f4f5",
  cream: "#f3ead8",
  beige: "#e4d7c1",
  sand: "#e0cfae",
  tan: "#c8a27a",
  brown: "#7b5230",
  khaki: "#b3a06a",
  olive: "#6b7141",
  green: "#3f7d4e",
  mint: "#a8dcc0",
  teal: "#2f7f7f",
  blue: "#3b6ea8",
  navy: "#2a3757",
  purple: "#6b4ea8",
  lavender: "#c4b6e3",
  mauve: "#b088a0",
  pink: "#e6a3b8",
  red: "#b8404a",
  burgundy: "#6f2436",
  rust: "#b05c33",
  orange: "#d97a35",
  yellow: "#e3c14f",
  gold: "#c9a227",
};

function swatchFor(color: string): string {
  const normalized = color.trim().toLowerCase();
  if (COLOR_SWATCHES[normalized]) {
    return COLOR_SWATCHES[normalized];
  }

  // Multi-word colours such as "light blue" or "dark grey": match on any token.
  const token = normalized.split(/[\s/-]+/).find((part) => COLOR_SWATCHES[part]);
  return token ? COLOR_SWATCHES[token] : "#ede9fe";
}

export default function ProductImage({
  image,
  name,
  color,
  sizes,
  priority = false,
  className = "object-cover",
}: ProductImageProps) {
  const [failed, setFailed] = useState(false);

  if (failed || !image) {
    return (
      <div
        className="flex h-full w-full items-center justify-center"
        style={{ backgroundColor: swatchFor(color) }}
        role="img"
        aria-label={`${name} — no image available`}
      >
        <span className="px-3 text-center text-xs font-medium uppercase tracking-[0.14em] text-white mix-blend-difference">
          {color}
        </span>
      </div>
    );
  }

  return (
    <Image
      src={resolveImageUrl(image)}
      alt={name}
      fill
      priority={priority}
      sizes={sizes}
      className={className}
      onError={() => setFailed(true)}
    />
  );
}

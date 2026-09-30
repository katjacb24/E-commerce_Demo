import Link from "next/link";

import ProductImage from "@/components/ProductImage";
import {
  formatPrice,
  formatSearchScore,
  formatSimilarityScore,
  type ProductCategory,
  type ProductPrice,
} from "@/lib/products";

type ProductCardProps = {
  sku: string;
  name: string;
  image: string;
  color: string;
  category: ProductCategory;
  price: ProductPrice;
  /** Relevance score. Left out — and hidden — outside search modes. */
  score?: number;
  /** Which search produced `score`, so the badge shows the right label/units. */
  scoreKind?: "similarity" | "fts";
};

export default function ProductCard({
  sku,
  name,
  image,
  color,
  category,
  price,
  score,
  scoreKind = "similarity",
}: ProductCardProps) {
  return (
    <Link
      href={`/products/${encodeURIComponent(sku)}`}
      className="group flex h-full flex-col overflow-hidden rounded-2xl border border-violet-100 bg-white shadow-[0_10px_30px_rgba(17,17,17,0.06)] transition-all hover:-translate-y-1 hover:shadow-[0_16px_36px_rgba(109,40,217,0.18)]"
    >
      <div className="relative aspect-square w-full overflow-hidden bg-violet-50">
        <ProductImage
          image={image}
          name={name}
          color={color}
          sizes="(max-width: 768px) 100vw, (max-width: 1200px) 50vw, 25vw"
          className="object-cover transition-transform duration-300 group-hover:scale-105"
        />
      </div>
      <div className="flex flex-1 flex-col p-4">
        <h2 className="line-clamp-2 text-base font-semibold text-black">{name}</h2>
        <p className="mt-2 text-xs leading-5 text-black/65">
          <span className="capitalize">{color}</span>
          {" · "}
          {category.subtype}
        </p>
        <p className="mt-4 text-lg font-semibold text-violet-800">{formatPrice(price)}</p>
        {score === undefined ? null : scoreKind === "fts" ? (
          <span className="mt-3 inline-flex w-fit items-center gap-1 self-end rounded-full bg-violet-100 px-2.5 py-1 text-[11px] font-semibold tracking-wide text-violet-800">
            Score {formatSearchScore(score)}
          </span>
        ) : (
          <span
            className={`mt-3 inline-flex w-fit items-center gap-1 self-end rounded-full px-2.5 py-1 text-[11px] font-semibold tracking-wide ${
              score > 0.5 ? "bg-green-100 text-green-800" : "bg-yellow-100 text-yellow-800"
            }`}
          >
            Similarity {formatSimilarityScore(score)}
          </span>
        )}
      </div>
    </Link>
  );
}

import { notFound } from "next/navigation";

import BackToProductsButton from "@/components/BackToProductsButton";
import ProductImage from "@/components/ProductImage";
import { apiUrl } from "@/lib/api";
import { formatPrice, type ProductDetail } from "@/lib/products";

type PageProps = {
  params: Promise<{ id: string }>;
};

function formatStock(stock: number): string {
  if (stock <= 0) {
    return "Out of stock";
  }
  if (stock < 15) {
    return `Low stock — ${stock} left`;
  }
  return `In stock — ${stock} available`;
}

async function fetchProductBySku(sku: string): Promise<ProductDetail | null> {
  // A 404 is an expected outcome here, so this one does not use fetchJson.
  const url = apiUrl(`/api/products/${encodeURIComponent(sku)}`);
  const response = await fetch(url.toString(), { cache: "no-store" });

  if (response.status === 404) {
    return null;
  }

  if (!response.ok) {
    throw new Error("Unable to load product details.");
  }

  return (await response.json()) as ProductDetail;
}

/**
 * The dynamic segment arrives decoded on a full page load but still
 * percent-encoded on a client-side navigation, so anything outside the plain
 * SKU charset (the "::" of a `product::SKU` document key, say) would otherwise
 * be encoded a second time by the fetch below and miss the document.
 */
function decodeSegment(segment: string): string {
  try {
    return decodeURIComponent(segment);
  } catch {
    // A stray "%" that is not a valid escape — take the segment as it stands.
    return segment;
  }
}

export default async function ProductDetailPage(props: PageProps) {
  // The dynamic segment carries the product SKU, which is also its document key
  // (the backend accepts it with or without the `product::` prefix).
  const { id } = await props.params;
  const sku = decodeSegment(id);

  let product: ProductDetail | null;

  try {
    product = await fetchProductBySku(sku);
  } catch {
    return (
      <main className="flex flex-1 items-center justify-center px-6 py-12 sm:px-10">
        <section className="w-full max-w-3xl rounded-3xl border border-red-200 bg-white p-8 text-center shadow-[0_12px_36px_rgba(17,17,17,0.08)]">
          <h1 className="text-2xl font-semibold text-black">Product details are unavailable</h1>
          <p className="mt-3 text-black/70">
            The product service could not be reached. Please check the backend and try again.
          </p>
        </section>
      </main>
    );
  }

  if (!product) {
    notFound();
  }

  return (
    <main className="flex flex-1 justify-center px-6 py-10 sm:px-10">
      <section className="w-full max-w-7xl rounded-3xl border border-violet-100 bg-white/95 p-5 shadow-[0_14px_34px_rgba(17,17,17,0.07)] sm:p-8">
        <div className="mb-6 flex items-center justify-between gap-4">
          <BackToProductsButton />
          <p className="text-xs font-semibold uppercase tracking-[0.16em] text-violet-700">
            Product Details
          </p>
        </div>

        <div className="grid grid-cols-1 gap-8 lg:grid-cols-[minmax(0,1.1fr)_minmax(0,1fr)] lg:gap-10">
          <div className="relative aspect-square overflow-hidden rounded-2xl bg-violet-50">
            <ProductImage
              image={product.image}
              name={product.name}
              color={product.color}
              sizes="(max-width: 1024px) 100vw, 55vw"
              priority
            />
          </div>

          <div className="flex flex-col">
            <p className="text-xs font-medium uppercase tracking-[0.16em] text-violet-700">
              {product.category.department} · {product.category.type} · {product.category.subtype}
            </p>
            <h1 className="mt-2 text-3xl font-semibold text-black sm:text-4xl">{product.name}</h1>
            <p className="mt-4 text-base leading-7 text-black/70">{product.description}</p>

            <p className="mt-6 text-3xl font-semibold text-violet-800">
              {formatPrice(product.price)}
            </p>
            <p
              className={`mt-2 text-sm font-medium ${
                product.stock <= 0
                  ? "text-red-700"
                  : product.stock < 15
                    ? "text-amber-700"
                    : "text-emerald-700"
              }`}
            >
              {formatStock(product.stock)}
            </p>

            <div className="mt-6 flex items-center gap-3">
              <button
                type="button"
                aria-label="Save to favourites"
                className="inline-flex h-11 w-11 items-center justify-center rounded-full border border-violet-200 text-violet-700 transition-colors hover:bg-violet-50"
              >
                <svg
                  xmlns="http://www.w3.org/2000/svg"
                  viewBox="0 0 24 24"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth="1.8"
                  className="h-5 w-5"
                >
                  <path
                    strokeLinecap="round"
                    strokeLinejoin="round"
                    d="M12 21s-6.716-4.26-9.183-7.223A5.5 5.5 0 0112 6.36a5.5 5.5 0 019.183 7.417C18.716 16.74 12 21 12 21z"
                  />
                </svg>
              </button>

              <button
                type="button"
                disabled={product.stock <= 0}
                className="inline-flex h-11 items-center justify-center rounded-full bg-violet-700 px-7 text-sm font-semibold text-white transition-colors hover:bg-violet-800 disabled:cursor-not-allowed disabled:bg-black/25"
              >
                Add to Bag
              </button>
            </div>

            <dl className="mt-8 grid grid-cols-1 gap-3 text-sm text-black/75 sm:grid-cols-2">
              <div>
                <dt className="font-medium text-black">SKU</dt>
                <dd className="mt-1 font-mono text-xs">{product.sku}</dd>
              </div>
              <div>
                <dt className="font-medium text-black">Colour</dt>
                <dd className="mt-1 capitalize">{product.color}</dd>
              </div>
              <div>
                <dt className="font-medium text-black">Material</dt>
                <dd className="mt-1">{product.material}</dd>
              </div>
              <div>
                <dt className="font-medium text-black">Sizes</dt>
                <dd className="mt-1">{product.sizes.join(", ") || "N/A"}</dd>
              </div>
            </dl>

            {product.tags.length > 0 ? (
              <div className="mt-6 flex flex-wrap gap-2">
                {product.tags.map((tag) => (
                  <span
                    key={tag}
                    className="rounded-full border border-violet-200 bg-violet-50 px-3 py-1 text-xs text-violet-900"
                  >
                    {tag}
                  </span>
                ))}
              </div>
            ) : null}
          </div>
        </div>
      </section>
    </main>
  );
}

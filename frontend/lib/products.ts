import { envOrDefault } from "./api";

export const DEFAULT_PRODUCT_IMAGE_BASE_URL = "/product-images/";

export type ProductCategory = {
  department: string;
  type: string;
  subtype: string;
};

export type ProductPrice = {
  amount: number;
  currency: string;
};

export type ProductSummary = {
  sku: string;
  name: string;
  image: string;
  color: string;
  category: ProductCategory;
  price: ProductPrice;
  sizes: string[];
};

export type ProductDetail = ProductSummary & {
  description: string;
  material: string;
  tags: string[];
  stock: number;
};

export type ProductsApiResponse = {
  total: number;
  page: number;
  pageSize: number;
  items: ProductSummary[];
};

/**
 * A full-text search hit: a product plus the relevance score Couchbase's
 * Search service assigned it. Unlike vector search's `score`, this is not
 * normalized to [0, 1] — it's whatever the FTS scoring model (TF-IDF/BM25)
 * returned, so higher still means a better match but there is no fixed ceiling.
 */
export type ProductSearchTextResult = ProductSummary & {
  score: number;
};

/** Response of GET /api/products/search. */
export type ProductSearchApiResponse = {
  total: number;
  page: number;
  pageSize: number;
  items: ProductSearchTextResult[];
  /** The full-text search request body Couchbase actually ran to produce this ranking. */
  ftsQuery: string;
};

/**
 * A vector-search hit: a product plus how close it was to the query embedding.
 * `score` is a 0–1 similarity derived from `distance` (higher is closer).
 */
export type ProductSearchResult = ProductSummary & {
  score: number;
  distance: number;
};

/** Response of GET /api/products/vector-search. */
export type ProductVectorSearchApiResponse = {
  total: number;
  page: number;
  pageSize: number;
  items: ProductSearchResult[];
  /** The SQL++ statement Couchbase actually ran to produce this ranking. */
  sqlQuery: string;
};

/**
 * What the listing page renders, from either endpoint. `score` is present only
 * on vector-search hits, so the tile can hide the field outside that mode.
 */
export type ProductListingItem = ProductSummary & { score?: number };

export type ProductListingResponse = {
  total: number;
  page: number;
  pageSize: number;
  items: ProductListingItem[];
};

/** Response of GET /api/products/facets — distinct filter values per department. */
export type ProductFacetsApiResponse = {
  types: string[];
  subtypes: string[];
  colors: string[];
  sizes: string[];
  minPrice: number;
  maxPrice: number;
};

export const DEPARTMENTS = ["Men", "Women"] as const;
export type Department = (typeof DEPARTMENTS)[number];

export const PRODUCT_TYPES = ["Tops", "Bottoms", "Activewear", "Footwear"] as const;
export type ProductType = (typeof PRODUCT_TYPES)[number];

export type SortBy = "name_asc" | "name_desc" | "price_asc" | "price_desc";

export const DEFAULT_SORT_BY: SortBy = "name_asc";

export const SORT_OPTIONS: Array<{ value: SortBy; label: string }> = [
  { value: "name_asc", label: "Name: A to Z" },
  { value: "name_desc", label: "Name: Z to A" },
  { value: "price_asc", label: "Price: Low to High" },
  { value: "price_desc", label: "Price: High to Low" },
];

export function isDepartment(value: string | undefined): value is Department {
  return DEPARTMENTS.includes(value as Department);
}

export function isProductType(value: string | undefined): value is ProductType {
  return PRODUCT_TYPES.includes(value as ProductType);
}

export function parseSortBy(value: string | undefined): SortBy {
  const match = SORT_OPTIONS.find((option) => option.value === value);
  return match ? match.value : DEFAULT_SORT_BY;
}

/**
 * Parses a price coming from a URL parameter or a numeric input. Blank,
 * non-numeric and negative values are all treated as "no bound given".
 */
export function parseNonNegativeNumber(value: string | undefined | null): number | undefined {
  if (!value || !value.trim()) {
    return undefined;
  }

  const parsed = Number.parseFloat(value);
  if (Number.isNaN(parsed) || parsed < 0) {
    return undefined;
  }

  return parsed;
}

/**
 * `score` is a cosine similarity in [0, 1] (the backend derives it from the
 * L2_SQUARED distance over unit-normalized embeddings). Shown as the raw
 * number rather than "% match" since it isn't a match probability.
 */
export function formatSimilarityScore(score: number): string {
  return score.toFixed(3);
}

/**
 * `score` is a Couchbase full-text search relevance score (TF-IDF/BM25-based),
 * not bounded to [0, 1] like the vector similarity score.
 */
export function formatSearchScore(score: number): string {
  return score.toFixed(3);
}

export function formatPrice(price: ProductPrice): string {
  return new Intl.NumberFormat("de-DE", {
    style: "currency",
    currency: price.currency,
    maximumFractionDigits: 2,
  }).format(price.amount);
}

/**
 * Documents store a bare filename (e.g. "39773.jpg"). Resolve it against the
 * configured image base, defaulting to `public/product-images/`. If the asset is
 * absent, ProductImage falls back to a placeholder tile.
 */
export function resolveImageUrl(image: string): string {
  const base = envOrDefault(
    process.env.NEXT_PUBLIC_PRODUCT_IMAGE_BASE_URL,
    DEFAULT_PRODUCT_IMAGE_BASE_URL
  );
  if (/^https?:\/\//i.test(image)) {
    return image;
  }
  return `${base.replace(/\/+$/, "")}/${image.replace(/^\/+/, "")}`;
}

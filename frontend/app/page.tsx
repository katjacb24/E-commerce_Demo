import Link from "next/link";
import FilterPanel from "@/components/FilterPanel";
import ProductCard from "@/components/ProductCard";
import FullTextQueryInfo from "@/components/FullTextQueryInfo";
import VectorQueryInfo from "@/components/VectorQueryInfo";
import { apiUrl, fetchJson } from "@/lib/api";
import {
  isDepartment,
  isProductType,
  parseNonNegativeNumber,
  parseSortBy,
  type Department,
  type ProductFacetsApiResponse,
  type ProductListingResponse,
  type ProductSearchApiResponse,
  type ProductsApiResponse,
  type ProductType,
  type ProductVectorSearchApiResponse,
  type SortBy,
} from "@/lib/products";

type ProductFilters = {
  sortBy: SortBy;
  department?: Department;
  type?: ProductType;
  subtype?: string;
  color?: string;
  size?: string;
  minPrice?: number;
  maxPrice?: number;
};

type ProductFilterOptions = {
  types: string[];
  subtypes: string[];
  colors: string[];
  sizes: string[];
  minPrice: number;
  maxPrice: number;
};

// Alphabetical ordering is wrong for garment sizes; age-based (4Y, 6Y…) and
// numeric (30, 32…) sizes fall through to a natural sort below.
const LETTER_SIZE_ORDER = ["XXS", "XS", "S", "M", "L", "XL", "XXL", "XXXL"];

type SearchParamValue = string | string[] | undefined;
type SearchParamsMap = Record<string, SearchParamValue>;
type PageProps = {
  searchParams: Promise<SearchParamsMap>;
};

const PAGE_SIZE = 20;

function normalizeParam(value: SearchParamValue): string | undefined {
  if (Array.isArray(value)) {
    return value[0];
  }
  return value;
}

function parsePositiveInteger(value: string | undefined, fallbackValue: number): number {
  if (!value) {
    return fallbackValue;
  }

  const parsed = Number.parseInt(value, 10);
  if (Number.isNaN(parsed) || parsed < 1) {
    return fallbackValue;
  }

  return parsed;
}

function compareSizes(a: string, b: string): number {
  const aLetter = LETTER_SIZE_ORDER.indexOf(a.toUpperCase());
  const bLetter = LETTER_SIZE_ORDER.indexOf(b.toUpperCase());

  if (aLetter !== -1 && bLetter !== -1) {
    return aLetter - bLetter;
  }
  if (aLetter !== -1) {
    return -1;
  }
  if (bLetter !== -1) {
    return 1;
  }

  // "30" / "32" and "4Y" / "10Y" both sort by their leading number.
  const aNumber = Number.parseInt(a, 10);
  const bNumber = Number.parseInt(b, 10);
  if (!Number.isNaN(aNumber) && !Number.isNaN(bNumber) && aNumber !== bNumber) {
    return aNumber - bNumber;
  }

  return a.localeCompare(b);
}

function buildPageHref(searchParams: SearchParamsMap, nextPage: number): string {
  const params = new URLSearchParams();

  Object.entries(searchParams).forEach(([key, value]) => {
    if (key === "page") {
      return;
    }

    if (Array.isArray(value)) {
      value.forEach((entry) => params.append(key, entry));
      return;
    }

    if (typeof value === "string") {
      params.set(key, value);
    }
  });

  params.set("page", String(nextPage));
  return `/?${params.toString()}`;
}

function fetchProducts(page: number, filters: ProductFilters): Promise<ProductsApiResponse> {
  const url = apiUrl("/api/products", {
    page,
    pageSize: PAGE_SIZE,
    sortBy: filters.sortBy,
    department: filters.department,
    type: filters.type,
    subtype: filters.subtype,
    color: filters.color,
    size: filters.size,
    minPrice: filters.minPrice,
    maxPrice: filters.maxPrice,
  });

  return fetchJson<ProductsApiResponse>(url, "Unable to load products.");
}

/**
 * Search is scoped to the department, because the department tab stays visible
 * (and highlighted) while a query is active.
 */
function fetchSearchResults(
  query: string,
  page: number,
  department?: Department
): Promise<ProductSearchApiResponse> {
  const url = apiUrl("/api/products/search", {
    q: query,
    department,
    page,
    pageSize: PAGE_SIZE,
  });

  return fetchJson<ProductSearchApiResponse>(url, "Unable to load search results.");
}

/**
 * Semantic search: the description is embedded by the Capella-hosted model and
 * ranked by the composite vector index server-side. The sidebar filters are sent
 * along, because the vector query applies them as predicates rather than
 * ignoring them.
 */
function fetchVectorSearchResults(
  description: string,
  page: number,
  filters: ProductFilters
): Promise<ProductVectorSearchApiResponse> {
  const url = apiUrl("/api/products/vector-search", {
    q: description,
    department: filters.department,
    type: filters.type,
    subtype: filters.subtype,
    color: filters.color,
    size: filters.size,
    minPrice: filters.minPrice,
    maxPrice: filters.maxPrice,
    page,
    pageSize: PAGE_SIZE,
  });

  return fetchJson<ProductVectorSearchApiResponse>(url, "Unable to load search results.");
}

/**
 * Facet values are aggregated server-side over the whole department, so they do
 * not depend on how many products fit on one page. They are scoped to the
 * department only: narrowing further (e.g. type plus subtype) can still produce
 * an empty listing.
 */
async function fetchFilterOptions(department?: Department): Promise<ProductFilterOptions> {
  const facets = await fetchJson<ProductFacetsApiResponse>(
    apiUrl("/api/products/facets", { department }),
    "Unable to load filter options."
  );

  return {
    types: facets.types,
    subtypes: facets.subtypes,
    colors: facets.colors,
    // Garment sizes need domain ordering, which SQL++ cannot express.
    sizes: [...facets.sizes].sort(compareSizes),
    minPrice: Math.floor(facets.minPrice),
    maxPrice: Math.ceil(facets.maxPrice),
  };
}

export default async function Home(props: PageProps) {
  const rawSearchParams = await props.searchParams;
  const query = normalizeParam(rawSearchParams.q)?.trim() ?? "";
  const isSearchMode = query.length > 0;

  // The keyword search bar wins over the sidebar's description box: it hides the
  // sidebar entirely, so a vector query left in the URL would be unreachable.
  const descriptionQuery = normalizeParam(rawSearchParams.vq)?.trim() ?? "";
  const isVectorMode = !isSearchMode && descriptionQuery.length > 0;

  const departmentParam = normalizeParam(rawSearchParams.department);
  const department = isDepartment(departmentParam) ? departmentParam : undefined;

  const typeParam = normalizeParam(rawSearchParams.type);
  const page = parsePositiveInteger(normalizeParam(rawSearchParams.page), 1);

  const filters: ProductFilters = {
    sortBy: parseSortBy(normalizeParam(rawSearchParams.sortBy)),
    department,
    type: isProductType(typeParam) ? typeParam : undefined,
    subtype: normalizeParam(rawSearchParams.subtype),
    color: normalizeParam(rawSearchParams.color),
    size: normalizeParam(rawSearchParams.size),
    minPrice: parseNonNegativeNumber(normalizeParam(rawSearchParams.minPrice)),
    maxPrice: parseNonNegativeNumber(normalizeParam(rawSearchParams.maxPrice)),
  };

  let productsData: ProductListingResponse;
  let filterOptions: ProductFilterOptions | null = null;
  let vectorSqlQuery: string | undefined;
  let fullTextQuery: string | undefined;

  try {
    if (isSearchMode) {
      const searchResult = await fetchSearchResults(query, page, department);
      productsData = searchResult;
      fullTextQuery = searchResult.ftsQuery;
    } else if (isVectorMode) {
      // The sidebar stays mounted in vector mode: it holds the description box
      // and the "Clear all" button that exits this mode.
      const [vectorResult, options] = await Promise.all([
        fetchVectorSearchResults(descriptionQuery, page, filters),
        fetchFilterOptions(department),
      ]);
      productsData = vectorResult;
      filterOptions = options;
      vectorSqlQuery = vectorResult.sqlQuery;
    } else {
      [productsData, filterOptions] = await Promise.all([
        fetchProducts(page, filters),
        fetchFilterOptions(department),
      ]);
    }
  } catch {
    return (
      <main className="flex flex-1 items-center justify-center px-6 py-12 sm:px-10">
        <section className="w-full max-w-3xl rounded-3xl border border-red-200 bg-white p-8 text-center shadow-[0_12px_36px_rgba(17,17,17,0.08)]">
          <h1 className="text-2xl font-semibold text-black">Products are unavailable</h1>
          <p className="mt-3 text-black/70">
            The listing service could not be reached. Please check the backend and try again.
          </p>
        </section>
      </main>
    );
  }

  const { total, items } = productsData;
  const hasPreviousPage = page > 1;
  const hasNextPage = page * PAGE_SIZE < total;
  // In either search mode the department tab stays highlighted and the query
  // honours it, so the heading names it too rather than implying an unscoped search.
  const departmentSuffix = department ? ` in ${department}` : "";
  const heading = isSearchMode
    ? `Product Suggestions`
    : isVectorMode
      ? `Product Suggestions`
      : (department ?? "All Products");
  const eyebrow = isSearchMode
    ? "Full-Text Search Results"
    : isVectorMode
      ? "Vector Search Results"
      : "Product Listing";

  return (
    <main className="flex flex-1 justify-center px-6 py-10 sm:px-10">
      <section className="w-full max-w-7xl">
        <div
          className={`mb-6 grid grid-cols-1 gap-6 ${isSearchMode ? "" : "lg:grid-cols-[280px_minmax(0,1fr)] lg:items-start"}`}
        >
          {!isSearchMode && filterOptions ? (
            <FilterPanel
              sortBy={filters.sortBy}
              selectedType={filters.type}
              selectedSubtype={filters.subtype}
              selectedSize={filters.size}
              selectedColor={filters.color}
              minPrice={filters.minPrice}
              maxPrice={filters.maxPrice}
              descriptionQuery={descriptionQuery}
              availableTypes={filterOptions.types}
              availableSubtypes={filterOptions.subtypes}
              availableSizes={filterOptions.sizes}
              availableColors={filterOptions.colors}
              availableMinPrice={filterOptions.minPrice}
              availableMaxPrice={filterOptions.maxPrice}
            />
          ) : null}

          <div>
            <div className="mb-6 flex flex-wrap items-end justify-between gap-4">
              <div>
                <p className="text-xs font-semibold uppercase tracking-[0.18em] text-violet-700">
                  {eyebrow}
                </p>
                <h1 className="mt-2 flex flex-wrap items-center gap-2 text-3xl font-semibold text-black sm:text-4xl">
                  <span>{heading}</span>
                  {isVectorMode && vectorSqlQuery ? (
                    <VectorQueryInfo sqlQuery={vectorSqlQuery} />
                  ) : null}
                  {isSearchMode && fullTextQuery ? (
                    <FullTextQueryInfo ftsQuery={fullTextQuery} />
                  ) : null}
                </h1>
                <p className="mt-2 text-sm text-black/65">
                  Showing {items.length} of {total} products
                </p>
              </div>
            </div>

            {items.length === 0 ? (
              <section className="rounded-3xl border border-violet-100 bg-white p-10 text-center shadow-[0_10px_30px_rgba(17,17,17,0.06)]">
                <h2 className="text-2xl font-semibold text-black">No products found</h2>
                <p className="mt-3 text-black/65">
                  {isSearchMode
                    ? "Try a different search term or clear the search field to return to the category view."
                    : isVectorMode
                      ? "Try describing the product differently, or press “Clear all” to return to the full listing."
                      : "Try clearing some filters to see more products."}
                </p>
              </section>
            ) : (
              <>
                <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
                  {items.map((product) => (
                    <div key={product.sku} className="mx-auto w-full max-w-[220px]">
                      <ProductCard
                        sku={product.sku}
                        name={product.name}
                        image={product.image}
                        color={product.color}
                        category={product.category}
                        price={product.price}
                        score={product.score}
                        scoreKind={isSearchMode ? "fts" : "similarity"}
                      />
                    </div>
                  ))}
                </div>

                <div className="mt-8 flex items-center justify-between rounded-2xl border border-violet-100 bg-white px-4 py-3 text-sm shadow-[0_8px_22px_rgba(17,17,17,0.05)]">
                  <Link
                    href={buildPageHref(rawSearchParams, page - 1)}
                    aria-disabled={!hasPreviousPage}
                    className={`rounded-full px-4 py-2 font-medium transition-colors ${
                      hasPreviousPage
                        ? "text-violet-800 hover:bg-violet-50"
                        : "pointer-events-none text-black/35"
                    }`}
                  >
                    Previous
                  </Link>

                  <p className="text-black/75">Page {page}</p>

                  <Link
                    href={buildPageHref(rawSearchParams, page + 1)}
                    aria-disabled={!hasNextPage}
                    className={`rounded-full px-4 py-2 font-medium transition-colors ${
                      hasNextPage
                        ? "text-violet-800 hover:bg-violet-50"
                        : "pointer-events-none text-black/35"
                    }`}
                  >
                    Next
                  </Link>
                </div>
              </>
            )}
          </div>
        </div>
      </section>
    </main>
  );
}

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class ProductCategory(BaseModel):
    """Three-level classification, e.g. Men / Tops / Shirts."""

    department: str
    type: str
    subtype: str


class ProductPrice(BaseModel):
    amount: float = Field(ge=0)
    currency: str


class ProductSummary(BaseModel):
    """Fields needed to render a product in a listing or search result."""

    model_config = ConfigDict(populate_by_name=True, serialize_by_alias=True)

    sku: str
    name: str
    image: str
    color: str
    category: ProductCategory
    price: ProductPrice
    # Carried on the summary so the listing page can derive its size filter options.
    sizes: list[str]


class ProductDetail(ProductSummary):
    """Full product document as stored in Couchbase."""

    description: str
    material: str
    tags: list[str]
    stock: int = Field(ge=0)


class ProductSearchResult(ProductSummary):
    """A product hit plus how close it was to the vector query.

    `distance` is what APPROX_VECTOR_DISTANCE returned, in the units of the
    index's similarity metric (lower is closer). `score` normalises it to a
    0-1 similarity so the listing tiles have one comparable number to show
    regardless of which metric the index was built with.
    """

    score: float = Field(ge=0, le=1)
    distance: float


class ProductSearchTextResult(ProductSummary):
    """A product hit plus its Couchbase full-text search relevance score.

    `score` is whatever the Search service's scoring model (TF-IDF/BM25)
    assigned the hit. Unlike the vector search's `score`, it is not
    normalised to [0, 1] — higher still means a better match.
    """

    score: float = Field(ge=0)


class PaginatedProductsResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True, serialize_by_alias=True)

    total: int
    page: int
    page_size: int = Field(alias="pageSize")
    items: list[ProductSummary]


class PaginatedProductSearchTextResponse(BaseModel):
    """Same envelope as PaginatedProductsResponse, plus the FTS query used.

    A separate model from PaginatedProductsResponse so the plain listing
    endpoint (which has no search query to report) is not forced to carry it.
    """

    model_config = ConfigDict(populate_by_name=True, serialize_by_alias=True)

    total: int
    page: int
    page_size: int = Field(alias="pageSize")
    items: list[ProductSearchTextResult]
    # The full-text search request body actually sent to Couchbase's Search
    # service for this request, shown to the user so they can see how the
    # ranking was produced.
    fts_query: str = Field(alias="ftsQuery")


class PaginatedProductSearchResponse(BaseModel):
    """Same envelope as PaginatedProductsResponse, with scored items.

    A separate model is needed because `response_model` drives serialisation:
    reusing PaginatedProductsResponse would silently drop `score`/`distance`.
    """

    model_config = ConfigDict(populate_by_name=True, serialize_by_alias=True)

    total: int
    page: int
    page_size: int = Field(alias="pageSize")
    items: list[ProductSearchResult]
    # The SQL++ statement actually sent to Couchbase for this search, shown to
    # the user so they can see how the ranking was produced.
    sql_query: str = Field(alias="sqlQuery")


class ProductFacetsResponse(BaseModel):
    """Distinct filter values across a whole department, not just one page of it.

    Derived server-side so the listing page never has to infer facets from a
    capped page of products.
    """

    model_config = ConfigDict(populate_by_name=True, serialize_by_alias=True)

    types: list[str]
    subtypes: list[str]
    colors: list[str]
    sizes: list[str]
    min_price: float = Field(alias="minPrice", ge=0)
    max_price: float = Field(alias="maxPrice", ge=0)

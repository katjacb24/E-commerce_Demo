"use client";

import { useCallback, useEffect, useState, useTransition } from "react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";

import {
	DEFAULT_SORT_BY,
	SORT_OPTIONS,
	parseNonNegativeNumber,
	type SortBy,
} from "@/lib/products";
import Spinner from "@/components/Spinner";

type PendingAction = "vector" | "filter" | null;

type FilterKey = "type" | "subtype" | "size" | "color";

type FilterPanelProps = {
	sortBy: SortBy;
	selectedType?: string;
	selectedSubtype?: string;
	selectedSize?: string;
	selectedColor?: string;
	minPrice?: number;
	maxPrice?: number;
	/** Committed natural-language query (URL `vq`); empty when not in vector mode. */
	descriptionQuery: string;
	availableTypes: string[];
	availableSubtypes: string[];
	availableSizes: string[];
	availableColors: string[];
	availableMinPrice: number;
	availableMaxPrice: number;
};

/**
 * Keeps a price input in step with the value in the URL without fighting the
 * user's typing: while the text still parses to the committed number (e.g. "5."
 * or "5.0" for 5) it is left exactly as typed.
 */
function syncPriceInput(current: string, committed: number | undefined): string {
	if (parseNonNegativeNumber(current) === committed) {
		return current;
	}
	return committed === undefined ? "" : String(committed);
}

export default function FilterPanel({
	sortBy,
	selectedType,
	selectedSubtype,
	selectedSize,
	selectedColor,
	minPrice,
	maxPrice,
	descriptionQuery,
	availableTypes,
	availableSubtypes,
	availableSizes,
	availableColors,
	availableMinPrice,
	availableMaxPrice,
}: FilterPanelProps) {
	const router = useRouter();
	const pathname = usePathname();
	const searchParams = useSearchParams();

	const [isPending, startTransition] = useTransition();
	// Which action is in flight; stale once isPending goes false, but every read
	// of this is gated on `isPending` so the stale value is never shown.
	const [pendingAction, setPendingAction] = useState<PendingAction>(null);

	// A vector query is active: the listing is ordered by similarity, so the
	// "Sort By" control below has nothing to act on.
	const isVectorMode = descriptionQuery.length > 0;

	const [searchDescription, setSearchDescription] = useState(descriptionQuery);

	const [minPriceInput, setMinPriceInput] = useState(
		minPrice === undefined ? "" : String(minPrice)
	);
	const [maxPriceInput, setMaxPriceInput] = useState(
		maxPrice === undefined ? "" : String(maxPrice)
	);

	// The panel used to be remounted via a `key` whenever a filter changed, which
	// destroyed the price input's DOM node and stole focus mid-typing. It now stays
	// mounted, and the inputs follow the URL when it moves for a reason other than
	// typing ("Clear all", Back/Forward) by adjusting state during render.
	const [committedPrices, setCommittedPrices] = useState({ minPrice, maxPrice });
	if (committedPrices.minPrice !== minPrice || committedPrices.maxPrice !== maxPrice) {
		setCommittedPrices({ minPrice, maxPrice });
		setMinPriceInput((current) => syncPriceInput(current, minPrice));
		setMaxPriceInput((current) => syncPriceInput(current, maxPrice));
	}

	// Same idea for the description box: it follows the URL when that moves for a
	// reason other than typing, so "Clear all" and Back/Forward empty the field
	// instead of leaving a query behind that is no longer being applied.
	const [committedDescription, setCommittedDescription] = useState(descriptionQuery);
	if (committedDescription !== descriptionQuery) {
		setCommittedDescription(descriptionQuery);
		setSearchDescription(descriptionQuery);
	}

	const hasActiveFilters = Boolean(
		selectedType ||
			selectedSubtype ||
			selectedSize ||
			selectedColor ||
			minPrice !== undefined ||
			maxPrice !== undefined ||
			sortBy !== DEFAULT_SORT_BY ||
			isVectorMode
	);

	const replaceParams = useCallback(
		(mutate: (params: URLSearchParams) => void, action: Exclude<PendingAction, null> = "filter") => {
			const params = new URLSearchParams(searchParams.toString());
			mutate(params);
			setPendingAction(action);
			startTransition(() => {
				router.replace(`${pathname}?${params.toString()}`);
			});
		},
		[pathname, router, searchParams]
	);

	// Submitted explicitly rather than debounced like the price inputs: every run
	// costs one call to the Capella embedding model.
	const submitDescription = useCallback(() => {
		const trimmed = searchDescription.trim();

		replaceParams((params) => {
			if (trimmed) {
				params.set("vq", trimmed);
			} else {
				params.delete("vq");
			}
			params.set("page", "1");
		}, "vector");
	}, [replaceParams, searchDescription]);

	const setSingleValue = useCallback(
		(key: FilterKey, value?: string) => {
			replaceParams((params) => {
				const current = params.get(key);
				const shouldClear = !value || current === value;

				if (shouldClear) {
					params.delete(key);
				} else {
					params.set(key, value);
				}
				params.set("page", "1");
			});
		},
		[replaceParams]
	);

	useEffect(() => {
		const timeoutId = setTimeout(() => {
			const parsedMin = parseNonNegativeNumber(minPriceInput);
			const parsedMax = parseNonNegativeNumber(maxPriceInput);

			const nextMin = parsedMin === undefined ? undefined : String(parsedMin);
			const nextMax = parsedMax === undefined ? undefined : String(parsedMax);

			const currentMin = searchParams.get("minPrice") ?? undefined;
			const currentMax = searchParams.get("maxPrice") ?? undefined;

			if (currentMin === nextMin && currentMax === nextMax) {
				return;
			}

			replaceParams((params) => {
				if (nextMin === undefined) {
					params.delete("minPrice");
				} else {
					params.set("minPrice", nextMin);
				}

				if (nextMax === undefined) {
					params.delete("maxPrice");
				} else {
					params.set("maxPrice", nextMax);
				}

				params.set("page", "1");
			});
		}, 400);

		return () => clearTimeout(timeoutId);
	}, [maxPriceInput, minPriceInput, replaceParams, searchParams]);

	return (
		<aside className="relative z-20 rounded-3xl border border-violet-100 bg-violet-50/50 p-5 shadow-[0_10px_30px_rgba(17,17,17,0.06)] lg:sticky lg:top-24">
			<div className="flex items-center justify-between gap-3">
				<h2 className="flex items-center gap-2 text-base font-semibold text-black">
					Filters
					{isPending && pendingAction === "filter" ? (
						<Spinner className="h-4 w-4 text-violet-700" />
					) : null}
				</h2>
				<button
					type="button"
					disabled={!hasActiveFilters}
					onClick={() => {
						replaceParams((params) => {
							params.delete("type");
							params.delete("subtype");
							params.delete("size");
							params.delete("color");
							params.delete("minPrice");
							params.delete("maxPrice");
							params.delete("sortBy");
							// Drops the vector search too, so the unfiltered listing
							// comes back and the similarity score disappears with it.
							params.delete("vq");
							params.set("page", "1");
						});
					}}
					className="text-xs font-semibold uppercase tracking-[0.12em] text-violet-700 disabled:cursor-not-allowed disabled:text-black/35"
				>
					Clear all
				</button>
			</div>

			<div className="mt-5 space-y-6">
				<section>
					<label
						htmlFor="searchDescription"
						className="mb-2 flex items-center gap-1.5 text-sm font-medium text-black/80"
					>
						<svg
							xmlns="http://www.w3.org/2000/svg"
							aria-hidden
							className="h-7 w-7 flex-none text-violet-700"
							fill="none"
							viewBox="0 0 24 24"
							stroke="currentColor"
							strokeWidth={1.5}
						>
							<path
								strokeLinecap="round"
								strokeLinejoin="round"
								d="M9.813 15.904L9 18.75l-.813-2.846a4.5 4.5 0 00-3.09-3.09L2.25 12l2.846-.813a4.5 4.5 0 003.09-3.09L9 5.25l.813 2.846a4.5 4.5 0 003.09 3.09L15.75 12l-2.846.813a4.5 4.5 0 00-3.09 3.09z"
							/>
						</svg>
						Describe what you are looking for
						<span className="group relative inline-flex">
							<svg
								xmlns="http://www.w3.org/2000/svg"
								aria-hidden
								className="h-4 w-4 flex-none text-black/40"
								fill="none"
								viewBox="0 0 24 24"
								stroke="currentColor"
								strokeWidth={1.5}
							>
								<path
									strokeLinecap="round"
									strokeLinejoin="round"
									d="M11.25 11.25l.041-.02a.75.75 0 011.063.852l-.708 2.836a.75.75 0 001.063.853l.041-.021M21 12a9 9 0 11-18 0 9 9 0 0118 0zm-9-3.75h.008v.008H12V8.25z"
								/>
							</svg>
							<span
								role="tooltip"
								className="pointer-events-none absolute left-1/2 top-full z-10 mt-2 w-64 -translate-x-1/2 whitespace-pre-line rounded-xl bg-neutral-900 px-3 py-2 text-xs font-normal leading-5 text-white opacity-0 shadow-lg transition-opacity group-hover:opacity-100"
							>
								{
									"Describe what you are looking for and Couchbase Vector Search will find top-10 most semantically similar results in our inventory.\n\nUse the other filters below to further constrain your search."
								}
							</span>
						</span>
					</label>
					<textarea
						id="searchDescription"
						rows={2}
						value={searchDescription}
						onChange={(event) => setSearchDescription(event.target.value)}
						onKeyDown={(event) => {
							// Enter searches; Shift+Enter keeps its usual newline.
							if (event.key === "Enter" && !event.shiftKey) {
								event.preventDefault();
								submitDescription();
							}
						}}
						placeholder="men's chinos in black"
						className="w-full resize-none rounded-xl border border-violet-200 bg-white px-3 py-2 text-xs text-black focus:border-violet-700 focus:outline-none"
					/>
					<button
						type="button"
						onClick={submitDescription}
						disabled={(!searchDescription.trim() && !isVectorMode) || isPending}
						className="mt-2 flex h-9 w-full items-center justify-center gap-2 rounded-xl bg-violet-700 text-sm font-semibold text-white transition-colors hover:bg-violet-800 disabled:cursor-not-allowed disabled:bg-violet-200"
					>
						{isPending && pendingAction === "vector" ? (
							<>
								<Spinner className="h-4 w-4" />
								Searching…
							</>
						) : (
							"Search"
						)}
					</button>
				</section>

				{isVectorMode ? null : (
					<section>
						<label htmlFor="sortBy" className="mb-2 block text-sm font-medium text-black/80">
							Sort By
						</label>
						<select
							id="sortBy"
							value={sortBy}
							onChange={(event) => {
								const value = event.target.value as SortBy;
								replaceParams((params) => {
									if (value === DEFAULT_SORT_BY) {
										params.delete("sortBy");
									} else {
										params.set("sortBy", value);
									}
									params.set("page", "1");
								});
							}}
							className="h-10 w-full rounded-xl border border-violet-200 bg-white px-3 text-xs text-black focus:border-violet-700 focus:outline-none"
						>
							{SORT_OPTIONS.map((option) => (
								<option key={option.value} value={option.value}>
									{option.label}
								</option>
							))}
						</select>
					</section>
				)}

				<section>
					<h3 className="mb-2 text-sm font-medium text-black/80">Price</h3>
					<div className="grid grid-cols-2 gap-2">
						<label className="text-xs text-black/60">
							Min
							<input
								type="number"
								inputMode="decimal"
								min={0}
								step="1"
								placeholder={String(availableMinPrice)}
								value={minPriceInput}
								onChange={(event) => setMinPriceInput(event.target.value)}
								className="mt-1 h-10 w-full rounded-xl border border-violet-200 px-3 text-xs text-black focus:border-violet-700 focus:outline-none"
							/>
						</label>
						<label className="text-xs text-black/60">
							Max
							<input
								type="number"
								inputMode="decimal"
								min={0}
								step="1"
								placeholder={String(availableMaxPrice)}
								value={maxPriceInput}
								onChange={(event) => setMaxPriceInput(event.target.value)}
								className="mt-1 h-10 w-full rounded-xl border border-violet-200 px-3 text-xs text-black focus:border-violet-700 focus:outline-none"
							/>
						</label>
					</div>
				</section>

				<section>
					<h3 className="mb-2 text-sm font-medium text-black/80">Type</h3>
					<div className="flex flex-wrap gap-2">
						{availableTypes.map((type) => {
							const active = selectedType === type;
							return (
								<button
									key={type}
									type="button"
									aria-pressed={active}
									onClick={() => setSingleValue("type", type)}
									className={`rounded-full border px-3 py-1.5 text-xs transition-colors ${
										active
											? "border-violet-700 bg-violet-700 text-white"
											: "border-violet-200 bg-white text-black/80 hover:border-violet-400 hover:bg-violet-50"
									}`}
								>
									{type}
								</button>
							);
						})}
					</div>
				</section>

				<section>
					<h3 className="mb-2 text-sm font-medium text-black/80">Product</h3>
					<div className="flex flex-wrap gap-2">
						{availableSubtypes.map((subtype) => {
							const active = selectedSubtype === subtype;
							return (
								<button
									key={subtype}
									type="button"
									aria-pressed={active}
									onClick={() => setSingleValue("subtype", subtype)}
									className={`rounded-full border px-3 py-1.5 text-xs transition-colors ${
										active
											? "border-violet-700 bg-violet-700 text-white"
											: "border-violet-200 bg-white text-black/80 hover:border-violet-400 hover:bg-violet-50"
									}`}
								>
									{subtype}
								</button>
							);
						})}
					</div>
				</section>

				<section>
					<h3 className="mb-2 text-sm font-medium text-black/80">Size</h3>
					<div className="flex flex-wrap gap-2">
						{availableSizes.map((size) => {
							const active = selectedSize === size;
							return (
								<button
									key={size}
									type="button"
									aria-pressed={active}
									onClick={() => setSingleValue("size", size)}
									className={`rounded-lg border px-3 py-1.5 text-xs transition-colors ${
										active
											? "border-violet-700 bg-violet-700 text-white"
											: "border-violet-200 bg-white text-black/80 hover:border-violet-400 hover:bg-violet-50"
									}`}
								>
									{size}
								</button>
							);
						})}
					</div>
				</section>

				<section>
					<h3 className="mb-2 text-sm font-medium text-black/80">Colour</h3>
					<div className="flex flex-wrap gap-2">
						{availableColors.map((color) => {
							const active = selectedColor === color;
							return (
								<button
									key={color}
									type="button"
									aria-pressed={active}
									onClick={() => setSingleValue("color", color)}
									className={`rounded-full border px-3 py-1.5 text-xs capitalize transition-colors ${
										active
											? "border-violet-700 bg-violet-700 text-white"
											: "border-violet-200 bg-white text-black/80 hover:border-violet-400 hover:bg-violet-50"
									}`}
								>
									{color}
								</button>
							);
						})}
					</div>
				</section>
			</div>
		</aside>
	);
}

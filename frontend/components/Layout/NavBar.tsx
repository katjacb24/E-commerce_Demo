"use client";

import { useRouter, useSearchParams, usePathname } from "next/navigation";
import Link from "next/link";
import { Cinzel } from "next/font/google";
import { useCallback, useEffect, useRef, useState, useTransition } from "react";

import { DEPARTMENTS, type Department } from "@/lib/products";
import Spinner from "@/components/Spinner";
import type { DemoUser } from "@/lib/auth";

// "All" clears the department filter; the API treats it as optional.
const DEPARTMENT_TABS = ["All", ...DEPARTMENTS] as const;
type DepartmentTab = (typeof DEPARTMENT_TABS)[number];

const logoFont = Cinzel({
  subsets: ["latin"],
  weight: "600",
});

type NavBarProps = {
  isChatbotOpen: boolean;
  onToggleChatbot: () => void;
  isAdminView: boolean;
  onOpenAdmin: () => void;
  onReturnFromAdmin: () => void;
  currentUser: DemoUser | null;
  onOpenLogin: () => void;
  onLogout: () => void;
};

export default function NavBar({
  isChatbotOpen,
  onToggleChatbot,
  isAdminView,
  onOpenAdmin,
  onReturnFromAdmin,
  currentUser,
  onOpenLogin,
  onLogout,
}: NavBarProps) {
  const router = useRouter();
  const searchParams = useSearchParams();
  const pathname = usePathname();

  const currentDepartment = searchParams.get("department") ?? "All";
  const currentQuery = searchParams.get("q") ?? "";
  const [searchValue, setSearchValue] = useState(currentQuery);
  const [isProfileMenuOpen, setIsProfileMenuOpen] = useState(false);
  const profileMenuRef = useRef<HTMLDivElement>(null);

  const [isPending, startTransition] = useTransition();
  // Which navigation is in flight; stale once isPending goes false, but every
  // read of this is gated on `isPending` so the stale value is never shown.
  const [pendingKind, setPendingKind] = useState<"search" | "department" | null>(null);
  const [pendingTab, setPendingTab] = useState<DepartmentTab | null>(null);

  useEffect(() => {
    setSearchValue(currentQuery);
  }, [currentQuery]);

  useEffect(() => {
    if (!isProfileMenuOpen) {
      return;
    }

    const handleClickOutside = (event: MouseEvent) => {
      if (!profileMenuRef.current?.contains(event.target as Node)) {
        setIsProfileMenuOpen(false);
      }
    };

    document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, [isProfileMenuOpen]);

  const navigateToDepartment = useCallback(
    (tab: DepartmentTab) => {
      const params = new URLSearchParams(searchParams.toString());

      if (tab === "All") {
        params.delete("department");
      } else {
        params.set("department", tab as Department);
      }

      // Facet values are department-scoped, so a stale selection can yield an
      // empty listing. Reset them alongside the search query and page.
      params.delete("q");
      params.delete("page");
      params.delete("type");
      params.delete("subtype");
      params.delete("size");
      params.delete("color");

      const nextPath = pathname.startsWith("/products/") ? "/" : pathname;
      const nextQuery = params.toString();
      setPendingKind("department");
      setPendingTab(tab);
      startTransition(() => {
        router.push(nextQuery ? `${nextPath}?${nextQuery}` : nextPath);
      });
    },
    [router, searchParams, pathname]
  );

  const submitSearch = useCallback(
    (event: React.FormEvent<HTMLFormElement>) => {
      event.preventDefault();

      const params = new URLSearchParams(searchParams.toString());
      const trimmedQuery = searchValue.trim();

      params.delete("page");
      params.delete("type");
      params.delete("subtype");
      params.delete("size");
      params.delete("color");
      params.delete("minPrice");
      params.delete("maxPrice");
      params.delete("sortBy");
      // Keyword search hides the sidebar, which is the only way back out of a
      // vector search, so the description query goes with the filters.
      params.delete("vq");

      if (trimmedQuery) {
        params.set("q", trimmedQuery);
      } else {
        params.delete("q");
      }

      const nextPath = pathname.startsWith("/products/") ? "/" : pathname;
      const nextQuery = params.toString();
      setPendingKind("search");
      startTransition(() => {
        router.push(nextQuery ? `${nextPath}?${nextQuery}` : nextPath);
      });
    },
    [pathname, router, searchParams, searchValue]
  );

  const clearSearch = useCallback(() => {
    const params = new URLSearchParams(searchParams.toString());

    setSearchValue("");
    params.delete("q");
    params.delete("page");

    const nextPath = pathname.startsWith("/products/") ? "/" : pathname;
    const nextQuery = params.toString();
    setPendingKind("search");
    startTransition(() => {
      router.push(nextQuery ? `${nextPath}?${nextQuery}` : nextPath);
    });
  }, [pathname, router, searchParams]);

  if (isAdminView) {
    return (
      <header className="fixed top-0 left-0 right-0 z-50 bg-white/95 border-b border-violet-100 shadow-sm backdrop-blur">
        <div className="max-w-7xl mx-auto px-6 flex items-center h-16 gap-6">
          {/* Logo */}
          <span
            className={`${logoFont.className} text-2xl tracking-wide leading-none text-black shrink-0 mr-2`}
          >
            DemoShop
          </span>

          <button
            type="button"
            onClick={onReturnFromAdmin}
            className="ml-auto rounded-full bg-violet-700 px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-violet-800"
          >
            Return to DemoShop
          </button>
        </div>
      </header>
    );
  }

  return (
    <header className="fixed top-0 left-0 right-0 z-50 bg-white/95 border-b border-violet-100 shadow-sm backdrop-blur">
      <div className="max-w-7xl mx-auto px-6 flex items-center h-16 gap-6">
        {/* Left: logo + department tabs */}
        <div className="flex items-center gap-6 shrink-0">
          {/* Logo — always routes back to the unfiltered product listing */}
          <Link
            href="/"
            aria-label="DemoShop home"
            className={`${logoFont.className} text-2xl tracking-wide leading-none text-black shrink-0 transition-colors hover:text-violet-700`}
          >
            DemoShop
          </Link>

          {/* Department tabs */}
          <nav className="flex items-center gap-1">
            {DEPARTMENT_TABS.map((cat) => {
              const isActive = currentDepartment === cat;
              return (
                <button
                  key={cat}
                  onClick={() => navigateToDepartment(cat)}
                  className={`inline-flex items-center gap-1.5 px-4 py-1.5 text-sm font-medium rounded-full transition-colors ${
                    isActive
                      ? "bg-violet-700 text-white"
                      : "text-black/70 hover:text-black hover:bg-violet-50"
                  }`}
                >
                  {isPending && pendingKind === "department" && pendingTab === cat ? (
                    <Spinner className="h-3.5 w-3.5" />
                  ) : null}
                  {cat}
                </button>
              );
            })}
          </nav>
        </div>

        {/* Center: search bar, centred in the space between the tabs and the icon group */}
        <div className="flex flex-1 items-center justify-center gap-2">
          <form onSubmit={submitSearch} className="w-full max-w-sm">
            <div className="flex items-center gap-2 rounded-full border border-violet-200 bg-white pr-1 shadow-[0_4px_14px_rgba(17,17,17,0.04)] transition-colors focus-within:border-violet-700">
              <input
                type="search"
                value={searchValue}
                onChange={(event) => setSearchValue(event.target.value)}
                placeholder="Search products..."
                className="no-search-cancel h-9 flex-1 rounded-full bg-transparent px-4 text-sm focus:outline-none"
              />
              {searchValue ? (
                <button
                  type="button"
                  aria-label="Clear search"
                  onClick={clearSearch}
                  className="inline-flex h-8 w-8 items-center justify-center rounded-full text-black/55 transition-colors hover:bg-violet-50 hover:text-black"
                >
                  <svg
                    xmlns="http://www.w3.org/2000/svg"
                    className="h-4 w-4"
                    fill="none"
                    viewBox="0 0 24 24"
                    stroke="currentColor"
                    strokeWidth={2}
                  >
                    <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
                  </svg>
                </button>
              ) : null}
              <button
                type="submit"
                aria-label="Search products"
                disabled={isPending && pendingKind === "search"}
                className="inline-flex h-8 w-8 items-center justify-center rounded-full bg-violet-700 text-white transition-colors hover:bg-violet-800 disabled:cursor-not-allowed disabled:bg-violet-400"
              >
                {isPending && pendingKind === "search" ? (
                  <Spinner className="h-4 w-4" />
                ) : (
                  <svg
                    xmlns="http://www.w3.org/2000/svg"
                    className="h-4 w-4"
                    fill="none"
                    viewBox="0 0 24 24"
                    stroke="currentColor"
                    strokeWidth={2}
                  >
                    <path
                      strokeLinecap="round"
                      strokeLinejoin="round"
                      d="M21 21l-4.35-4.35m1.85-5.15a7 7 0 11-14 0 7 7 0 0114 0z"
                    />
                  </svg>
                )}
              </button>
            </div>
          </form>

          {/* Search bar info tooltip — hover only, not clickable */}
          <span className="group relative inline-flex shrink-0">
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
              className="pointer-events-none absolute left-1/2 top-full z-10 mt-2 w-56 -translate-x-1/2 whitespace-pre-line rounded-xl bg-neutral-900 px-3 py-2 text-xs font-normal leading-5 text-white opacity-0 shadow-lg transition-opacity group-hover:opacity-100"
            >
              {
                "Describe what you are looking for using keywords like 'Floral print'. Couchbase Full-Text Search will find the matching results in our inventory.\n\nMake sure that you selected the correct Tab 'All', 'Women' or 'Men' on the left-hand side, as the results will be filtered accordingly."
              }
            </span>
          </span>
        </div>

        {/* Icon group */}
        <div className="flex items-center gap-1 shrink-0">
          {/* My Profile — opens Log in/Sign up and Admin options */}
          <div className="relative" ref={profileMenuRef}>
            <button
              type="button"
              aria-label={currentUser ? `My Profile — signed in as ${currentUser.displayName}` : "My Profile"}
              aria-haspopup="menu"
              aria-expanded={isProfileMenuOpen}
              onClick={() => setIsProfileMenuOpen((prevValue) => !prevValue)}
              className={`p-2 rounded-full hover:bg-violet-50 transition-colors ${
                currentUser ? "text-violet-700" : "text-black/75"
              }`}
            >
              {/* Same silhouette either way; filled + violet once signed in. */}
              {currentUser ? (
                <svg
                  xmlns="http://www.w3.org/2000/svg"
                  className="h-6 w-6"
                  viewBox="0 0 24 24"
                  fill="currentColor"
                >
                  <path
                    fillRule="evenodd"
                    clipRule="evenodd"
                    d="M7.5 6a4.5 4.5 0 119 0 4.5 4.5 0 01-9 0zM3.751 20.105a8.25 8.25 0 0116.498 0 .75.75 0 01-.437.695A18.683 18.683 0 0112 22.5c-2.786 0-5.433-.608-7.812-1.7a.75.75 0 01-.437-.695z"
                  />
                </svg>
              ) : (
                <svg
                  xmlns="http://www.w3.org/2000/svg"
                  className="h-6 w-6"
                  fill="none"
                  viewBox="0 0 24 24"
                  stroke="currentColor"
                  strokeWidth={1.5}
                >
                  <path
                    strokeLinecap="round"
                    strokeLinejoin="round"
                    d="M15.75 7.5a3.75 3.75 0 11-7.5 0 3.75 3.75 0 017.5 0zM4.501 20.118a7.5 7.5 0 0114.998 0A17.933 17.933 0 0112 21.75c-2.676 0-5.216-.584-7.499-1.632z"
                  />
                </svg>
              )}
            </button>

            {isProfileMenuOpen ? (
              <div
                role="menu"
                aria-label="Profile options"
                className="absolute right-0 top-full mt-2 w-48 overflow-hidden rounded-xl border border-violet-100 bg-white py-1 shadow-[0_12px_28px_rgba(17,17,17,0.12)]"
              >
                {currentUser ? (
                  <>
                    <p className="px-4 py-2 text-xs text-black/50">
                      Signed in as{" "}
                      <span className="font-semibold text-black/75">{currentUser.displayName}</span>
                    </p>
                    <button
                      type="button"
                      role="menuitem"
                      onClick={() => {
                        setIsProfileMenuOpen(false);
                        onLogout();
                      }}
                      className="block w-full px-4 py-2 text-left text-sm text-black/80 transition-colors hover:bg-violet-50"
                    >
                      Log out
                    </button>
                  </>
                ) : (
                  <button
                    type="button"
                    role="menuitem"
                    onClick={() => {
                      setIsProfileMenuOpen(false);
                      onOpenLogin();
                    }}
                    className="block w-full px-4 py-2 text-left text-sm text-black/80 transition-colors hover:bg-violet-50"
                  >
                    Log in / Sign up
                  </button>
                )}
                <button
                  type="button"
                  role="menuitem"
                  onClick={() => {
                    setIsProfileMenuOpen(false);
                    onOpenAdmin();
                  }}
                  className="block w-full px-4 py-2 text-left text-sm text-black/80 transition-colors hover:bg-violet-50"
                >
                  Admin
                </button>
              </div>
            ) : null}
          </div>

          {/* My Bag — placeholder */}
          <button
            aria-label="My Bag"
            className="p-2 rounded-full hover:bg-violet-50 transition-colors text-black/75"
          >
            <svg
              xmlns="http://www.w3.org/2000/svg"
              className="h-6 w-6"
              fill="none"
              viewBox="0 0 24 24"
              stroke="currentColor"
              strokeWidth={1.5}
            >
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                d="M15.75 10.5V6a3.75 3.75 0 10-7.5 0v4.5m11.356-1.993l1.263 12c.07.665-.45 1.243-1.119 1.243H4.25a1.125 1.125 0 01-1.12-1.243l1.264-12A1.125 1.125 0 015.513 7.5h12.974c.576 0 1.059.435 1.119 1.007z"
              />
            </svg>
          </button>

          {/* Personal Assistant — toggles the ChatbotPanel rendered by AppShell */}
          <button
            aria-label="Personal Assistant"
            data-testid="ai-chatbot-toggle"
            aria-pressed={isChatbotOpen}
            onClick={onToggleChatbot}
            className="p-2 rounded-full bg-violet-700 text-white hover:bg-violet-800 transition-colors ml-1"
          >
            <svg
              xmlns="http://www.w3.org/2000/svg"
              className="h-6 w-6"
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
          </button>
        </div>
      </div>
    </header>
  );
}

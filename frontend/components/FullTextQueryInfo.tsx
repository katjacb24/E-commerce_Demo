"use client";

import { useEffect, useState } from "react";

type FullTextQueryInfoProps = {
  ftsQuery: string;
};

export default function FullTextQueryInfo({ ftsQuery }: FullTextQueryInfoProps) {
  const [isOpen, setIsOpen] = useState(false);

  useEffect(() => {
    if (!isOpen) {
      return;
    }

    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        setIsOpen(false);
      }
    };

    document.addEventListener("keydown", handleKeyDown);
    return () => document.removeEventListener("keydown", handleKeyDown);
  }, [isOpen]);

  return (
    <>
      <button
        type="button"
        aria-label="Full-Text Search"
        aria-expanded={isOpen}
        onClick={() => setIsOpen(true)}
        className="inline-flex h-7 w-7 items-center justify-center rounded-full text-violet-700 transition-colors hover:bg-violet-50"
      >
        <svg
          xmlns="http://www.w3.org/2000/svg"
          aria-hidden
          className="h-5 w-5"
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
      </button>

      {isOpen ? (
        <div
          role="presentation"
          onClick={() => setIsOpen(false)}
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4 backdrop-blur-sm"
        >
          <div
            role="dialog"
            aria-modal="true"
            aria-label="Full-text search query details"
            onClick={(event) => event.stopPropagation()}
            className="w-full max-w-[75vw] overflow-y-auto rounded-2xl border border-violet-300 bg-white p-6 shadow-2xl max-h-[85vh]"
          >
            <div className="flex items-start justify-between gap-4">
              <div className="flex items-center gap-2">
                <svg
                  xmlns="http://www.w3.org/2000/svg"
                  aria-hidden
                  className="h-6 w-6 flex-none text-violet-700"
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
                <h2 className="text-base font-semibold text-black">Full-Text Search</h2>
              </div>
              <button
                type="button"
                aria-label="Close"
                onClick={() => setIsOpen(false)}
                className="inline-flex h-8 w-8 flex-none items-center justify-center rounded-full text-black/60 transition-colors hover:bg-violet-50 hover:text-black"
              >
                <span aria-hidden className="text-xl leading-none">
                  ×
                </span>
              </button>
            </div>

            <p className="mt-4 text-sm text-black/80">
              These are the results of the full-text search performed in Couchbase using its{" "}
              <a
                href="https://docs.couchbase.com/cloud/search/search.html"
                target="_blank"
                rel="noopener noreferrer"
                className="text-violet-700 underline underline-offset-2 hover:text-violet-900"
              >Search service</a>
              . They are ranked by relevance to your search term.
            </p>
            <p className="mt-2 text-sm text-black/80">
              The following search query was used for this search:
            </p>
            <pre className="mt-3 overflow-x-auto rounded-xl bg-neutral-900 p-4 text-xs leading-5 text-violet-100">
              <code>{ftsQuery}</code>
            </pre>
          </div>
        </div>
      ) : null}
    </>
  );
}

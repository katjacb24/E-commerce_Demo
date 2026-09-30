import Link from "next/link";

export default function ProductNotFound() {
  return (
    <main className="flex flex-1 items-center justify-center px-6 py-12 sm:px-10">
      <section className="w-full max-w-3xl rounded-3xl border border-violet-100 bg-white p-8 text-center shadow-[0_12px_36px_rgba(17,17,17,0.08)]">
        <p className="text-xs font-semibold uppercase tracking-[0.18em] text-violet-700">404</p>
        <h1 className="mt-3 text-2xl font-semibold text-black sm:text-3xl">Product not found</h1>
        <p className="mt-3 text-black/70">
          This product may no longer exist or the link is incorrect.
        </p>
        <Link
          href="/"
          className="mt-6 inline-flex items-center justify-center rounded-full bg-violet-700 px-5 py-2.5 text-sm font-semibold text-white transition-colors hover:bg-violet-800"
        >
          Browse products
        </Link>
      </section>
    </main>
  );
}
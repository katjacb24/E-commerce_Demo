export default function ProductDetailLoading() {
  return (
    <main className="flex flex-1 justify-center px-6 py-10 sm:px-10">
      <section className="w-full max-w-7xl rounded-3xl border border-violet-100 bg-white/95 p-5 shadow-[0_14px_34px_rgba(17,17,17,0.07)] sm:p-8">
        <div className="mb-6 h-10 w-40 animate-pulse rounded-full bg-violet-100" />

        <div className="grid grid-cols-1 gap-8 lg:grid-cols-[minmax(0,1.1fr)_minmax(0,1fr)] lg:gap-10">
          <div className="aspect-square animate-pulse rounded-2xl bg-violet-100" />

          <div>
            <div className="h-10 w-4/5 animate-pulse rounded-lg bg-violet-100" />
            <div className="mt-4 h-5 w-full animate-pulse rounded bg-violet-100" />
            <div className="mt-2 h-5 w-11/12 animate-pulse rounded bg-violet-100" />
            <div className="mt-6 h-9 w-40 animate-pulse rounded-lg bg-violet-100" />

            <div className="mt-6 flex gap-3">
              <div className="h-11 w-11 animate-pulse rounded-full bg-violet-100" />
              <div className="h-11 w-32 animate-pulse rounded-full bg-violet-100" />
            </div>

            <div className="mt-8 grid grid-cols-1 gap-3 sm:grid-cols-2">
              <div className="h-12 animate-pulse rounded-lg bg-violet-100" />
              <div className="h-12 animate-pulse rounded-lg bg-violet-100" />
              <div className="h-12 animate-pulse rounded-lg bg-violet-100" />
              <div className="h-12 animate-pulse rounded-lg bg-violet-100" />
            </div>

            <div className="mt-8 h-12 animate-pulse rounded-2xl bg-violet-100" />
          </div>
        </div>
      </section>
    </main>
  );
}
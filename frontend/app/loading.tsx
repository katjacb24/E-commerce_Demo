export default function Loading() {
  return (
    <main className="flex flex-1 justify-center px-6 py-10 sm:px-10">
      <section className="w-full max-w-7xl animate-pulse">
        <div className="mb-6 space-y-3">
          <div className="h-3 w-32 rounded bg-violet-200" />
          <div className="h-8 w-64 rounded bg-violet-100" />
          <div className="h-4 w-40 rounded bg-violet-100" />
        </div>
        <div className="grid grid-cols-1 gap-5 sm:grid-cols-2 xl:grid-cols-4">
          {Array.from({ length: 8 }).map((_, index) => (
            <div key={index} className="overflow-hidden rounded-2xl border border-violet-100 bg-white p-4">
              <div className="aspect-square w-full rounded-xl bg-violet-100" />
              <div className="mt-4 h-4 w-4/5 rounded bg-violet-100" />
              <div className="mt-3 h-3 w-full rounded bg-violet-50" />
              <div className="mt-2 h-3 w-2/3 rounded bg-violet-50" />
              <div className="mt-4 h-5 w-1/3 rounded bg-violet-100" />
            </div>
          ))}
        </div>
      </section>
    </main>
  );
}
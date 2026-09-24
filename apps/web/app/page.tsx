import Link from "next/link";

export default function HomePage() {
  return (
    <main className="flex flex-1 items-center justify-center bg-zinc-50 px-6 py-16">
      <section className="w-full max-w-xl rounded-lg border border-zinc-200 bg-white p-8">
        <h1 className="text-2xl font-semibold text-zinc-900">AssistFlow</h1>
        <p className="mt-3 text-base leading-6 text-zinc-600">
          Customer support, running on this machine.
        </p>
        <Link
          href="/chat"
          className="mt-6 inline-flex min-h-11 items-center text-sm font-medium text-indigo-700 underline"
        >
          Open chat
        </Link>
      </section>
    </main>
  );
}

"use client";

import { ApiError, listLoginUsers, startSession } from "@/lib/api/client";
import type { LoginUser } from "@/lib/api/schemas";
import { useQuery } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { useState } from "react";

export default function LoginPage() {
  const router = useRouter();
  const [error, setError] = useState<string | null>(null);
  const [pendingKey, setPendingKey] = useState<string | null>(null);
  const usersQuery = useQuery({
    queryKey: ["login-users"],
    queryFn: listLoginUsers,
    retry: false,
  });

  async function signIn(user: LoginUser) {
    setError(null);
    setPendingKey(user.key);
    try {
      const session = await startSession(user.key);
      router.push(session.role === "support_agent" ? "/agent/inbox" : "/chat");
    } catch (caught) {
      const message =
        caught instanceof ApiError ? "Sign-in did not complete. Try again." : "Sign-in did not complete. Try again.";
      setError(message);
      setPendingKey(null);
    }
  }

  const users = usersQuery.data?.users ?? [];
  const customers = users.filter((user) => user.role === "customer");
  const staff = users.filter((user) => user.role === "support_agent");

  return (
    <main className="flex flex-1 items-center justify-center bg-zinc-50 px-6 py-16">
      <section className="w-full max-w-xl rounded-lg border border-zinc-200 bg-white p-8">
        <h1 className="text-2xl font-semibold text-zinc-900">Sign in</h1>
        <p className="mt-3 text-base leading-6 text-zinc-600">
          Choose a person for this local session. The server decides the tenant.
        </p>
        {usersQuery.isLoading ? <p className="mt-6 text-sm text-zinc-500">Loading people…</p> : null}
        {usersQuery.isError ? (
          <p className="mt-6 text-sm text-zinc-700" role="alert">
            Local sign-in is not available.
          </p>
        ) : null}
        {error ? (
          <p className="mt-6 text-sm text-zinc-700" role="alert">
            {error}
          </p>
        ) : null}
        <UserGroup title="Customers" users={customers} pendingKey={pendingKey} onSelect={(user) => void signIn(user)} />
        <UserGroup title="Support" users={staff} pendingKey={pendingKey} onSelect={(user) => void signIn(user)} />
      </section>
    </main>
  );
}

function UserGroup({
  title,
  users,
  pendingKey,
  onSelect,
}: {
  title: string;
  users: LoginUser[];
  pendingKey: string | null;
  onSelect: (user: LoginUser) => void;
}) {
  if (users.length === 0) {
    return null;
  }
  return (
    <div className="mt-6">
      <h2 className="text-sm font-semibold text-zinc-900">{title}</h2>
      <ul className="mt-2 flex flex-col gap-2">
        {users.map((user) => (
          <li key={user.key}>
            <button
              type="button"
              disabled={pendingKey !== null}
              onClick={() => onSelect(user)}
              className="flex min-h-11 w-full items-center justify-between rounded-md border border-zinc-200 px-3 text-left text-sm text-zinc-900 hover:bg-zinc-50 focus-visible:ring-2 focus-visible:ring-indigo-600 disabled:opacity-60"
            >
              <span>
                {user.label}
                <span className="text-zinc-500"> · {user.organization}</span>
              </span>
            </button>
          </li>
        ))}
      </ul>
    </div>
  );
}

"use client";

import { ErrorPanel } from "@/components/chat/states";
import { ApiError, readSession } from "@/lib/api/client";
import { readTicket } from "@/lib/api/staff";
import { absoluteTime, relativeTime } from "@/lib/chat/format";
import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect } from "react";

const NOTE_LABEL: Record<string, string> = {
  customer: "Customer",
  support: "Support",
  system: "System",
};

const TICKET_STATUS: Record<string, string> = {
  open: "Open",
  pending: "Pending",
  escalated: "Escalated",
  resolved: "Resolved",
};

export function TicketView({ ticketId }: { ticketId: string }) {
  const router = useRouter();
  const sessionQuery = useQuery({
    queryKey: ["session"],
    queryFn: readSession,
    retry: false,
  });
  const signedIn = sessionQuery.data?.role === "support_agent";
  const ticketQuery = useQuery({
    queryKey: ["staff-ticket", ticketId, sessionQuery.data?.key],
    queryFn: () => readTicket(ticketId),
    enabled: signedIn,
  });

  useEffect(() => {
    if (sessionQuery.isError && sessionQuery.error instanceof ApiError && sessionQuery.error.status === 401) {
      router.replace("/login");
    }
  }, [router, sessionQuery.error, sessionQuery.isError]);

  if (
    sessionQuery.isLoading ||
    (sessionQuery.isError && sessionQuery.error instanceof ApiError && sessionQuery.error.status === 401)
  ) {
    return (
      <main className="flex h-dvh items-center justify-center px-6">
        <p className="text-sm text-muted">Loading the ticket…</p>
      </main>
    );
  }

  if (!signedIn) {
    return (
      <main className="flex h-dvh items-center justify-center px-6">
        <h1 className="text-xl font-semibold text-text">You don&apos;t have access to this page.</h1>
      </main>
    );
  }

  const ticket = ticketQuery.data;
  return (
    <main className="mx-auto flex min-h-dvh w-full max-w-3xl flex-col gap-4 px-4 py-6">
      <p className="text-xs font-medium text-warning">Development staff</p>
      {ticketQuery.isLoading || sessionQuery.isLoading ? (
        <p className="text-sm text-muted">Loading the ticket…</p>
      ) : ticketQuery.isError || !ticket ? (
        <ErrorPanel onRetry={() => void ticketQuery.refetch()} />
      ) : (
        <>
          <header className="flex flex-wrap items-start justify-between gap-3">
            <h1 className="text-xl font-semibold break-words text-text">{ticket.summary}</h1>
            <p className="text-sm font-medium text-text">{TICKET_STATUS[ticket.status] ?? ticket.status}</p>
          </header>
          <p className="text-sm text-muted">
            {ticket.priority} priority · {ticket.category}
            {ticket.assignee_name ? ` · ${ticket.assignee_name}` : ""}
          </p>
          {ticket.conversation_id ? (
            <Link
              href={`/agent/conversations/${ticket.conversation_id}`}
              className="inline-flex min-h-11 items-center text-sm font-medium text-accent underline-offset-2 hover:underline focus-visible:ring-2 focus-visible:ring-accent"
            >
              Open conversation
            </Link>
          ) : null}
          <section>
            <h2 className="text-sm font-semibold text-text">Notes</h2>
            {ticket.notes.length === 0 ? (
              <p className="mt-2 text-sm text-muted">No notes yet.</p>
            ) : (
              <ul className="mt-2 flex flex-col gap-3">
                {ticket.notes.map((note) => (
                  <li key={note.id} className="rounded-lg border border-default bg-surface px-3 py-3">
                    <p className="text-sm text-text">{note.body}</p>
                    <p className="mt-1 text-xs text-muted">
                      {NOTE_LABEL[note.author_type] ?? note.author_type}
                      {" · "}
                      <time dateTime={note.created_at} title={absoluteTime(note.created_at)}>
                        {relativeTime(note.created_at)}
                      </time>
                    </p>
                  </li>
                ))}
              </ul>
            )}
          </section>
        </>
      )}
    </main>
  );
}

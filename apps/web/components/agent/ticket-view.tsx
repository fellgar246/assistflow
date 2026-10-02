"use client";

import { ErrorPanel } from "@/components/chat/states";
import { ApiError } from "@/lib/api/client";
import { listStaffActors, readTicket, type StaffHeaders } from "@/lib/api/staff";
import { absoluteTime, relativeTime } from "@/lib/chat/format";
import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { useSyncExternalStore } from "react";

const STAFF_KEY = "assistflow.localStaff";

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

function subscribe(onStoreChange: () => void): () => void {
  window.addEventListener("assistflow-staff", onStoreChange);
  return () => window.removeEventListener("assistflow-staff", onStoreChange);
}

export function TicketView({ ticketId }: { ticketId: string }) {
  const staffId = useSyncExternalStore(subscribe, () => window.localStorage.getItem(STAFF_KEY), () => null);
  const actorsQuery = useQuery({
    queryKey: ["staff-actors"],
    queryFn: listStaffActors,
    retry: false,
  });
  const actors = actorsQuery.data?.actors ?? [];
  const staff = actors.find((item) => item.agent_id === staffId) ?? actors[0] ?? null;
  const headers: StaffHeaders | null = staff
    ? { tenantId: staff.tenant_id, agentId: staff.agent_id }
    : null;
  const ticketQuery = useQuery({
    queryKey: ["staff-ticket", ticketId, headers?.agentId],
    queryFn: () => readTicket(headers!, ticketId),
    enabled: headers !== null,
  });

  if (actorsQuery.isError && actorsQuery.error instanceof ApiError && actorsQuery.error.status === 404) {
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
      {ticketQuery.isLoading || actorsQuery.isLoading ? (
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
          <section aria-label="Notes" className="flex flex-col gap-3">
            {ticket.notes.length === 0 ? (
              <p className="text-sm text-muted">No notes yet.</p>
            ) : (
              ticket.notes.map((note) => (
                <article key={note.id} className="rounded-lg border border-default bg-surface p-3">
                  <p className="text-sm font-medium text-text">
                    {NOTE_LABEL[note.author_type] ?? "Support"}
                  </p>
                  <p className="mt-1 text-[15px] leading-6 break-words text-text">{note.body}</p>
                  <time
                    dateTime={note.created_at}
                    title={absoluteTime(note.created_at)}
                    className="mt-1 block text-xs text-muted"
                  >
                    {relativeTime(note.created_at)}
                  </time>
                </article>
              ))
            )}
          </section>
        </>
      )}
    </main>
  );
}

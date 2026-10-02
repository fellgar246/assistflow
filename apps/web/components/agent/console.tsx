"use client";

import { ApprovalCard } from "@/components/chat/approval-card";
import { Composer } from "@/components/chat/composer";
import { ErrorPanel } from "@/components/chat/states";
import { Transcript, TranscriptSkeleton } from "@/components/chat/transcript";
import { StatusBadge } from "@/components/status-badge";
import { ApiError, listLoginUsers, readSession, startSession } from "@/lib/api/client";
import type { LoginUser, StaffConversation } from "@/lib/api/schemas";
import {
  confirmAsStaff,
  listInbox,
  postStaffReply,
  readStaffConversation,
  readStaffTranscript,
  readTrace,
  rejectAsStaff,
  resolveConversation,
  takeOver,
} from "@/lib/api/staff";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import { EmptyInbox, InboxList } from "./inbox-list";
import { TracePanel } from "./trace-panel";

type AgentConsoleProps = {
  conversationId?: string;
};

type Queue = "all" | "escalated" | "waiting_approval";

export function AgentConsole({ conversationId }: AgentConsoleProps) {
  const router = useRouter();
  const queryClient = useQueryClient();
  const headingRef = useRef<HTMLHeadingElement>(null);
  const [queue, setQueue] = useState<Queue>("all");
  const [extra, setExtra] = useState<{
    key: string;
    loaded: StaffConversation[];
    cursor: string | null | undefined;
  }>({ key: "", loaded: [], cursor: undefined });
  const [tab, setTab] = useState<"summary" | "trace" | "approvals" | "ticket">("summary");
  const [confirmingResolve, setConfirmingResolve] = useState(false);
  const [busyApprovalId, setBusyApprovalId] = useState<string | null>(null);
  const [pendingAction, setPendingAction] = useState<"confirm" | "reject" | null>(null);
  const [approvalError, setApprovalError] = useState<{ id: string; message: string } | null>(null);
  const sessionQuery = useQuery({
    queryKey: ["session"],
    queryFn: readSession,
    retry: false,
  });
  const usersQuery = useQuery({
    queryKey: ["login-users"],
    queryFn: listLoginUsers,
    retry: false,
    enabled: sessionQuery.isSuccess,
  });
  const session = sessionQuery.data ?? null;
  const actors = (usersQuery.data?.users ?? []).filter((user) => user.role === "support_agent");
  const signedIn = session?.role === "support_agent";

  function selectAccount(userKey: string) {
    void startSession(userKey).then(async () => {
      await queryClient.invalidateQueries({ queryKey: ["session"] });
      await queryClient.invalidateQueries({ queryKey: ["staff-inbox"] });
      router.push("/agent/inbox");
    });
  }

  useEffect(() => {
    if (sessionQuery.isError && sessionQuery.error instanceof ApiError && sessionQuery.error.status === 401) {
      router.replace("/login");
    }
  }, [router, sessionQuery.error, sessionQuery.isError]);

  const inboxQuery = useQuery({
    queryKey: ["staff-inbox", session?.key, queue],
    queryFn: () => listInbox(queue),
    enabled: signedIn,
  });

  const conversationQuery = useQuery({
    queryKey: ["staff-conversation", conversationId, session?.key],
    queryFn: () => readStaffConversation(conversationId!),
    enabled: signedIn && conversationId !== undefined,
  });
  const transcriptQuery = useQuery({
    queryKey: ["staff-transcript", conversationId, session?.key],
    queryFn: () => readStaffTranscript(conversationId!),
    enabled: signedIn && conversationId !== undefined,
  });
  const traceQuery = useQuery({
    queryKey: ["staff-trace", conversationId, session?.key],
    queryFn: () => readTrace(conversationId!),
    enabled: signedIn && conversationId !== undefined && tab === "trace",
  });

  useEffect(() => {
    if (conversationId && conversationQuery.data) {
      headingRef.current?.focus();
    }
  }, [conversationId, conversationQuery.data]);

  const pageKey = `${session?.key ?? ""}:${queue}`;
  const extraPage = extra.key === pageKey ? extra : { key: pageKey, loaded: [], cursor: undefined };
  const items = mergeInbox(inboxQuery.data?.items ?? [], extraPage.loaded);
  const nextCursor =
    extraPage.cursor === undefined ? (inboxQuery.data?.next_cursor ?? null) : extraPage.cursor;
  const conversation = conversationQuery.data;
  const assignedToMe = Boolean(session && conversation?.assignee_name === session.label);

  const takeOverMutation = useMutation({
    mutationFn: () => takeOver(conversationId!, crypto.randomUUID()),
    onSuccess: async () => {
      await refresh(queryClient, conversationId);
    },
  });
  const resolveMutation = useMutation({
    mutationFn: () => resolveConversation(conversationId!, crypto.randomUUID()),
    onSuccess: async () => {
      setConfirmingResolve(false);
      await refresh(queryClient, conversationId);
    },
  });
  const replyMutation = useMutation({
    mutationFn: (content: string) =>
      postStaffReply(conversationId!, content, crypto.randomUUID()),
    onSuccess: async () => {
      await refresh(queryClient, conversationId);
    },
  });

  async function loadMore() {
    if (!signedIn || !nextCursor) {
      return;
    }
    const page = await listInbox(queue, nextCursor);
    setExtra({
      key: pageKey,
      loaded: mergeInbox(extraPage.loaded, page.items),
      cursor: page.next_cursor,
    });
  }

  async function decide(approvalId: string, action: "confirm" | "reject") {
    if (!signedIn || !conversationId || busyApprovalId) {
      return;
    }
    setBusyApprovalId(approvalId);
    setPendingAction(action);
    setApprovalError(null);
    try {
      if (action === "confirm") {
        await confirmAsStaff(conversationId, approvalId);
      } else {
        await rejectAsStaff(conversationId, approvalId);
      }
      await refresh(queryClient, conversationId);
    } catch (error) {
      const message = error instanceof ApiError ? error.message : "This change could not be confirmed.";
      setApprovalError({ id: approvalId, message });
    } finally {
      setBusyApprovalId(null);
      setPendingAction(null);
    }
  }

  if (sessionQuery.isLoading || (sessionQuery.isError && sessionQuery.error instanceof ApiError && sessionQuery.error.status === 401)) {
    return (
      <main className="flex h-dvh items-center justify-center px-6">
        <p className="text-sm text-muted">Loading…</p>
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

  const failed = conversationQuery.isError || transcriptQuery.isError;
  const approvals = (transcriptQuery.data?.items ?? []).flatMap((message) => message.approvals);
  const approverName = (approvedBy: string | null | undefined) =>
    approvedBy && session ? session.label.split(" ")[0] : undefined;

  return (
    <div className="flex h-dvh min-h-0 flex-col overflow-hidden">
      <a
        href="#conversation"
        className="sr-only focus:not-sr-only focus:absolute focus:z-10 focus:bg-surface focus:p-2"
      >
        Skip to conversation
      </a>
      <header className="flex items-center justify-between gap-3 border-b border-default bg-surface px-4 py-3">
        <p className="text-base font-semibold text-text">AssistFlow</p>
        <p className="rounded-md border border-dashed border-warning bg-warning-soft px-2 py-1 text-xs font-medium text-warning">
          Development staff{session ? ` · ${session.label}` : ""}
        </p>
      </header>
      <div className="flex min-h-0 min-w-0 flex-1 flex-col overflow-y-auto lg:flex-row lg:overflow-hidden">
        <nav
          aria-label="Inbox"
          className={`min-h-0 w-full border-default bg-surface lg:flex lg:w-80 lg:shrink-0 lg:flex-col lg:overflow-y-auto lg:border-r ${
            conversationId ? "hidden lg:flex" : "flex flex-1 flex-col"
          }`}
        >
          <div className="flex gap-2 overflow-x-auto px-3 py-3">
            <QueueTab
              label="All waiting"
              count={inboxQuery.data?.counts.all}
              selected={queue === "all"}
              onSelect={() => setQueue("all")}
            />
            <QueueTab
              label="Escalated"
              count={inboxQuery.data?.counts.escalated}
              selected={queue === "escalated"}
              onSelect={() => setQueue("escalated")}
            />
            <QueueTab
              label="Waiting for confirmation"
              count={inboxQuery.data?.counts.waiting_approval}
              selected={queue === "waiting_approval"}
              onSelect={() => setQueue("waiting_approval")}
            />
          </div>
          {inboxQuery.isLoading ? (
            <p className="px-3 text-sm text-muted">Loading the queue…</p>
          ) : inboxQuery.isError ? (
            <div className="p-3">
              <ErrorPanel onRetry={() => void inboxQuery.refetch()} />
            </div>
          ) : (
            <InboxList items={items} selectedId={conversationId} />
          )}
          {nextCursor ? (
            <button
              type="button"
              onClick={() => void loadMore()}
              className="m-3 min-h-8 rounded-md border border-strong bg-surface px-3 text-sm font-medium text-text focus-visible:ring-2 focus-visible:ring-accent focus-visible:ring-offset-2"
            >
              Load more
            </button>
          ) : null}
          {actors.length > 0 ? (
            <StaffSwitch actors={actors} currentKey={session?.key ?? null} onChange={selectAccount} />
          ) : null}
        </nav>
        <main
          id="conversation"
          className={`min-h-0 min-w-0 flex-1 flex-col ${conversationId ? "flex" : "hidden lg:flex"}`}
        >
          {conversationId ? (
            <>
              <header className="flex items-center gap-2 border-b border-default bg-surface px-3 py-3">
                <Link
                  href="/agent/inbox"
                  aria-label="Back to inbox"
                  className="inline-flex size-11 items-center justify-center rounded-md lg:hidden focus-visible:ring-2 focus-visible:ring-accent"
                >
                  <ArrowLeft className="size-5" aria-hidden />
                </Link>
                <h1
                  ref={headingRef}
                  tabIndex={-1}
                  className="min-w-0 flex-1 truncate text-xl font-semibold text-text outline-none"
                >
                  {conversation?.customer_display_name ?? "Conversation"}
                </h1>
                {conversation ? <StatusBadge status={conversation.status} /> : null}
              </header>
              <div className="min-h-0 flex-1 overflow-y-auto">
                {transcriptQuery.isLoading || conversationQuery.isLoading ? (
                  <TranscriptSkeleton />
                ) : failed ? (
                  <div className="p-4">
                    <ErrorPanel
                      onRetry={() => {
                        void conversationQuery.refetch();
                        void transcriptQuery.refetch();
                      }}
                    />
                  </div>
                ) : (
                  <Transcript
                    messages={transcriptQuery.data?.items ?? []}
                    approvalAudience="staff"
                    customerName={conversation?.customer_display_name}
                    approverNameFor={approverName}
                    busyApprovalId={busyApprovalId}
                    pendingAction={pendingAction}
                    approvalError={approvalError}
                    onConfirmApproval={(id) => void decide(id, "confirm")}
                    onCancelApproval={(id) => void decide(id, "reject")}
                    onDismissApprovalError={(id) =>
                      setApprovalError((current) => (current?.id === id ? null : current))
                    }
                  />
                )}
              </div>
              <div className="border-t border-default bg-surface px-3 py-3">
                {conversation && conversation.status !== "resolved" ? (
                  <div className="mx-auto mb-3 flex max-w-3xl flex-wrap gap-2">
                    {!assignedToMe ? (
                      <button
                        type="button"
                        disabled={takeOverMutation.isPending || !signedIn}
                        onClick={() => takeOverMutation.mutate()}
                        className="inline-flex min-h-8 items-center rounded-md bg-accent px-3 text-sm font-medium text-white hover:bg-accent-hover focus-visible:ring-2 focus-visible:ring-accent focus-visible:ring-offset-2 disabled:opacity-50"
                      >
                        Take over
                      </button>
                    ) : confirmingResolve ? (
                      <div className="flex flex-wrap items-center gap-2">
                        <p className="text-sm text-text">Resolve conversation and ticket?</p>
                        <button
                          type="button"
                          onClick={() => resolveMutation.mutate()}
                          className="inline-flex min-h-8 items-center rounded-md bg-accent px-3 text-sm font-medium text-white focus-visible:ring-2 focus-visible:ring-accent focus-visible:ring-offset-2"
                        >
                          Resolve conversation
                        </button>
                        <button
                          type="button"
                          onClick={() => setConfirmingResolve(false)}
                          className="inline-flex min-h-8 items-center rounded-md border border-strong bg-surface px-3 text-sm font-medium text-text focus-visible:ring-2 focus-visible:ring-accent focus-visible:ring-offset-2"
                        >
                          Keep open
                        </button>
                      </div>
                    ) : (
                      <button
                        type="button"
                        onClick={() => setConfirmingResolve(true)}
                        className="inline-flex min-h-8 items-center rounded-md bg-accent px-3 text-sm font-medium text-white hover:bg-accent-hover focus-visible:ring-2 focus-visible:ring-accent focus-visible:ring-offset-2"
                      >
                        Resolve conversation
                      </button>
                    )}
                  </div>
                ) : null}
                <Composer
                  placeholder="Write a reply the customer will see"
                  footer={
                    session
                      ? `Replying as ${session.label} · visible to the customer`
                      : null
                  }
                  sending={replyMutation.isPending}
                  disabled={!assignedToMe || conversation?.status === "resolved" || !signedIn}
                  onSend={(content) => replyMutation.mutate(content)}
                />
              </div>
            </>
          ) : (
            <div className="hidden flex-1 items-center justify-center p-6 lg:flex">
              <EmptyInbox />
            </div>
          )}
        </main>
        {conversationId ? (
          <aside
            aria-label="Details"
            className="min-w-0 border-default bg-surface lg:w-[360px] lg:shrink-0 lg:overflow-y-auto lg:border-l"
          >
            <div className="flex gap-2 overflow-x-auto border-b border-default px-3 py-2" role="tablist">
              {(["summary", "trace", "approvals", "ticket"] as const).map((name) => (
                <button
                  key={name}
                  type="button"
                  role="tab"
                  aria-selected={tab === name}
                  onClick={() => setTab(name)}
                  className={`min-h-8 rounded-md px-2 text-sm font-medium capitalize focus-visible:ring-2 focus-visible:ring-accent ${
                    tab === name ? "bg-accent-soft text-accent" : "text-muted"
                  }`}
                >
                  {name}
                </button>
              ))}
            </div>
            <div className="p-3">
              {tab === "summary" && conversation ? (
                <dl className="space-y-2 text-sm">
                  <div>
                    <dt className="text-muted">Customer</dt>
                    <dd className="font-medium text-text">{conversation.customer_display_name}</dd>
                  </div>
                  <div>
                    <dt className="text-muted">Assignee</dt>
                    <dd className="text-text">{conversation.assignee_name ?? "Unassigned"}</dd>
                  </div>
                </dl>
              ) : null}
              {tab === "trace" ? (
                traceQuery.isLoading ? (
                  <p className="text-sm text-muted">Loading the trace…</p>
                ) : traceQuery.isError ? (
                  <ErrorPanel onRetry={() => void traceQuery.refetch()} />
                ) : (
                  <TracePanel summary={traceQuery.data ?? { items: [] }} />
                )
              ) : null}
              {tab === "approvals" ? (
                approvals.length === 0 ? (
                  <p className="text-sm text-muted">No confirmation is waiting.</p>
                ) : (
                  approvals.map((approval) => (
                    <ApprovalCard
                      key={approval.id}
                      approval={approval}
                      audience="staff"
                      customerName={conversation?.customer_display_name}
                      approverName={approverName(approval.approved_by)}
                      submitting={busyApprovalId === approval.id}
                      pendingAction={busyApprovalId === approval.id ? pendingAction : null}
                      error={approvalError?.id === approval.id ? approvalError.message : null}
                      onConfirm={(id) => void decide(id, "confirm")}
                      onCancel={(id) => void decide(id, "reject")}
                    />
                  ))
                )
              ) : null}
              {tab === "ticket" && conversation?.ticket_id ? (
                <Link
                  href={`/agent/tickets/${conversation.ticket_id}`}
                  className="text-sm font-medium text-accent underline-offset-2 hover:underline focus-visible:ring-2 focus-visible:ring-accent"
                >
                  Open ticket
                </Link>
              ) : null}
              {tab === "ticket" && conversation && !conversation.ticket_id ? (
                <p className="text-sm text-muted">This conversation has no ticket yet.</p>
              ) : null}
            </div>
          </aside>
        ) : null}
      </div>
    </div>
  );
}

function QueueTab({
  label,
  count,
  selected,
  onSelect,
}: {
  label: string;
  count?: number;
  selected: boolean;
  onSelect: () => void;
}) {
  return (
    <button
      type="button"
      aria-pressed={selected}
      onClick={onSelect}
      className={`inline-flex min-h-8 shrink-0 items-center gap-1 rounded-full px-3 text-sm font-medium focus-visible:ring-2 focus-visible:ring-accent ${
        selected ? "bg-accent-soft text-accent" : "bg-surface-subtle text-text"
      }`}
    >
      {label}
      {count !== undefined ? <span className="tabular-nums">{count}</span> : null}
    </button>
  );
}

function StaffSwitch({
  actors,
  currentKey,
  onChange,
}: {
  actors: LoginUser[];
  currentKey: string | null;
  onChange: (userKey: string) => void;
}) {
  return (
    <div className="m-3 rounded-lg border border-dashed border-warning bg-warning-soft p-3">
      <p className="text-sm font-medium text-warning">Development only</p>
      <label htmlFor="dev-staff" className="mt-2 block text-xs text-muted">
        Local staff
      </label>
      <select
        id="dev-staff"
        value={currentKey ?? ""}
        onChange={(event) => onChange(event.target.value)}
        className="mt-1 min-h-8 w-full rounded-md border border-strong bg-surface px-2 text-sm text-text focus-visible:ring-2 focus-visible:ring-accent"
      >
        {actors.map((actor) => (
          <option key={actor.key} value={actor.key}>
            {actor.label} · {actor.organization}
          </option>
        ))}
      </select>
    </div>
  );
}

function mergeInbox(first: StaffConversation[], second: StaffConversation[]): StaffConversation[] {
  const seen = new Set<string>();
  const items: StaffConversation[] = [];
  for (const item of [...first, ...second]) {
    if (seen.has(item.id)) {
      continue;
    }
    seen.add(item.id);
    items.push(item);
  }
  return items;
}

async function refresh(
  queryClient: ReturnType<typeof useQueryClient>,
  conversationId: string | undefined,
) {
  await queryClient.invalidateQueries({ queryKey: ["staff-inbox"] });
  await queryClient.invalidateQueries({ queryKey: ["staff-conversation", conversationId] });
  await queryClient.invalidateQueries({ queryKey: ["staff-transcript", conversationId] });
  await queryClient.invalidateQueries({ queryKey: ["staff-trace", conversationId] });
}

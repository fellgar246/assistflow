"use client";

import {
  ApiError,
  confirmApproval,
  createConversation,
  listConversations,
  listLoginUsers,
  postMessage,
  readConversation,
  readSession,
  readTranscript,
  rejectApproval,
  startSession,
} from "@/lib/api/client";
import { conversationTitle } from "@/lib/chat/format";
import { StatusBadge } from "@/components/status-badge";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import { Composer } from "./composer";
import { ConversationList } from "./conversation-list";
import { EmptyThread, ErrorPanel, ListSkeleton } from "./states";
import { Transcript, TranscriptSkeleton } from "./transcript";

type WorkspaceProps = {
  conversationId?: string;
};

export function ChatWorkspace({ conversationId }: WorkspaceProps) {
  const router = useRouter();
  const queryClient = useQueryClient();
  const headingRef = useRef<HTMLHeadingElement>(null);
  const sendingRef = useRef(false);
  const decidingRef = useRef(false);
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
  const actors = (usersQuery.data?.users ?? []).filter((user) => user.role === "customer");
  const showActorSwitch = actors.length > 1;
  const signedIn = session?.role === "customer";

  useEffect(() => {
    if (sessionQuery.isError && sessionQuery.error instanceof ApiError && sessionQuery.error.status === 401) {
      router.replace("/login");
    }
  }, [router, sessionQuery.error, sessionQuery.isError]);

  useEffect(() => {
    if (session?.role === "support_agent") {
      router.replace("/agent/inbox");
    }
  }, [router, session?.role]);

  function selectActor(userKey: string) {
    void startSession(userKey).then(async () => {
      await queryClient.invalidateQueries({ queryKey: ["session"] });
      await queryClient.invalidateQueries({ queryKey: ["conversations"] });
      await queryClient.invalidateQueries({ queryKey: ["transcript"] });
      router.push("/chat");
    });
  }

  const listQuery = useQuery({
    queryKey: ["conversations", session?.key],
    queryFn: () => listConversations(),
    enabled: signedIn,
  });

  const conversationQuery = useQuery({
    queryKey: ["conversation", conversationId, session?.key],
    queryFn: () => readConversation(conversationId!),
    enabled: signedIn && conversationId !== undefined,
  });

  const transcriptQuery = useQuery({
    queryKey: ["transcript", conversationId, session?.key],
    queryFn: () => readTranscript(conversationId!),
    enabled: signedIn && conversationId !== undefined,
  });

  useEffect(() => {
    if (conversationId && conversationQuery.data) {
      headingRef.current?.focus();
    }
  }, [conversationId, conversationQuery.data]);

  const createMutation = useMutation({
    mutationFn: async (content: string) => {
      if (!signedIn) {
        throw new Error("Sign in is required.");
      }
      const conversation = await createConversation(crypto.randomUUID());
      const posted = await postMessage(conversation.id, content, crypto.randomUUID());
      return posted.conversationId;
    },
    onSuccess: async (id) => {
      await queryClient.invalidateQueries({ queryKey: ["conversations"] });
      router.push(`/chat/${id}`);
    },
  });

  const sendMutation = useMutation({
    mutationFn: async (content: string) => {
      if (!signedIn || !conversationId) {
        throw new Error("No conversation is open.");
      }
      const posted = await postMessage(conversationId, content, crypto.randomUUID());
      return posted.conversationId;
    },
    onSuccess: async (id) => {
      await queryClient.invalidateQueries({ queryKey: ["transcript", conversationId] });
      await queryClient.invalidateQueries({ queryKey: ["conversation", conversationId] });
      await queryClient.invalidateQueries({ queryKey: ["conversations"] });
      if (id !== conversationId) {
        router.push(`/chat/${id}`);
      }
    },
  });

  async function decide(approvalId: string, action: "confirm" | "reject") {
    if (!signedIn || !conversationId || decidingRef.current) {
      return;
    }
    decidingRef.current = true;
    setBusyApprovalId(approvalId);
    setPendingAction(action);
    setApprovalError(null);
    try {
      if (action === "confirm") {
        await confirmApproval(conversationId, approvalId);
      } else {
        await rejectApproval(conversationId, approvalId);
      }
      await queryClient.invalidateQueries({ queryKey: ["transcript", conversationId] });
      await queryClient.invalidateQueries({ queryKey: ["conversation", conversationId] });
      await queryClient.invalidateQueries({ queryKey: ["conversations"] });
    } catch (error) {
      const message =
        error instanceof ApiError ? error.message : "This change could not be confirmed.";
      setApprovalError({ id: approvalId, message });
    } finally {
      decidingRef.current = false;
      setBusyApprovalId(null);
      setPendingAction(null);
    }
  }

  function send(content: string) {
    if (sendingRef.current || sendMutation.isPending || createMutation.isPending) {
      return;
    }
    sendingRef.current = true;
    const pending = conversationId ? sendMutation.mutateAsync(content) : createMutation.mutateAsync(content);
    void pending.finally(() => {
      sendingRef.current = false;
    });
  }

  const threadFailed = conversationQuery.isError || transcriptQuery.isError || sendMutation.isError;

  const showList = !conversationId;
  const preview =
    conversationQuery.data?.preview ??
    transcriptQuery.data?.items.find((item) => item.role === "customer")?.content;
  const title = preview?.trim()
    ? conversationTitle(preview)
    : conversationId
      ? "Conversation"
      : "New conversation";

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

  return (
    <div className="flex h-dvh min-h-0 flex-col md:flex-row">
      <a
        href="#message"
        className="sr-only focus:not-sr-only focus:absolute focus:z-10 focus:bg-surface focus:p-2"
      >
        Skip to message box
      </a>
      <nav
        aria-label="Conversations"
        className={`min-h-0 w-full border-default bg-surface md:flex md:w-[280px] md:shrink-0 md:border-r ${
          showList ? "flex flex-1 flex-col" : "hidden"
        }`}
      >
        {listQuery.isLoading || sessionQuery.isLoading ? (
          <ListSkeleton />
        ) : listQuery.isError ? (
          <div className="p-3">
            <ErrorPanel onRetry={() => void listQuery.refetch()} />
          </div>
        ) : (
          <ConversationList
            conversations={listQuery.data?.items ?? []}
            selectedId={conversationId}
            actors={actors}
            actorId={session?.key ?? null}
            onActorChange={selectActor}
            showActorSwitch={showActorSwitch}
          />
        )}
      </nav>
      <main className={`flex min-h-0 min-w-0 flex-1 flex-col ${showList ? "hidden md:flex" : "flex"}`}>
        {conversationId ? (
          <header className="flex items-center gap-2 border-b border-default bg-surface px-3 py-3">
            <Link
              href="/chat"
              aria-label="Back to conversations"
              className="inline-flex size-11 items-center justify-center rounded-md md:hidden focus-visible:ring-2 focus-visible:ring-accent"
            >
              <ArrowLeft className="size-5" aria-hidden />
            </Link>
            <h1 ref={headingRef} tabIndex={-1} className="min-w-0 flex-1 truncate text-xl font-semibold text-text outline-none">
              {title}
            </h1>
            {conversationQuery.data ? <StatusBadge status={conversationQuery.data.status} /> : null}
          </header>
        ) : (
          <header className="hidden border-b border-default px-4 py-3 md:block">
            <h1 className="text-xl font-semibold text-text">New conversation</h1>
          </header>
        )}
        <div className="min-h-0 flex-1 overflow-y-auto">
          {!conversationId ? (
            <EmptyThread onSuggest={send} />
          ) : transcriptQuery.isLoading || conversationQuery.isLoading ? (
            <TranscriptSkeleton />
          ) : threadFailed ? (
            <div className="p-4">
              <ErrorPanel
                onRetry={() => {
                  void conversationQuery.refetch();
                  void transcriptQuery.refetch();
                }}
              />
            </div>
          ) : (transcriptQuery.data?.items.length ?? 0) === 0 ? (
            <EmptyThread onSuggest={send} />
          ) : (
            <Transcript
              messages={transcriptQuery.data?.items ?? []}
              busyApprovalId={busyApprovalId}
              pendingAction={pendingAction}
              approvalError={approvalError}
              onConfirmApproval={(id) => void decide(id, "confirm")}
              onCancelApproval={(id) => void decide(id, "reject")}
              onDismissApprovalError={(id) =>
                setApprovalError((current) => (current?.id === id ? null : current))
              }
              onTalkToPerson={() => send("Please connect me with a person.")}
            />
          )}
        </div>
        <Composer
          sending={sendMutation.isPending || createMutation.isPending}
          disabled={!signedIn || (conversationId !== undefined && threadFailed)}
          notice={
            conversationQuery.data?.status === "resolved"
              ? "This conversation is resolved. Sending a message starts a new one."
              : conversationQuery.data?.status === "waiting_approval"
                ? "Confirm or cancel the pending change above, or keep chatting."
                : undefined
          }
          onSend={send}
        />
      </main>
    </div>
  );
}


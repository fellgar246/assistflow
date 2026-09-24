import type { Conversation, LocalActor } from "@/lib/api/schemas";
import { conversationTitle, relativeTime } from "@/lib/chat/format";
import { StatusBadge } from "@/components/status-badge";
import Link from "next/link";
import { EmptyList } from "./states";

type ConversationListProps = {
  conversations: Conversation[];
  selectedId?: string;
  actors: LocalActor[];
  actorId: string | null;
  onActorChange: (customerId: string) => void;
  showActorSwitch: boolean;
};

export function ConversationList({
  conversations,
  selectedId,
  actors,
  actorId,
  onActorChange,
  showActorSwitch,
}: ConversationListProps) {
  const ordered = [...conversations].sort(
    (left, right) => new Date(right.updated_at).getTime() - new Date(left.updated_at).getTime(),
  );
  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="flex items-center justify-between gap-3 px-3 py-4">
        <p className="text-base font-semibold text-text">AssistFlow</p>
        <Link
          href="/chat"
          className="inline-flex min-h-11 items-center rounded-md bg-accent px-3 text-sm font-medium text-white hover:bg-accent-hover focus-visible:ring-2 focus-visible:ring-accent focus-visible:ring-offset-2"
        >
          New conversation
        </Link>
      </div>
      {ordered.length === 0 ? (
        <EmptyList />
      ) : (
        <ul className="min-h-0 flex-1 overflow-y-auto">
          {ordered.map((conversation) => {
            const selected = conversation.id === selectedId;
            const title = conversationTitle(conversation.preview);
            return (
              <li key={conversation.id}>
                <Link
                  href={`/chat/${conversation.id}`}
                  aria-current={selected ? "page" : undefined}
                  className={`block min-h-11 border-l-2 px-3 py-3 focus-visible:ring-2 focus-visible:ring-accent ${
                    selected ? "border-accent bg-accent-soft" : "border-transparent hover:bg-surface-subtle"
                  }`}
                >
                  <p className="truncate text-sm font-medium text-text">{title}</p>
                  <p className="mt-1 flex flex-wrap items-center gap-2">
                    <StatusBadge status={conversation.status} />
                    <time dateTime={conversation.updated_at} className="text-xs text-muted">
                      {relativeTime(conversation.updated_at)}
                    </time>
                  </p>
                </Link>
              </li>
            );
          })}
        </ul>
      )}
      {showActorSwitch ? (
        <div className="m-3 rounded-lg border border-dashed border-warning bg-warning-soft p-3">
          <p className="text-sm font-medium text-warning">Development only</p>
          <label htmlFor="dev-actor" className="mt-2 block text-xs text-muted">
            Local customer
          </label>
          <select
            id="dev-actor"
            value={actorId ?? ""}
            onChange={(event) => onActorChange(event.target.value)}
            className="mt-1 min-h-11 w-full rounded-md border border-strong bg-surface px-2 text-sm text-text focus-visible:ring-2 focus-visible:ring-accent"
          >
            {actors.map((actor) => (
              <option key={actor.customer_id} value={actor.customer_id}>
                {actor.label}, {actor.organization}
              </option>
            ))}
          </select>
        </div>
      ) : null}
    </div>
  );
}

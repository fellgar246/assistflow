"use client";

import type { StaffConversation } from "@/lib/api/schemas";
import { relativeTime } from "@/lib/chat/format";
import { StatusBadge } from "@/components/status-badge";
import Link from "next/link";
import type { KeyboardEvent } from "react";

type InboxListProps = {
  items: StaffConversation[];
  selectedId?: string;
};

export function EmptyInbox() {
  return (
    <p className="px-3 py-6 text-sm text-success">
      Nothing is waiting. Escalated conversations and pending approvals will show up here.
    </p>
  );
}

export function InboxList({ items, selectedId }: InboxListProps) {
  function onKeyDown(event: KeyboardEvent<HTMLUListElement>) {
    if (event.key !== "ArrowDown" && event.key !== "ArrowUp" && event.key !== "j" && event.key !== "k") {
      return;
    }
    const links = Array.from(event.currentTarget.querySelectorAll<HTMLAnchorElement>("a"));
    const current = links.findIndex((link) => link === document.activeElement);
    const next =
      event.key === "ArrowDown" || event.key === "j"
        ? Math.min(links.length - 1, current + 1)
        : Math.max(0, current - 1);
    links[next]?.focus();
    event.preventDefault();
  }

  if (items.length === 0) {
    return <EmptyInbox />;
  }

  return (
    <ul className="min-h-0 flex-1 overflow-y-auto" onKeyDown={onKeyDown}>
      {items.map((item) => {
        const selected = item.id === selectedId;
        return (
          <li key={item.id}>
            <Link
              href={`/agent/conversations/${item.id}`}
              aria-current={selected ? "page" : undefined}
              className={`block min-h-11 border-l-2 px-3 py-3 focus-visible:ring-2 focus-visible:ring-accent ${
                selected ? "border-accent bg-accent-soft" : "border-transparent hover:bg-surface-subtle"
              }`}
            >
              <span className="flex items-start justify-between gap-2">
                <span className="min-w-0 truncate text-sm font-semibold text-text">
                  {item.customer_display_name}
                </span>
                <time
                  dateTime={item.updated_at}
                  className="shrink-0 text-xs text-muted tabular-nums"
                >
                  {relativeTime(item.updated_at)}
                </time>
              </span>
              <span className="mt-1 flex flex-wrap items-center gap-2">
                <StatusBadge status={item.status} />
              </span>
              {item.preview ? (
                <span className="mt-1 block truncate text-sm text-muted">{item.preview}</span>
              ) : null}
              <span className="mt-1 flex flex-wrap gap-2 text-xs">
                {item.pending_approval_count > 0 ? (
                  <span className="text-warning">
                    {item.pending_approval_count} pending approval
                  </span>
                ) : null}
                {item.ticket_priority === "high" ? (
                  <span className="font-medium text-danger">High priority</span>
                ) : null}
                <span className={item.assignee_name ? "text-muted" : "text-warning"}>
                  {item.assignee_name ? `Assigned to ${item.assignee_name}` : "Unassigned"}
                </span>
              </span>
            </Link>
          </li>
        );
      })}
    </ul>
  );
}

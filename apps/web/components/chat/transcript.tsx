"use client";

import type { Message } from "@/lib/api/schemas";
import { absoluteTime, dayLabel, relativeTime } from "@/lib/chat/format";
import { Citations } from "./citations";
import { ToolActivityRow } from "./tool-activity";

const GROUP_WINDOW_MS = 2 * 60_000;

type TranscriptProps = {
  messages: Message[];
};

function sameGroup(previous: Message | undefined, current: Message): boolean {
  if (!previous || previous.role !== current.role) {
    return false;
  }
  return new Date(current.created_at).getTime() - new Date(previous.created_at).getTime() <= GROUP_WINDOW_MS;
}

export function Transcript({ messages }: TranscriptProps) {
  return (
    <div
      role="log"
      aria-live="polite"
      aria-relevant="additions"
      aria-label="Conversation"
      className="mx-auto flex w-full max-w-3xl flex-col gap-4 px-4 py-6"
    >
      {messages.map((message, index) => {
        const previous = messages[index - 1];
        const showDay =
          !previous ||
          dayLabel(new Date(previous.created_at)) !== dayLabel(new Date(message.created_at));
        const grouped = sameGroup(previous, message);
        return (
          <div key={message.id} className={grouped ? "mt-[-0.75rem]" : undefined}>
            {showDay ? (
              <p className="mb-4 text-center text-xs text-muted">{dayLabel(new Date(message.created_at))}</p>
            ) : null}
            <MessageView message={message} showLabel={!grouped} />
          </div>
        );
      })}
    </div>
  );
}

function MessageView({ message, showLabel }: { message: Message; showLabel: boolean }) {
  if (message.role === "system") {
    return (
      <p className="text-center text-xs text-muted">
        <span className="sr-only">System said </span>
        {message.content}
      </p>
    );
  }
  if (message.role === "customer") {
    return (
      <div className="flex justify-end">
        <div className="max-w-prose">
          {showLabel ? <p className="sr-only">You said</p> : null}
          <p className="rounded-2xl bg-accent px-4 py-2 text-[15px] leading-6 break-words text-white">
            {message.content}
          </p>
          <time
            dateTime={message.created_at}
            title={absoluteTime(message.created_at)}
            className="mt-1 block text-right text-xs text-muted"
          >
            {relativeTime(message.created_at)}
          </time>
        </div>
      </div>
    );
  }
  return (
    <article className="max-w-prose">
      {showLabel ? (
        <p className="mb-1 text-sm font-medium text-text">
          <span className="sr-only">AssistFlow said </span>
          AssistFlow
          <span className="ml-2 text-xs font-medium text-muted">Automated</span>
        </p>
      ) : null}
      <ToolActivityRow items={message.tool_activity} />
      <p className="text-[15px] leading-6 break-words text-text">{message.content}</p>
      <Citations citations={message.citations} />
      <time
        dateTime={message.created_at}
        title={absoluteTime(message.created_at)}
        className="mt-1 block text-xs text-muted"
      >
        {relativeTime(message.created_at)}
      </time>
    </article>
  );
}

export function TranscriptSkeleton() {
  return (
    <div className="mx-auto flex w-full max-w-3xl flex-col gap-4 px-4 py-6" aria-hidden>
      <div className="ml-auto h-16 w-2/3 animate-pulse rounded-2xl bg-surface-subtle motion-safe:animate-pulse" />
      <div className="h-20 w-3/4 animate-pulse rounded-lg bg-surface-subtle" />
      <div className="ml-auto h-16 w-1/2 animate-pulse rounded-2xl bg-surface-subtle" />
    </div>
  );
}

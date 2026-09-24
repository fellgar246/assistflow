"use client";

import { Send } from "lucide-react";
import { useId, useRef, useState, type FormEvent, type KeyboardEvent } from "react";

const LIMIT = 8000;
const SHOW_COUNT_AT = LIMIT * 0.9;

type ComposerProps = {
  disabled?: boolean;
  sending?: boolean;
  onSend: (content: string) => void;
};

export function Composer({ disabled = false, sending = false, onSend }: ComposerProps) {
  const labelId = useId();
  const fieldRef = useRef<HTMLTextAreaElement>(null);
  const [draft, setDraft] = useState("");
  const trimmed = draft.trim();
  const blocked = disabled || sending || trimmed.length === 0;

  function submit() {
    if (blocked) {
      return;
    }
    const content = trimmed;
    setDraft("");
    onSend(content);
    fieldRef.current?.focus();
  }

  function onKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key !== "Enter" || event.shiftKey || event.nativeEvent.isComposing) {
      return;
    }
    event.preventDefault();
    submit();
  }

  function onSubmit(event: FormEvent) {
    event.preventDefault();
    submit();
  }

  return (
    <form onSubmit={onSubmit} className="border-t border-default bg-surface px-4 py-3 pb-[max(0.75rem,env(safe-area-inset-bottom))]">
      <label id={labelId} htmlFor="message" className="sr-only">
        Message
      </label>
      <div className="mx-auto flex max-w-3xl items-end gap-2">
        <textarea
          ref={fieldRef}
          id="message"
          name="message"
          rows={1}
          value={draft}
          aria-labelledby={labelId}
          placeholder="Ask about an order, delivery, return, or refund"
          disabled={disabled || sending}
          onChange={(event) => setDraft(event.target.value.slice(0, LIMIT))}
          onKeyDown={onKeyDown}
          className="max-h-36 min-h-11 flex-1 resize-none rounded-md border border-strong bg-surface px-3 py-2 text-[15px] leading-6 text-text outline-none focus-visible:ring-2 focus-visible:ring-accent focus-visible:ring-offset-2 disabled:opacity-50"
        />
        <button
          type="submit"
          aria-label="Send message"
          disabled={blocked}
          className="inline-flex size-11 shrink-0 items-center justify-center rounded-md bg-accent text-white hover:bg-accent-hover focus-visible:ring-2 focus-visible:ring-accent focus-visible:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-50"
        >
          <Send className="size-5" aria-hidden />
        </button>
      </div>
      {draft.length >= SHOW_COUNT_AT ? (
        <p className="mx-auto mt-1 max-w-3xl text-xs text-muted">
          {draft.length} / {LIMIT}
        </p>
      ) : null}
      <p className="mx-auto mt-2 max-w-3xl text-xs text-muted">
        AssistFlow is automated and can make mistakes. Changes always need your confirmation.
      </p>
    </form>
  );
}

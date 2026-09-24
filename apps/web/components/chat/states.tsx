const SUGGESTIONS = [
  "Where is my order?",
  "Can I change my delivery address?",
  "What's your return policy?",
  "Talk to a person",
];

type EmptyThreadProps = {
  onSuggest: (prompt: string) => void;
};

export function EmptyThread({ onSuggest }: EmptyThreadProps) {
  return (
    <div className="mx-auto flex max-w-prose flex-col gap-4 px-4 py-10">
      <h2 className="text-xl font-semibold text-text">Ask a support question</h2>
      <p className="text-[15px] leading-6 text-muted">
        Hi, I&apos;m the AssistFlow assistant. I can check orders and deliveries, explain our
        policies, and help with changes — which you&apos;ll always confirm first. If I can&apos;t
        help, I&apos;ll bring in a person.
      </p>
      <ul className="flex flex-wrap gap-2">
        {SUGGESTIONS.map((prompt) => (
          <li key={prompt}>
            <button
              type="button"
              onClick={() => onSuggest(prompt)}
              className="min-h-11 rounded-full border border-strong bg-surface px-3 text-sm font-medium text-text hover:bg-surface-subtle focus-visible:ring-2 focus-visible:ring-accent focus-visible:ring-offset-2"
            >
              {prompt}
            </button>
          </li>
        ))}
      </ul>
    </div>
  );
}

export function EmptyList() {
  return (
    <p className="px-3 py-6 text-sm text-muted">
      No conversations yet. Start one to ask about an order.
    </p>
  );
}

type ErrorPanelProps = {
  onRetry: () => void;
};

export function ErrorPanel({ onRetry }: ErrorPanelProps) {
  return (
    <div role="alert" className="mx-auto max-w-prose rounded-lg border border-danger bg-danger-soft p-4">
      <p className="text-[15px] leading-6 text-danger">
        We couldn&apos;t load this conversation. Check your connection and try again.
      </p>
      <button
        type="button"
        onClick={onRetry}
        className="mt-3 min-h-11 rounded-md border border-strong bg-surface px-3 text-sm font-medium text-text focus-visible:ring-2 focus-visible:ring-accent focus-visible:ring-offset-2"
      >
        Try again
      </button>
    </div>
  );
}

export function ListSkeleton() {
  return (
    <ul className="space-y-2 px-3" aria-hidden>
      {Array.from({ length: 5 }, (_, index) => (
        <li key={index} className="h-14 animate-pulse rounded-lg bg-surface-subtle" />
      ))}
    </ul>
  );
}

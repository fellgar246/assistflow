import type { Citation } from "@/lib/api/schemas";

type CitationsProps = {
  citations: Citation[];
};

export function Citations({ citations }: CitationsProps) {
  if (citations.length === 0) {
    return null;
  }
  return (
    <section aria-label="Sources" className="mt-3">
      <h3 className="text-sm font-medium text-text">Sources</h3>
      <ul className="mt-2 flex gap-2 overflow-x-auto pb-1 md:flex-wrap">
        {citations.slice(0, 4).map((citation, index) => (
          <li key={`${citation.title}-${index}`} className="min-w-0 shrink-0 md:shrink">
            <article className="w-56 rounded-lg border border-default bg-surface p-3 md:w-auto">
              <p className="text-sm font-medium text-text">
                <span className="mr-1 text-muted">{index + 1}</span>
                {citation.title}
              </p>
              {citation.version ? (
                <p className="mt-1 text-xs text-muted">Version {citation.version}</p>
              ) : null}
            </article>
          </li>
        ))}
      </ul>
    </section>
  );
}

import type { TraceSummary } from "@/lib/api/schemas";
import { toolLabel } from "@/lib/chat/tools";

const STATUS_LABEL: Record<string, string> = {
  proposed: "Proposed",
  running: "Running",
  succeeded: "Succeeded",
  pending_approval: "Pending approval",
  blocked: "Blocked",
  failed: "Failed",
};

type TracePanelProps = {
  summary: TraceSummary;
};

export function TracePanel({ summary }: TracePanelProps) {
  if (summary.items.length === 0) {
    return <p className="text-sm text-muted">No trace has been stored for this conversation.</p>;
  }
  return (
    <div className="flex flex-col gap-4">
      {summary.items.map((turn) => (
        <section key={turn.id} aria-label="Trace" className="flex flex-col gap-2">
          {turn.steps.map((step) => {
            const failed = step.status === "failed" || step.status === "blocked";
            return (
              <article key={`${turn.id}-${step.step}`} className="rounded-lg border border-default bg-surface p-3">
                <div className="flex flex-wrap items-baseline justify-between gap-2">
                  <p className="text-sm font-medium text-text">Step {step.step}</p>
                  <p className="text-[13px] text-muted tabular-nums">{step.latency_ms} ms</p>
                </div>
                <p className="mt-1 text-sm text-text">{step.kind}</p>
                {step.tool_name ? (
                  <p className="mt-1 text-sm text-text">
                    {toolLabel(step.tool_name)}
                    <span className="mt-1 block font-mono text-[13px] text-muted">{step.tool_name}</span>
                  </p>
                ) : null}
                {step.status ? (
                  <p className="mt-1 text-sm text-text">{STATUS_LABEL[step.status] ?? step.status}</p>
                ) : null}
                {failed && step.error_code ? (
                  <p className="mt-2 font-mono text-[13px] text-danger">{step.error_code}</p>
                ) : null}
                {failed || step.detail ? (
                  <p className="mt-1 text-sm break-words text-muted">{step.detail}</p>
                ) : null}
              </article>
            );
          })}
          <p
            className={`text-[13px] tabular-nums ${turn.stopped_by_limit ? "text-warning" : "text-muted"}`}
          >
            {turn.step_count} / {turn.step_limit} steps · {turn.tool_call_count} / {turn.tool_call_limit}{" "}
            tool calls · {turn.total_latency_ms} ms
          </p>
        </section>
      ))}
    </div>
  );
}

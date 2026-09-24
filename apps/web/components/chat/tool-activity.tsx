"use client";

import { toolLabel, toolStatusLabel, visibleToolActivity } from "@/lib/chat/tools";
import type { ToolActivity } from "@/lib/api/schemas";
import { AlertTriangle, Check, ChevronRight, Clock, LoaderCircle, Shield } from "lucide-react";
import { useState } from "react";

const ICONS = {
  running: LoaderCircle,
  succeeded: Check,
  pending_approval: Clock,
  blocked: Shield,
  failed: AlertTriangle,
} as const;

type ToolActivityRowProps = {
  items: ToolActivity[];
};

export function ToolActivityRow({ items }: ToolActivityRowProps) {
  const visible = visibleToolActivity(items);
  const hasProblem = visible.some((item) => item.status === "blocked" || item.status === "failed");
  const [open, setOpen] = useState(hasProblem);
  if (visible.length === 0) {
    return null;
  }
  const summary =
    visible.length === 1 ? toolLabel(visible[0].tool_name) : `Checked ${visible.length} things`;
  return (
    <div className="mb-2">
      <button
        type="button"
        className="inline-flex min-h-8 items-center gap-1 rounded-md text-sm text-muted focus-visible:ring-2 focus-visible:ring-accent focus-visible:ring-offset-2"
        aria-expanded={open}
        onClick={() => setOpen((current) => !current)}
      >
        <ChevronRight className={`size-4 motion-safe:transition-transform ${open ? "rotate-90" : ""}`} aria-hidden />
        {summary}
      </button>
      {open ? (
        <ul className="mt-1 space-y-1 pl-5">
          {visible.map((item) => {
            const Icon = ICONS[item.status as keyof typeof ICONS] ?? Check;
            const danger = item.status === "blocked" || item.status === "failed";
            return (
              <li key={`${item.tool_name}-${item.status}`} className={danger ? "text-danger" : "text-text"}>
                <p className="flex items-center gap-2 text-sm">
                  <Icon className="size-4 shrink-0" aria-hidden />
                  <span>{toolLabel(item.tool_name)}</span>
                  <span className="text-muted">{toolStatusLabel(item.status)}</span>
                </p>
                {item.reason ? <p className="pl-6 text-sm text-danger">{item.reason}</p> : null}
              </li>
            );
          })}
        </ul>
      ) : null}
    </div>
  );
}

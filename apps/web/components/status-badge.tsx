import { CheckCircle2, Circle, Clock, UserRound } from "lucide-react";
import type { ComponentType } from "react";

const CONVERSATION_STATUS = {
  open: { label: "Open", tone: "neutral", Icon: Circle },
  waiting_approval: { label: "Waiting for confirmation", tone: "warning", Icon: Clock },
  escalated: { label: "With support team", tone: "human", Icon: UserRound },
  resolved: { label: "Resolved", tone: "success", Icon: CheckCircle2 },
} as const;

const TONE_CLASS = {
  neutral: "bg-surface-subtle text-text",
  warning: "bg-warning-soft text-warning",
  human: "bg-human-soft text-human",
  success: "bg-success-soft text-success",
  info: "bg-info-soft text-info",
  danger: "bg-danger-soft text-danger",
} as const;

type StatusBadgeProps = {
  status: keyof typeof CONVERSATION_STATUS;
};

export function StatusBadge({ status }: StatusBadgeProps) {
  const item = CONVERSATION_STATUS[status];
  const Icon = item.Icon as ComponentType<{ className?: string; "aria-hidden"?: boolean }>;
  return (
    <span
      className={`inline-flex items-center gap-1 rounded-full px-2 py-1 text-sm font-medium ${TONE_CLASS[item.tone]}`}
    >
      <Icon className="size-4 shrink-0" aria-hidden />
      {item.label}
    </span>
  );
}

export function conversationStatusLabel(status: keyof typeof CONVERSATION_STATUS): string {
  return CONVERSATION_STATUS[status].label;
}

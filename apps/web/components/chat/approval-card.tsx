"use client";

import type { Approval, ProposedChange } from "@/lib/api/schemas";
import { Clock, LoaderCircle } from "lucide-react";
import { useEffect, useId, useRef, useState } from "react";

type ApprovalCardProps = {
  approval: Approval;
  submitting?: boolean;
  pendingAction?: "confirm" | "reject" | null;
  error?: string | null;
  audience?: "customer" | "staff";
  customerName?: string;
  approverName?: string;
  onConfirm: (approvalId: string) => void;
  onCancel: (approvalId: string) => void;
  onDismissError?: (approvalId: string) => void;
  onTalkToPerson?: () => void;
};

const ACTION_TITLE: Record<ProposedChange["kind"], string> = {
  address: "Change delivery address",
  return: "Start a return",
  refund: "Request a refund",
};

const CONFIRM_LABEL: Record<ProposedChange["kind"], string> = {
  address: "Confirm address change",
  return: "Start return",
  refund: "Request refund",
};

export function ApprovalCard({
  approval,
  submitting = false,
  pendingAction = null,
  error = null,
  audience = "customer",
  customerName,
  approverName,
  onConfirm,
  onCancel,
  onDismissError,
  onTalkToPerson,
}: ApprovalCardProps) {
  const titleId = useId();
  const statusRef = useRef<HTMLParagraphElement>(null);
  const change = approval.proposed_change;
  const failed = error !== null && error.trim() !== "";
  const pending = approval.status === "pending" && !failed;
  const [expanded, setExpanded] = useState(pending || failed);
  const [now, setNow] = useState(() => Date.now());

  useEffect(() => {
    if (!pending) {
      return;
    }
    const timer = window.setInterval(() => setNow(Date.now()), 60_000);
    return () => window.clearInterval(timer);
  }, [pending]);

  useEffect(() => {
    if (pending || submitting) {
      return;
    }
    statusRef.current?.focus();
  }, [approval.status, failed, pending, submitting]);

  const title = ACTION_TITLE[change.kind];
  const expiry = expiryCopy(approval.expires_at, now);
  const terminal = !pending && !submitting;

  return (
    <section
      role="group"
      aria-labelledby={titleId}
      aria-busy={submitting}
      className={`mt-3 max-w-prose rounded-lg border border-default bg-surface p-4 ${
        failed
          ? "border-l-4 border-l-danger"
          : pending || submitting
            ? "border-l-4 border-l-warning"
            : approval.status === "consumed"
              ? "border-l-4 border-l-success"
              : "border-l-4 border-l-strong"
      }`}
    >
      {pending || submitting ? (
        <div className="mb-3 flex items-start justify-between gap-3">
          <p className="inline-flex items-center gap-1 text-sm font-medium text-warning">
            <Clock className="size-4 shrink-0" aria-hidden />
            Awaiting confirmation
          </p>
          <p className={`text-sm tabular-nums ${expiry.urgent ? "font-medium text-warning" : "text-muted"}`}>
            {expiry.text}
          </p>
        </div>
      ) : null}
      <h2 id={titleId} className="text-base font-semibold text-text">
        {title}
      </h2>
      {audience === "staff" && customerName ? (
        <p className="mt-1 text-sm text-text">On behalf of {customerName}</p>
      ) : null}
      <p className="mt-1 text-sm text-muted">Order {change.order_number}</p>
      {expanded ? <Diff change={change} muted={approval.status === "expired"} /> : null}
      {change.kind === "refund" && (pending || submitting || failed || expanded) ? (
        <p className="mt-3 text-sm text-text">Refund request — not a payment</p>
      ) : null}
      <p
        ref={statusRef}
        tabIndex={-1}
        className={`mt-3 text-sm outline-none ${failed ? "text-danger" : "text-text"}`}
      >
        {statusCopy(approval, submitting, pendingAction, error, audience, approverName)}
      </p>
      {pending || submitting ? (
        <div className="mt-4 flex flex-col gap-2 sm:flex-row">
          <button
            type="button"
            disabled={submitting}
            onClick={() => onConfirm(approval.id)}
            className="inline-flex min-h-11 items-center justify-center gap-2 rounded-md bg-accent px-4 text-sm font-medium text-white hover:bg-accent-hover focus-visible:ring-2 focus-visible:ring-accent focus-visible:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-50"
          >
            {submitting ? <LoaderCircle className="size-4 animate-spin" aria-hidden /> : null}
            {submitting && pendingAction !== "reject"
              ? "Confirming…"
              : audience === "staff"
                ? "Approve as support agent"
                : CONFIRM_LABEL[change.kind]}
          </button>
          <button
            type="button"
            disabled={submitting}
            onClick={() => onCancel(approval.id)}
            className="inline-flex min-h-11 items-center justify-center rounded-md border border-strong bg-surface px-4 text-sm font-medium text-text focus-visible:ring-2 focus-visible:ring-accent focus-visible:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-50"
          >
            Cancel
          </button>
        </div>
      ) : null}
      {failed ? (
        <div className="mt-4 flex flex-col gap-2 sm:flex-row">
          <button
            type="button"
            onClick={() => onDismissError?.(approval.id)}
            className="inline-flex min-h-11 items-center justify-center rounded-md border border-strong bg-surface px-4 text-sm font-medium text-text focus-visible:ring-2 focus-visible:ring-accent focus-visible:ring-offset-2"
          >
            Close
          </button>
          {onTalkToPerson ? (
            <button
              type="button"
              onClick={onTalkToPerson}
              className="inline-flex min-h-11 items-center justify-center rounded-md border border-strong bg-surface px-4 text-sm font-medium text-text focus-visible:ring-2 focus-visible:ring-accent focus-visible:ring-offset-2"
            >
              Talk to a person
            </button>
          ) : null}
        </div>
      ) : null}
      {terminal && approval.status === "consumed" ? (
        <button
          type="button"
          className="mt-3 text-sm text-accent underline-offset-2 hover:underline focus-visible:ring-2 focus-visible:ring-accent"
          onClick={() => setExpanded((current) => !current)}
        >
          {expanded ? "Hide details" : "View details"}
        </button>
      ) : null}
    </section>
  );
}

function Diff({ change, muted }: { change: ProposedChange; muted: boolean }) {
  if (change.kind === "address") {
    const current = addressLines(change.current);
    const proposed = addressLines(change.proposed);
    const rows = Math.max(current.length, proposed.length);
    return (
      <div className={`mt-3 grid gap-3 sm:grid-cols-2 ${muted ? "text-muted line-through" : ""}`}>
        <div>
          <p className="text-xs font-medium tracking-wide text-muted uppercase">Current</p>
          <ul className="mt-1 space-y-1">
            {Array.from({ length: rows }, (_, index) => (
              <DiffLine
                key={`current-${index}`}
                value={current[index] ?? ""}
                changed={current[index] !== proposed[index]}
              />
            ))}
          </ul>
        </div>
        <div>
          <p className="text-xs font-medium tracking-wide text-muted uppercase">New</p>
          <ul className="mt-1 space-y-1">
            {Array.from({ length: rows }, (_, index) => (
              <DiffLine
                key={`new-${index}`}
                value={proposed[index] ?? ""}
                changed={current[index] !== proposed[index]}
              />
            ))}
          </ul>
        </div>
      </div>
    );
  }
  if (change.kind === "return") {
    return (
      <dl className={`mt-3 space-y-1 text-sm ${muted ? "text-muted line-through" : "text-text"}`}>
        <div>
          <dt className="text-muted">Reason</dt>
          <dd className="font-medium">
            {change.reason_label}
            <ChangedMark />
          </dd>
        </div>
      </dl>
    );
  }
  const amount = new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: change.currency,
  }).format(change.amount_cents / 100);
  return (
    <dl className={`mt-3 space-y-1 text-sm ${muted ? "text-muted line-through" : "text-text"}`}>
      <div>
        <dt className="text-muted">Amount</dt>
        <dd className="font-medium">
          {amount}
          <ChangedMark />
        </dd>
      </div>
      <div>
        <dt className="text-muted">Reason</dt>
        <dd>{change.reason_label}</dd>
      </div>
    </dl>
  );
}

function DiffLine({ value, changed }: { value: string; changed: boolean }) {
  if (value === "") {
    return null;
  }
  return (
    <li className={changed ? "font-semibold text-text" : "text-muted"}>
      {value}
      {changed ? <ChangedMark /> : null}
    </li>
  );
}

function ChangedMark() {
  return (
    <>
      <span aria-hidden> ◆</span>
      <span className="sr-only"> changed</span>
    </>
  );
}

function addressLines(address: {
  recipient: string;
  line1: string;
  line2?: string | null;
  city: string;
  region: string;
  postal_code: string;
  country: string;
}): string[] {
  return [
    address.recipient,
    address.line1,
    address.line2 ?? "",
    `${address.city}, ${address.region} ${address.postal_code}`,
    address.country,
  ];
}

function statusCopy(
  approval: Approval,
  submitting: boolean,
  pendingAction: "confirm" | "reject" | null,
  error: string | null,
  audience: "customer" | "staff",
  approverName?: string,
): string {
  if (submitting) {
    return pendingAction === "reject" ? "Cancelling…" : "Confirming…";
  }
  if (error) {
    return error;
  }
  if (approval.status === "pending") {
    return "Nothing changes until you confirm.";
  }
  if (approval.status === "consumed") {
    if (audience === "staff" && approverName) {
      const when = approval.approved_at ? formatConfirmed(approval.approved_at) : "";
      const stamp = when ? ` · ${when}` : "";
      return `Approved by ${approverName} (support)${stamp}.`;
    }
    return receipt(approval);
  }
  if (approval.status === "rejected") {
    return "You cancelled this change. Nothing was updated.";
  }
  if (approval.status === "expired") {
    return "This request expired and nothing changed. Ask again if you still need it.";
  }
  return "This change is waiting for confirmation.";
}

function receipt(approval: Approval): string {
  const when = approval.approved_at ? formatConfirmed(approval.approved_at) : "";
  const suffix = when ? ` Confirmed ${when}.` : "";
  if (approval.proposed_change.kind === "address") {
    return `Delivery address changed.${suffix}`;
  }
  if (approval.proposed_change.kind === "return") {
    return `Return started.${suffix}`;
  }
  return `Refund requested.${suffix}`;
}

function formatConfirmed(value: string): string {
  return new Intl.DateTimeFormat("en-US", {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  }).format(new Date(value));
}

function expiryCopy(expiresAt: string, now: number): { text: string; urgent: boolean } {
  const remainingMs = new Date(expiresAt).getTime() - now;
  const minutes = Math.max(1, Math.ceil(remainingMs / 60_000));
  if (minutes < 2) {
    return { text: "Expires in 1 min", urgent: true };
  }
  return { text: `Expires in ${minutes} min`, urgent: false };
}

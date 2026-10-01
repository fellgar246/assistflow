import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { Approval } from "@/lib/api/schemas";
import { ApprovalCard } from "./approval-card";

const address = (line1: string, line2: string | null = null) => ({
  recipient: "Ava Chen",
  line1,
  line2,
  city: "Austin",
  region: "TX",
  postal_code: "78701",
  country: "US",
});

function approval(overrides: Partial<Approval> = {}): Approval {
  return {
    id: "99999999-9999-4999-8999-999999999999",
    action_type: "update_shipping_address",
    status: "pending",
    proposed_change: {
      kind: "address",
      order_number: "ORD-10482",
      current: address("18 Market Street", "Apt 4"),
      proposed: address("42 Congress Avenue"),
    },
    requested_at: "2026-09-30T16:00:00Z",
    expires_at: "2026-09-30T16:15:00Z",
    approved_at: null,
    ...overrides,
  };
}

describe("approval card", () => {
  it("shows the current and proposed address and sends only the approval id", () => {
    const onConfirm = vi.fn();
    const onCancel = vi.fn();
    render(<ApprovalCard approval={approval()} onConfirm={onConfirm} onCancel={onCancel} />);

    expect(screen.getByRole("group", { name: "Change delivery address" })).toBeInTheDocument();
    expect(screen.getByText("18 Market Street")).toBeInTheDocument();
    expect(screen.getByText("42 Congress Avenue")).toBeInTheDocument();
    expect(screen.getByText("Nothing changes until you confirm.")).toBeInTheDocument();
    expect(screen.getAllByText("changed", { selector: ".sr-only" }).length).toBeGreaterThan(0);
    expect(screen.queryByRole("textbox")).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Confirm address change" }));
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(onConfirm).toHaveBeenCalledWith("99999999-9999-4999-8999-999999999999");
    expect(onCancel).toHaveBeenCalledWith("99999999-9999-4999-8999-999999999999");
  });

  it("disables confirm and cancel while the request is in flight", () => {
    render(
      <ApprovalCard
        approval={approval()}
        submitting
        pendingAction="confirm"
        onConfirm={vi.fn()}
        onCancel={vi.fn()}
      />,
    );
    const group = screen.getByRole("group", { name: "Change delivery address" });
    expect(group).toHaveAttribute("aria-busy", "true");
    expect(screen.getByRole("button", { name: "Confirming…" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Cancel" })).toBeDisabled();
  });

  it("renders consumed, rejected, expired, and failed copy", () => {
    const { rerender } = render(
      <ApprovalCard
        approval={approval({ status: "consumed", approved_at: "2026-09-30T16:05:00Z" })}
        onConfirm={vi.fn()}
        onCancel={vi.fn()}
      />,
    );
    expect(screen.getByText(/Delivery address changed/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Confirm address change" })).not.toBeInTheDocument();

    rerender(
      <ApprovalCard
        approval={approval({ status: "rejected" })}
        onConfirm={vi.fn()}
        onCancel={vi.fn()}
      />,
    );
    expect(screen.getByText("You cancelled this change. Nothing was updated.")).toBeInTheDocument();

    rerender(
      <ApprovalCard
        approval={approval({ status: "expired" })}
        onConfirm={vi.fn()}
        onCancel={vi.fn()}
      />,
    );
    expect(
      screen.getByText("This request expired and nothing changed. Ask again if you still need it."),
    ).toBeInTheDocument();

    rerender(
      <ApprovalCard
        approval={approval()}
        error="This shipment can no longer be changed."
        onConfirm={vi.fn()}
        onCancel={vi.fn()}
      />,
    );
    expect(screen.getByText("This shipment can no longer be changed.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Close" })).toBeInTheDocument();
  });

  it("formats a refund request without a card number", () => {
    render(
      <ApprovalCard
        approval={approval({
          action_type: "create_refund_request",
          proposed_change: {
            kind: "refund",
            order_number: "ORD-10482",
            amount_cents: 1500,
            currency: "USD",
            reason_code: "damaged",
            reason_label: "Damaged",
          },
        })}
        onConfirm={vi.fn()}
        onCancel={vi.fn()}
      />,
    );
    expect(screen.getByRole("button", { name: "Request refund" })).toBeInTheDocument();
    expect(screen.getByText("$15.00")).toBeInTheDocument();
    expect(screen.getByText("Refund request — not a payment")).toBeInTheDocument();
    expect(screen.queryByText(/card/i)).not.toBeInTheDocument();
  });
});

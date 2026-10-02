import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { StaffConversation } from "@/lib/api/schemas";
import { EmptyInbox, InboxList } from "./inbox-list";
import { TracePanel } from "./trace-panel";

const row = (overrides: Partial<StaffConversation> = {}): StaffConversation => ({
  id: "11111111-1111-4111-8111-111111111111",
  customer_id: "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaa0001",
  customer_display_name: "Ava Chen",
  channel: "web",
  status: "escalated",
  assigned_to: null,
  assignee_name: null,
  ticket_id: null,
  ticket_priority: null,
  pending_approval_count: 0,
  preview: "Can you change the delivery address?",
  created_at: "2026-10-01T18:00:00Z",
  updated_at: "2026-10-01T18:04:00Z",
  ...overrides,
});

describe("support inbox", () => {
  it("explains an empty queue", () => {
    render(<EmptyInbox />);
    expect(
      screen.getByText(
        "Nothing is waiting. Escalated conversations and pending approvals will show up here.",
      ),
    ).toBeInTheDocument();
  });

  it("shows the customer, status, and updated time", () => {
    render(<InboxList items={[row()]} />);
    expect(screen.getByText("Ava Chen")).toBeInTheDocument();
    expect(screen.getByText("With support team")).toBeInTheDocument();
    expect(screen.getByText("Unassigned")).toBeInTheDocument();
    const link = screen.getByRole("link", { name: /Ava Chen/ });
    expect(link).toHaveAttribute("href", "/agent/conversations/11111111-1111-4111-8111-111111111111");
  });
});

describe("trace summary", () => {
  it("shows kind, tool, status, latency, and the error code", () => {
    render(
      <TracePanel
        summary={{
          items: [
            {
              id: "22222222-2222-4222-8222-222222222222",
              stop_reason: "completed",
              created_at: "2026-10-01T18:00:00Z",
              step_count: 1,
              step_limit: 8,
              tool_call_count: 1,
              tool_call_limit: 5,
              total_latency_ms: 320,
              stopped_by_limit: false,
              steps: [
                {
                  step: 1,
                  kind: "Tool call",
                  tool_name: "get_order",
                  status: "blocked",
                  latency_ms: 320,
                  error_code: "tool_denied",
                  detail: "This action is not available.",
                  arguments_hash: "abc12345",
                },
              ],
            },
          ],
        }}
      />,
    );
    expect(screen.getByText("Tool call")).toBeInTheDocument();
    expect(screen.getByText("get_order")).toBeInTheDocument();
    expect(screen.getByText("Blocked")).toBeInTheDocument();
    expect(screen.getByText("320 ms")).toBeInTheDocument();
    expect(screen.getByText("tool_denied")).toBeInTheDocument();
    expect(screen.queryByText(/PROVIDER_PAYLOAD/)).not.toBeInTheDocument();
  });
});

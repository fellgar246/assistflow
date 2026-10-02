import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { Message } from "@/lib/api/schemas";
import { Composer } from "./composer";
import { Citations } from "./citations";
import { ErrorPanel, EmptyThread } from "./states";
import { ToolActivityRow } from "./tool-activity";
import { Transcript } from "./transcript";

const message = (overrides: Partial<Message> = {}): Message => ({
  id: "11111111-1111-4111-8111-111111111111",
  role: "assistant",
  content: "Thanks, I saved your message.",
  created_at: "2026-09-23T18:00:00Z",
  citations: [],
  tool_activity: [],
  approvals: [],
  author_type: "model",
  ...overrides,
});

describe("composer", () => {
  it("sends on Enter, inserts a newline on Shift+Enter, and names the send control", () => {
    const onSend = vi.fn();
    render(<Composer onSend={onSend} />);
    const field = screen.getByRole("textbox", { name: "Message" });
    expect(screen.getByRole("button", { name: "Send message" })).toBeDisabled();

    fireEvent.change(field, { target: { value: "Where is my order?" } });
    fireEvent.keyDown(field, { key: "Enter", shiftKey: true });
    expect(onSend).not.toHaveBeenCalled();

    fireEvent.keyDown(field, { key: "Enter" });
    expect(onSend).toHaveBeenCalledOnce();
    expect(onSend).toHaveBeenCalledWith("Where is my order?");
  });

  it("does not send a second time while a send is in flight", () => {
    const onSend = vi.fn();
    render(<Composer onSend={onSend} sending />);
    const field = screen.getByRole("textbox", { name: "Message" });
    fireEvent.change(field, { target: { value: "Hello" } });
    fireEvent.keyDown(field, { key: "Enter" });
    fireEvent.click(screen.getByRole("button", { name: "Send message" }));
    expect(onSend).not.toHaveBeenCalled();
  });
});

describe("transcript states", () => {
  it("invites the customer to ask a support question when the thread is empty", () => {
    render(<EmptyThread onSuggest={vi.fn()} />);
    expect(screen.getByRole("heading", { name: "Ask a support question" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Where is my order?" })).toBeInTheDocument();
  });

  it("shows an English error and a retry action", () => {
    const onRetry = vi.fn();
    render(<ErrorPanel onRetry={onRetry} />);
    expect(screen.getByRole("alert")).toHaveTextContent("couldn't load this conversation");
    fireEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(onRetry).toHaveBeenCalledOnce();
  });

  it("labels a human reply as a person and skips sources", () => {
    render(
      <Transcript
        messages={[
          message({
            role: "assistant",
            author_type: "support_agent",
            author_name: "Nora Hale",
            content: "I can help with that order.",
            citations: [{ title: "Shipping policy", version: "3" }],
          }),
        ]}
      />,
    );
    expect(screen.getByText("Nora")).toBeInTheDocument();
    expect(screen.getByText("· Support team")).toBeInTheDocument();
    expect(screen.getByText("I can help with that order.")).toBeInTheDocument();
    expect(screen.queryByText("Automated")).not.toBeInTheDocument();
    expect(screen.queryByRole("region", { name: "Sources" })).not.toBeInTheDocument();
  });

  it("labels a human reply as a person and not as an automated answer", () => {
    render(
      <Transcript
        messages={[
          message({
            role: "assistant",
            author_type: "support_agent",
            author_name: "Nora Hale",
            content: "I can help with that order.",
            citations: [{ title: "Shipping policy", version: "3" }],
          }),
        ]}
      />,
    );
    expect(screen.getByText("Nora")).toBeInTheDocument();
    expect(screen.getByText("· Support team")).toBeInTheDocument();
    expect(screen.getByText("I can help with that order.")).toBeInTheDocument();
    expect(screen.queryByText("Automated")).not.toBeInTheDocument();
    expect(screen.queryByRole("region", { name: "Sources" })).not.toBeInTheDocument();
  });

  it("announces messages from a polite live region", () => {
    render(<Transcript messages={[message({ role: "customer", content: "Hello" })]} />);
    expect(screen.getByRole("log", { name: "Conversation" })).toHaveAttribute("aria-live", "polite");
    expect(screen.getByText("Hello")).toBeInTheDocument();
  });
});

describe("citations and tool activity", () => {
  it("shows a citation title and hides the block when there are none", () => {
    const { rerender } = render(
      <Citations citations={[{ title: "Shipping policy", version: "3" }]} />,
    );
    expect(screen.getByRole("region", { name: "Sources" })).toBeInTheDocument();
    expect(screen.getByText("Shipping policy")).toBeInTheDocument();
    expect(screen.getByText("Version 3")).toBeInTheDocument();
    expect(screen.queryByRole("link")).not.toBeInTheDocument();

    rerender(<Citations citations={[]} />);
    expect(screen.queryByRole("region", { name: "Sources" })).not.toBeInTheDocument();
  });

  it("shows the tool name and status in English and hides an empty summary", () => {
    const { rerender } = render(
      <ToolActivityRow
        items={[{ tool_name: "get_shipment", status: "succeeded" }]}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: "Checked shipment status" }));
    expect(screen.getByRole("list")).toHaveTextContent("Checked shipment status");
    expect(screen.getByRole("list")).toHaveTextContent("Done");
    expect(screen.getByRole("list")).not.toHaveTextContent("get_shipment");

    rerender(<ToolActivityRow items={[]} />);
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
  });
});

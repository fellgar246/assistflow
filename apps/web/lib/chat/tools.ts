const TOOL_LABELS: Record<string, string> = {
  get_order: "Looked up your order",
  get_shipment: "Checked shipment status",
  get_customer_profile: "Checked your account",
  get_ticket: "Checked your support ticket",
  search_support_policy: "Searched help articles",
  check_address_change_eligibility: "Checked if the address can change",
  check_return_eligibility: "Checked return eligibility",
  check_refund_eligibility: "Checked refund eligibility",
  create_ticket: "Created a support ticket",
  add_ticket_note: "Added a note to your ticket",
  request_human_escalation: "Asked the support team to join",
  update_shipping_address: "Change delivery address",
  create_return_request: "Start a return",
  create_refund_request: "Request a refund",
};

const STATUS_LABELS: Record<string, string> = {
  running: "Checking…",
  succeeded: "Done",
  pending_approval: "Needs your confirmation",
  blocked: "Not allowed",
  failed: "Couldn't complete",
};

export function toolLabel(toolName: string): string {
  return TOOL_LABELS[toolName] ?? "Ran a check";
}

export function toolStatusLabel(status: string): string {
  return STATUS_LABELS[status] ?? "Done";
}

export function visibleToolActivity<T extends { status: string }>(items: T[]): T[] {
  return items.filter((item) => item.status !== "proposed");
}

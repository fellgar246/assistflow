import { z } from "zod";
import { ApiError } from "./client";
import {
  messageSchema,
  staffActorListSchema,
  staffConversationSchema,
  staffInboxSchema,
  ticketDetailSchema,
  traceSummarySchema,
  messagePageSchema,
  approvalSchema,
  type Approval,
  type Message,
  type StaffActor,
  type StaffConversation,
  type StaffInbox,
  type TicketDetail,
  type TraceSummary,
} from "./schemas";

export type StaffHeaders = {
  tenantId: string;
  agentId: string;
};

async function staffRequest<T>(
  path: string,
  schema: z.ZodType<T>,
  staff: StaffHeaders,
  init: RequestInit = {},
): Promise<T> {
  const headers = new Headers(init.headers);
  if (init.body !== undefined) {
    headers.set("Content-Type", "application/json");
  }
  headers.set("X-Tenant-Id", staff.tenantId);
  headers.set("X-Agent-Id", staff.agentId);
  let response: Response;
  try {
    response = await fetch(`/api${path}`, { ...init, headers });
  } catch {
    throw new ApiError("We couldn't load this conversation. Check your connection and try again.", 0);
  }
  if (!response.ok) {
    throw new ApiError(await problemMessage(response), response.status);
  }
  return parse(response, schema);
}

async function parse<T>(response: Response, schema: z.ZodType<T>): Promise<T> {
  let payload: unknown;
  try {
    payload = await response.json();
  } catch {
    throw new ApiError("Something went wrong displaying this conversation.", response.status);
  }
  const parsed = schema.safeParse(payload);
  if (!parsed.success) {
    if (process.env.NODE_ENV === "development") {
      console.error("Invalid API payload", parsed.error);
    }
    throw new ApiError("Something went wrong displaying this conversation.", response.status);
  }
  return parsed.data;
}

async function problemMessage(response: Response): Promise<string> {
  try {
    const payload: unknown = await response.json();
    if (
      typeof payload === "object" &&
      payload !== null &&
      "message" in payload &&
      typeof payload.message === "string" &&
      payload.message.trim() !== ""
    ) {
      return payload.message;
    }
  } catch {
    return "We couldn't load this conversation. Check your connection and try again.";
  }
  return "We couldn't load this conversation. Check your connection and try again.";
}

export async function listStaffActors(): Promise<{ actors: StaffActor[] }> {
  let response: Response;
  try {
    response = await fetch("/api/dev/staff");
  } catch {
    throw new ApiError("We couldn't load this conversation. Check your connection and try again.", 0);
  }
  if (!response.ok) {
    throw new ApiError("You don't have access to this page.", response.status);
  }
  return parse(response, staffActorListSchema);
}

export function listInbox(
  staff: StaffHeaders,
  queue: "all" | "escalated" | "waiting_approval",
  cursor?: string | null,
): Promise<StaffInbox> {
  const params = new URLSearchParams({ queue, limit: "20" });
  if (cursor) {
    params.set("cursor", cursor);
  }
  return staffRequest(`/staff/inbox?${params.toString()}`, staffInboxSchema, staff);
}

export function readStaffConversation(
  staff: StaffHeaders,
  conversationId: string,
): Promise<StaffConversation> {
  return staffRequest(`/staff/conversations/${conversationId}`, staffConversationSchema, staff);
}

export function readStaffTranscript(
  staff: StaffHeaders,
  conversationId: string,
): Promise<{ items: Message[] }> {
  return staffRequest(
    `/staff/conversations/${conversationId}/messages?limit=100`,
    messagePageSchema,
    staff,
  );
}

export function readTrace(staff: StaffHeaders, conversationId: string): Promise<TraceSummary> {
  return staffRequest(`/staff/conversations/${conversationId}/trace`, traceSummarySchema, staff);
}

export function readTicket(staff: StaffHeaders, ticketId: string): Promise<TicketDetail> {
  return staffRequest(`/staff/tickets/${ticketId}`, ticketDetailSchema, staff);
}

export function takeOver(
  staff: StaffHeaders,
  conversationId: string,
  idempotencyKey: string,
): Promise<StaffConversation> {
  return staffRequest(
    `/staff/conversations/${conversationId}/takeover`,
    staffConversationSchema,
    staff,
    { method: "POST", body: JSON.stringify({ idempotency_key: idempotencyKey }) },
  );
}

export function resolveConversation(
  staff: StaffHeaders,
  conversationId: string,
  idempotencyKey: string,
): Promise<StaffConversation> {
  return staffRequest(
    `/staff/conversations/${conversationId}/resolve`,
    staffConversationSchema,
    staff,
    { method: "POST", body: JSON.stringify({ idempotency_key: idempotencyKey }) },
  );
}

export function postStaffReply(
  staff: StaffHeaders,
  conversationId: string,
  content: string,
  idempotencyKey: string,
): Promise<Message> {
  return staffRequest(`/staff/conversations/${conversationId}/messages`, messageSchema, staff, {
    method: "POST",
    body: JSON.stringify({ content, idempotency_key: idempotencyKey }),
  });
}

export function confirmAsStaff(
  staff: StaffHeaders,
  conversationId: string,
  approvalId: string,
): Promise<Approval> {
  return staffRequest(
    `/staff/conversations/${conversationId}/approvals/${approvalId}/confirm`,
    approvalSchema,
    staff,
    { method: "POST", body: "{}" },
  );
}

export function rejectAsStaff(
  staff: StaffHeaders,
  conversationId: string,
  approvalId: string,
): Promise<Approval> {
  return staffRequest(
    `/staff/conversations/${conversationId}/approvals/${approvalId}/reject`,
    approvalSchema,
    staff,
    { method: "POST", body: "{}" },
  );
}

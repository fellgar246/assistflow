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

async function staffRequest<T>(
  path: string,
  schema: z.ZodType<T>,
  init: RequestInit = {},
): Promise<T> {
  const headers = new Headers(init.headers);
  if (init.body !== undefined) {
    headers.set("Content-Type", "application/json");
  }
  let response: Response;
  try {
    response = await fetch(`/api${path}`, { ...init, headers, credentials: "include" });
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
    response = await fetch("/api/dev/staff", { credentials: "include" });
  } catch {
    throw new ApiError("We couldn't load this conversation. Check your connection and try again.", 0);
  }
  if (!response.ok) {
    throw new ApiError("You don't have access to this page.", response.status);
  }
  return parse(response, staffActorListSchema);
}

export function listInbox(
  queue: "all" | "escalated" | "waiting_approval",
  cursor?: string | null,
): Promise<StaffInbox> {
  const params = new URLSearchParams({ queue, limit: "20" });
  if (cursor) {
    params.set("cursor", cursor);
  }
  return staffRequest(`/staff/inbox?${params.toString()}`, staffInboxSchema);
}

export function readStaffConversation(conversationId: string): Promise<StaffConversation> {
  return staffRequest(`/staff/conversations/${conversationId}`, staffConversationSchema);
}

export function readStaffTranscript(conversationId: string): Promise<{ items: Message[] }> {
  return staffRequest(
    `/staff/conversations/${conversationId}/messages?limit=100`,
    messagePageSchema,
  );
}

export function readTrace(conversationId: string): Promise<TraceSummary> {
  return staffRequest(`/staff/conversations/${conversationId}/trace`, traceSummarySchema);
}

export function readTicket(ticketId: string): Promise<TicketDetail> {
  return staffRequest(`/staff/tickets/${ticketId}`, ticketDetailSchema);
}

export function takeOver(conversationId: string, idempotencyKey: string): Promise<StaffConversation> {
  return staffRequest(`/staff/conversations/${conversationId}/takeover`, staffConversationSchema, {
    method: "POST",
    body: JSON.stringify({ idempotency_key: idempotencyKey }),
  });
}

export function resolveConversation(
  conversationId: string,
  idempotencyKey: string,
): Promise<StaffConversation> {
  return staffRequest(`/staff/conversations/${conversationId}/resolve`, staffConversationSchema, {
    method: "POST",
    body: JSON.stringify({ idempotency_key: idempotencyKey }),
  });
}

export function postStaffReply(
  conversationId: string,
  content: string,
  idempotencyKey: string,
): Promise<Message> {
  return staffRequest(`/staff/conversations/${conversationId}/messages`, messageSchema, {
    method: "POST",
    body: JSON.stringify({ content, idempotency_key: idempotencyKey }),
  });
}

export function confirmAsStaff(conversationId: string, approvalId: string): Promise<Approval> {
  return staffRequest(
    `/staff/conversations/${conversationId}/approvals/${approvalId}/confirm`,
    approvalSchema,
    { method: "POST", body: "{}" },
  );
}

export function rejectAsStaff(conversationId: string, approvalId: string): Promise<Approval> {
  return staffRequest(
    `/staff/conversations/${conversationId}/approvals/${approvalId}/reject`,
    approvalSchema,
    { method: "POST", body: "{}" },
  );
}

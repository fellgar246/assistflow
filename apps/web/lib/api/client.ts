import { z } from "zod";
import {
  conversationPageSchema,
  conversationSchema,
  loginCatalogSchema,
  sessionProfileSchema,
  approvalSchema,
  messagePageSchema,
  messageSchema,
  openConversationBodySchema,
  postMessageBodySchema,
  type Approval,
  type Conversation,
  type LoginUser,
  type Message,
  type SessionProfile,
} from "./schemas";

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

async function parseBody<T>(response: Response, schema: z.ZodType<T>): Promise<T> {
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

async function request<T>(
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
    throw new ApiError("We couldn't load this conversation. Check your connection and try again.", response.status);
  }
  return parseBody(response, schema);
}

export function readSession(): Promise<SessionProfile> {
  return request("/dev/session", sessionProfileSchema);
}

export function listLoginUsers(): Promise<{ users: LoginUser[] }> {
  return request("/dev/issuer/users", loginCatalogSchema);
}

export function startSession(user: string): Promise<SessionProfile> {
  return request("/dev/issuer/session", sessionProfileSchema, {
    method: "POST",
    body: JSON.stringify({ user }),
  });
}

export function listConversations(): Promise<{ items: Conversation[] }> {
  return request("/conversations?limit=100", conversationPageSchema);
}

export function createConversation(idempotencyKey: string): Promise<Conversation> {
  const body = openConversationBodySchema.parse({ idempotency_key: idempotencyKey });
  return request("/conversations", conversationSchema, { method: "POST", body: JSON.stringify(body) });
}

export function readConversation(conversationId: string): Promise<Conversation> {
  return request(`/conversations/${conversationId}`, conversationSchema);
}

export function readTranscript(conversationId: string): Promise<{ items: Message[] }> {
  return request(`/conversations/${conversationId}/messages?limit=100`, messagePageSchema);
}

export function confirmApproval(conversationId: string, approvalId: string): Promise<Approval> {
  return decide(conversationId, approvalId, "confirm");
}

export function rejectApproval(conversationId: string, approvalId: string): Promise<Approval> {
  return decide(conversationId, approvalId, "reject");
}

async function decide(
  conversationId: string,
  approvalId: string,
  action: "confirm" | "reject",
): Promise<Approval> {
  const headers = new Headers({ "Content-Type": "application/json" });
  let response: Response;
  try {
    response = await fetch(
      `/api/conversations/${conversationId}/approvals/${approvalId}/${action}`,
      { method: "POST", headers, body: "{}", credentials: "include" },
    );
  } catch {
    throw new ApiError("We couldn't load this conversation. Check your connection and try again.", 0);
  }
  if (!response.ok) {
    throw new ApiError(await problemMessage(response, action), response.status);
  }
  return parseBody(response, approvalSchema);
}

async function problemMessage(response: Response, action: "confirm" | "reject"): Promise<string> {
  const fallback =
    action === "confirm"
      ? "This change could not be confirmed."
      : "This change could not be cancelled.";
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
    return fallback;
  }
  return fallback;
}

export async function postMessage(
  conversationId: string,
  content: string,
  idempotencyKey: string,
): Promise<{ message: Message; conversationId: string }> {
  const body = postMessageBodySchema.parse({ content, idempotency_key: idempotencyKey });
  const headers = new Headers({ "Content-Type": "application/json" });
  let response: Response;
  try {
    response = await fetch(`/api/conversations/${conversationId}/messages`, {
      method: "POST",
      headers,
      body: JSON.stringify(body),
      credentials: "include",
    });
  } catch {
    throw new ApiError("We couldn't load this conversation. Check your connection and try again.", 0);
  }
  if (!response.ok) {
    throw new ApiError("We couldn't load this conversation. Check your connection and try again.", response.status);
  }
  const message = await parseBody(response, messageSchema);
  return {
    message,
    conversationId: response.headers.get("X-Conversation-Id") ?? conversationId,
  };
}

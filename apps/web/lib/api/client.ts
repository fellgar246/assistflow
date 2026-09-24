import { z } from "zod";
import {
  conversationPageSchema,
  conversationSchema,
  localActorListSchema,
  messagePageSchema,
  messageSchema,
  openConversationBodySchema,
  postMessageBodySchema,
  type Conversation,
  type LocalActor,
  type Message,
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

export type ActorHeaders = {
  tenantId: string;
  customerId: string;
};

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
  actor?: ActorHeaders,
): Promise<T> {
  const headers = new Headers(init.headers);
  if (init.body !== undefined) {
    headers.set("Content-Type", "application/json");
  }
  if (actor) {
    headers.set("X-Tenant-Id", actor.tenantId);
    headers.set("X-Customer-Id", actor.customerId);
  }
  let response: Response;
  try {
    response = await fetch(`/api${path}`, { ...init, headers });
  } catch {
    throw new ApiError("We couldn't load this conversation. Check your connection and try again.", 0);
  }
  if (!response.ok) {
    throw new ApiError("We couldn't load this conversation. Check your connection and try again.", response.status);
  }
  return parseBody(response, schema);
}

export function listLocalActors(): Promise<{ actors: LocalActor[] }> {
  return request("/dev/actors", localActorListSchema);
}

export function listConversations(actor: ActorHeaders): Promise<{ items: Conversation[] }> {
  return request("/conversations?limit=100", conversationPageSchema, {}, actor);
}

export function createConversation(actor: ActorHeaders, idempotencyKey: string): Promise<Conversation> {
  const body = openConversationBodySchema.parse({ idempotency_key: idempotencyKey });
  return request("/conversations", conversationSchema, { method: "POST", body: JSON.stringify(body) }, actor);
}

export function readConversation(actor: ActorHeaders, conversationId: string): Promise<Conversation> {
  return request(`/conversations/${conversationId}`, conversationSchema, {}, actor);
}

export function readTranscript(actor: ActorHeaders, conversationId: string): Promise<{ items: Message[] }> {
  return request(
    `/conversations/${conversationId}/messages?limit=100`,
    messagePageSchema,
    {},
    actor,
  );
}

export function postMessage(
  actor: ActorHeaders,
  conversationId: string,
  content: string,
  idempotencyKey: string,
): Promise<Message> {
  const body = postMessageBodySchema.parse({ content, idempotency_key: idempotencyKey });
  return request(
    `/conversations/${conversationId}/messages`,
    messageSchema,
    { method: "POST", body: JSON.stringify(body) },
    actor,
  );
}

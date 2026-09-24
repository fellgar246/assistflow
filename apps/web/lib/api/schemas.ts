import { z } from "zod";

export const conversationStatusSchema = z.enum([
  "open",
  "waiting_approval",
  "escalated",
  "resolved",
]);

export const citationSchema = z.object({
  title: z.string().min(1),
  version: z.string().nullable().optional(),
});

export const toolActivitySchema = z.object({
  tool_name: z.string().min(1),
  status: z.enum([
    "proposed",
    "running",
    "succeeded",
    "pending_approval",
    "blocked",
    "failed",
  ]),
  reason: z.string().nullable().optional(),
});

export const messageSchema = z.object({
  id: z.uuid(),
  role: z.enum(["customer", "assistant", "system", "tool"]),
  content: z.string(),
  created_at: z.string(),
  citations: z.array(citationSchema).default([]),
  tool_activity: z.array(toolActivitySchema).default([]),
});

export const messagePageSchema = z.object({
  items: z.array(messageSchema),
  next_cursor: z.string().nullable(),
});

export const conversationSchema = z.object({
  id: z.uuid(),
  customer_id: z.uuid(),
  channel: z.literal("web"),
  status: conversationStatusSchema,
  created_at: z.string(),
  updated_at: z.string(),
  preview: z.string().nullable().optional(),
});

export const conversationPageSchema = z.object({
  items: z.array(conversationSchema),
  next_cursor: z.string().nullable(),
});

export const localActorSchema = z.object({
  label: z.string(),
  organization: z.string(),
  tenant_id: z.uuid(),
  customer_id: z.uuid(),
});

export const localActorListSchema = z.object({
  actors: z.array(localActorSchema),
});

export const openConversationBodySchema = z.object({
  idempotency_key: z.string().min(1).max(200),
});

export const postMessageBodySchema = z.object({
  content: z.string().min(1).max(8000),
  idempotency_key: z.string().min(1).max(200),
});

export type Citation = z.infer<typeof citationSchema>;
export type ToolActivity = z.infer<typeof toolActivitySchema>;
export type Message = z.infer<typeof messageSchema>;
export type Conversation = z.infer<typeof conversationSchema>;
export type LocalActor = z.infer<typeof localActorSchema>;

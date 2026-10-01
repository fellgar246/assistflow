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

const shippingAddressSchema = z.object({
  recipient: z.string(),
  line1: z.string(),
  line2: z.string().nullable().optional(),
  city: z.string(),
  region: z.string(),
  postal_code: z.string(),
  country: z.string(),
});

export const proposedChangeSchema = z.discriminatedUnion("kind", [
  z.object({
    kind: z.literal("address"),
    order_number: z.string(),
    current: shippingAddressSchema,
    proposed: shippingAddressSchema,
  }),
  z.object({
    kind: z.literal("return"),
    order_number: z.string(),
    reason_code: z.string(),
    reason_label: z.string(),
  }),
  z.object({
    kind: z.literal("refund"),
    order_number: z.string(),
    amount_cents: z.number().int().positive(),
    currency: z.string().length(3),
    reason_code: z.string(),
    reason_label: z.string(),
  }),
]);

export const approvalSchema = z.object({
  id: z.uuid(),
  action_type: z.string().min(1),
  status: z.enum(["pending", "approved", "rejected", "expired", "consumed"]),
  proposed_change: proposedChangeSchema,
  requested_at: z.string(),
  expires_at: z.string(),
  approved_at: z.string().nullable().optional(),
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
  approvals: z.array(approvalSchema).default([]),
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
export type Approval = z.infer<typeof approvalSchema>;
export type ProposedChange = z.infer<typeof proposedChangeSchema>;
export type Message = z.infer<typeof messageSchema>;
export type Conversation = z.infer<typeof conversationSchema>;
export type LocalActor = z.infer<typeof localActorSchema>;

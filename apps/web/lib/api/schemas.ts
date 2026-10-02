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
  approved_by: z.uuid().nullable().optional(),
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
  author_type: z.enum(["customer", "model", "support_agent", "system"]).default("model"),
  author_name: z.string().nullable().optional(),
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

export const loginUserSchema = z.object({
  key: z.string().min(1),
  label: z.string(),
  organization: z.string(),
  role: z.enum(["customer", "support_agent"]),
});

export const loginCatalogSchema = z.object({
  users: z.array(loginUserSchema),
});

export const sessionProfileSchema = loginUserSchema;

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
export type LoginUser = z.infer<typeof loginUserSchema>;
export type SessionProfile = z.infer<typeof sessionProfileSchema>;
export type LocalActor = z.infer<typeof localActorSchema>;

export const staffActorSchema = z.object({
  label: z.string(),
  organization: z.string(),
  tenant_id: z.uuid(),
  agent_id: z.uuid(),
});

export const staffActorListSchema = z.object({
  actors: z.array(staffActorSchema),
});

export const staffConversationSchema = z.object({
  id: z.uuid(),
  customer_id: z.uuid(),
  customer_display_name: z.string(),
  channel: z.literal("web"),
  status: conversationStatusSchema,
  assigned_to: z.uuid().nullable(),
  assignee_name: z.string().nullable(),
  ticket_id: z.uuid().nullable(),
  ticket_priority: z.enum(["low", "normal", "high"]).nullable(),
  pending_approval_count: z.number().int().nonnegative(),
  preview: z.string().nullable(),
  created_at: z.string(),
  updated_at: z.string(),
});

export const staffInboxSchema = z.object({
  items: z.array(staffConversationSchema),
  next_cursor: z.string().nullable(),
  counts: z.object({
    all: z.number().int().nonnegative(),
    escalated: z.number().int().nonnegative(),
    waiting_approval: z.number().int().nonnegative(),
  }),
});

export const traceStepSchema = z.object({
  step: z.number().int().positive(),
  kind: z.string(),
  tool_name: z.string().nullable().optional(),
  status: z.string().nullable().optional(),
  latency_ms: z.number().int().nonnegative(),
  error_code: z.string().nullable().optional(),
  detail: z.string(),
  arguments_hash: z.string().nullable().optional(),
});

export const traceSummarySchema = z.object({
  items: z.array(
    z.object({
      id: z.uuid(),
      stop_reason: z.string(),
      created_at: z.string(),
      steps: z.array(traceStepSchema),
      step_count: z.number().int().nonnegative(),
      step_limit: z.number().int().positive(),
      tool_call_count: z.number().int().nonnegative(),
      tool_call_limit: z.number().int().positive(),
      total_latency_ms: z.number().int().nonnegative(),
      stopped_by_limit: z.boolean(),
    }),
  ),
});

export const ticketDetailSchema = z.object({
  id: z.uuid(),
  customer_display_name: z.string(),
  priority: z.enum(["low", "normal", "high"]),
  category: z.string(),
  status: z.enum(["open", "pending", "escalated", "resolved"]),
  summary: z.string(),
  conversation_id: z.uuid().nullable(),
  assigned_to: z.uuid().nullable(),
  assignee_name: z.string().nullable(),
  created_at: z.string(),
  notes: z.array(
    z.object({
      id: z.uuid(),
      body: z.string(),
      author_type: z.string(),
      created_at: z.string(),
    }),
  ),
});

export type StaffActor = z.infer<typeof staffActorSchema>;
export type StaffConversation = z.infer<typeof staffConversationSchema>;
export type StaffInbox = z.infer<typeof staffInboxSchema>;
export type TraceSummary = z.infer<typeof traceSummarySchema>;
export type TraceStep = z.infer<typeof traceStepSchema>;
export type TicketDetail = z.infer<typeof ticketDetailSchema>;

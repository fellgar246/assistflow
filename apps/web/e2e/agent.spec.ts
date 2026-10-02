import { expect, test } from "@playwright/test";

const STAFF = {
  label: "Nora Hale",
  organization: "Harbor Goods",
  tenant_id: "11111111-1111-4111-8111-111111111111",
  agent_id: "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbb0001",
};

const CONVERSATION_ID = "33333333-3333-4333-8333-333333333333";
const APPROVAL_ID = "44444444-4444-4444-8444-444444444444";
const TICKET_ID = "55555555-5555-4555-8555-555555555555";

test("staff can take over, approve, reply, and resolve", async ({ page }) => {
  let assigned = false;
  let resolved = false;
  const messages: Array<Record<string, unknown>> = [
    {
      id: "66666666-6666-4666-8666-666666666666",
      role: "customer",
      author_type: "customer",
      content: "Can you change the delivery address?",
      created_at: "2026-10-01T18:00:00Z",
      citations: [],
      tool_activity: [],
      approvals: [],
    },
    {
      id: "66666666-6666-4666-8666-666666666667",
      role: "assistant",
      author_type: "model",
      content: "Here is the delivery address change I can make. Please review and confirm.",
      created_at: "2026-10-01T18:01:00Z",
      citations: [],
      tool_activity: [],
      approvals: [
        {
          id: APPROVAL_ID,
          action_type: "update_shipping_address",
          status: "pending",
          proposed_change: {
            kind: "address",
            order_number: "ORD-10482",
            current: {
              recipient: "Ava Chen",
              line1: "18 Market Street",
              city: "Austin",
              region: "TX",
              postal_code: "78701",
              country: "US",
            },
            proposed: {
              recipient: "Ava Chen",
              line1: "42 Congress Avenue",
              city: "Austin",
              region: "TX",
              postal_code: "78701",
              country: "US",
            },
          },
          requested_at: "2026-10-01T18:01:00Z",
          expires_at: "2099-10-01T18:16:00Z",
          approved_at: null,
          approved_by: null,
        },
      ],
    },
  ];

  await page.route("**/api/**", async (route) => {
    const url = new URL(route.request().url());
    const path = url.pathname.replace(/^\/api/, "");
    const method = route.request().method();
    const conversation = {
      id: CONVERSATION_ID,
      customer_id: "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaa0001",
      customer_display_name: "Ava Chen",
      channel: "web",
      status: resolved ? "resolved" : "escalated",
      assigned_to: assigned ? STAFF.agent_id : null,
      assignee_name: assigned ? STAFF.label : null,
      ticket_id: TICKET_ID,
      ticket_priority: "high",
      pending_approval_count: messages.some((item) =>
        ((item.approvals as Array<{ status: string }>) ?? []).some((approval) => approval.status === "pending"),
      )
        ? 1
        : 0,
      preview: "Can you change the delivery address?",
      created_at: "2026-10-01T18:00:00Z",
      updated_at: "2026-10-01T18:04:00Z",
    };

    if (path === "/dev/staff" && method === "GET") {
      await route.fulfill({ json: { actors: [STAFF] } });
      return;
    }
    if (path === "/staff/inbox" && method === "GET") {
      await route.fulfill({
        json: {
          items: [conversation],
          next_cursor: null,
          counts: { all: 1, escalated: 1, waiting_approval: 0 },
        },
      });
      return;
    }
    if (path === `/staff/conversations/${CONVERSATION_ID}` && method === "GET") {
      await route.fulfill({ json: conversation });
      return;
    }
    if (path === `/staff/conversations/${CONVERSATION_ID}/messages` && method === "GET") {
      await route.fulfill({ json: { items: messages, next_cursor: null } });
      return;
    }
    if (path === `/staff/conversations/${CONVERSATION_ID}/trace` && method === "GET") {
      await route.fulfill({
        json: {
          items: [
            {
              id: "77777777-7777-4777-8777-777777777777",
              stop_reason: "completed",
              created_at: "2026-10-01T18:01:00Z",
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
              step_count: 1,
              step_limit: 8,
              tool_call_count: 1,
              tool_call_limit: 5,
              total_latency_ms: 320,
              stopped_by_limit: false,
            },
          ],
        },
      });
      return;
    }
    if (path === `/staff/conversations/${CONVERSATION_ID}/takeover` && method === "POST") {
      assigned = true;
      messages.push({
        id: "88888888-8888-4888-8888-888888888888",
        role: "system",
        author_type: "system",
        content: "Nora joined the conversation",
        created_at: "2026-10-01T18:05:00Z",
        citations: [],
        tool_activity: [],
        approvals: [],
      });
      await route.fulfill({ json: { ...conversation, assigned_to: STAFF.agent_id, assignee_name: STAFF.label } });
      return;
    }
    if (path.endsWith("/confirm") && method === "POST") {
      const approval = (messages[1].approvals as Array<Record<string, unknown>>)[0];
      approval.status = "consumed";
      approval.approved_by = STAFF.agent_id;
      approval.approved_at = "2026-10-01T18:06:00Z";
      await route.fulfill({ json: approval });
      return;
    }
    if (path === `/staff/conversations/${CONVERSATION_ID}/messages` && method === "POST") {
      const body = route.request().postDataJSON() as { content: string };
      messages.push({
        id: "99999999-9999-4999-8999-999999999999",
        role: "assistant",
        author_type: "support_agent",
        author_name: STAFF.label,
        content: body.content,
        created_at: "2026-10-01T18:07:00Z",
        citations: [],
        tool_activity: [],
        approvals: [],
      });
      await route.fulfill({
        status: 201,
        json: messages[messages.length - 1],
      });
      return;
    }
    if (path === `/staff/conversations/${CONVERSATION_ID}/resolve` && method === "POST") {
      resolved = true;
      messages.push({
        id: "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaa0009",
        role: "system",
        author_type: "system",
        content: "Conversation resolved",
        created_at: "2026-10-01T18:08:00Z",
        citations: [],
        tool_activity: [],
        approvals: [],
      });
      await route.fulfill({ json: { ...conversation, status: "resolved" } });
      return;
    }
    if (path === `/staff/tickets/${TICKET_ID}` && method === "GET") {
      await route.fulfill({
        json: {
          id: TICKET_ID,
          customer_display_name: "Ava Chen",
          priority: "high",
          category: "shipping",
          status: resolved ? "resolved" : "open",
          summary: "Need a person to look at ORD-10482",
          conversation_id: CONVERSATION_ID,
          assigned_to: assigned ? STAFF.agent_id : null,
          assignee_name: assigned ? STAFF.label : null,
          created_at: "2026-10-01T18:00:00Z",
          notes: [],
        },
      });
      return;
    }
    await route.fulfill({ status: 404, json: { code: "not_found", message: "missing" } });
  });

  await page.setViewportSize({ width: 1280, height: 800 });
  await page.goto("/agent/inbox");
  await expect(page.getByText("Development staff")).toBeVisible();
  await expect(page.getByRole("link", { name: /Ava Chen/ })).toBeVisible();
  await expect(page.getByText("With support team")).toBeVisible();
  await expect(page.getByText("High priority")).toBeVisible();

  await page.getByRole("link", { name: /Ava Chen/ }).click();
  await expect(page.getByRole("heading", { name: "Ava Chen" })).toBeVisible();
  await page.getByRole("button", { name: "Take over" }).click();
  await expect(page.getByText("Nora joined the conversation")).toBeVisible();

  await page.getByRole("tab", { name: "Trace" }).click();
  await expect(page.getByText("tool_denied")).toBeVisible();
  await expect(page.getByText("Tool call", { exact: true })).toBeVisible();
  await expect(page.getByText("320 ms", { exact: true })).toBeVisible();
  await page.getByRole("tab", { name: "Approvals" }).click();

  const details = page.getByRole("complementary", { name: "Details" });
  await details.getByRole("button", { name: "Approve as support agent" }).click();
  await expect(details.getByText(/Approved by Nora \(support\)/)).toBeVisible();

  await page.getByRole("textbox", { name: "Message" }).fill("I updated the address request.");
  await page.getByRole("button", { name: "Send message" }).click();
  await expect(page.getByRole("log", { name: "Conversation" }).getByText("I updated the address request.")).toBeVisible();
  await expect(page.getByRole("log", { name: "Conversation" }).getByText("· Support team")).toBeVisible();

  await page.getByRole("button", { name: "Resolve conversation", exact: true }).click();
  await page.getByRole("button", { name: "Resolve conversation", exact: true }).click();
  await expect(page.getByText("Conversation resolved")).toBeVisible();
  await expect(page.getByText("Resolved").first()).toBeVisible();

  await page.getByRole("tab", { name: "Ticket" }).click();
  await page.getByRole("link", { name: "Open ticket" }).click();
  await expect(page.getByRole("heading", { name: "Need a person to look at ORD-10482" })).toBeVisible();
  await expect(page.getByRole("link", { name: "Open conversation" })).toBeVisible();
  await expect(page.getByText("No notes yet.")).toBeVisible();
});

test("empty inbox explains that nothing is waiting", async ({ page }) => {
  await page.route("**/api/**", async (route) => {
    const path = new URL(route.request().url()).pathname.replace(/^\/api/, "");
    if (path === "/dev/staff") {
      await route.fulfill({ json: { actors: [STAFF] } });
      return;
    }
    if (path === "/staff/inbox") {
      await route.fulfill({
        json: { items: [], next_cursor: null, counts: { all: 0, escalated: 0, waiting_approval: 0 } },
      });
      return;
    }
    await route.fulfill({ status: 404, json: { code: "not_found", message: "missing" } });
  });

  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/agent/inbox");
  await expect(
    page.getByRole("navigation", { name: "Inbox" }).getByText(
      "Nothing is waiting. Escalated conversations and pending approvals will show up here.",
    ),
  ).toBeVisible();
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth > document.documentElement.clientWidth + 1);
  expect(overflow).toBe(false);
});

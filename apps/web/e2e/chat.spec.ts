import { expect, test } from "@playwright/test";

const ACTOR = {
  label: "Ava Chen",
  organization: "Harbor Goods",
  tenant_id: "11111111-1111-4111-8111-111111111111",
  customer_id: "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaa0001",
};

test("customer can start a chat, send a message, and see it after reload", async ({ page }) => {
  const conversations: Array<{
    id: string;
    customer_id: string;
    channel: string;
    status: string;
    created_at: string;
    updated_at: string;
    preview: string | null;
  }> = [];
  const messages = new Map<string, Array<Record<string, unknown>>>();

  await page.route("**/api/**", async (route) => {
    const url = new URL(route.request().url());
    const path = url.pathname.replace(/^\/api/, "");
    const method = route.request().method();

    if (path === "/dev/actors" && method === "GET") {
      await route.fulfill({ json: { actors: [ACTOR] } });
      return;
    }
    if (path === "/conversations" && method === "GET") {
      await route.fulfill({ json: { items: conversations, next_cursor: null } });
      return;
    }
    if (path === "/conversations" && method === "POST") {
      const id = "33333333-3333-4333-8333-333333333333";
      const now = new Date().toISOString();
      const conversation = {
        id,
        customer_id: ACTOR.customer_id,
        channel: "web",
        status: "open",
        created_at: now,
        updated_at: now,
        preview: null,
      };
      conversations.unshift(conversation);
      messages.set(id, []);
      await route.fulfill({ status: 201, json: conversation });
      return;
    }
    const transcript = path.match(/^\/conversations\/([^/]+)\/messages$/);
    if (transcript && method === "POST") {
      const id = transcript[1];
      const body = route.request().postDataJSON() as { content: string };
      const now = new Date().toISOString();
      const stored = messages.get(id) ?? [];
      stored.push({
        id: "44444444-4444-4444-8444-444444444444",
        role: "customer",
        content: body.content,
        created_at: now,
        citations: [],
        tool_activity: [],
      });
      stored.push({
        id: "55555555-5555-4555-8555-555555555555",
        role: "assistant",
        content: "Thanks, I saved your message. I have not looked up an order, delivery, return, or refund.",
        created_at: now,
        citations: [],
        tool_activity: [],
      });
      messages.set(id, stored);
      const conversation = conversations.find((item) => item.id === id);
      if (conversation) {
        conversation.preview = body.content;
        conversation.updated_at = now;
      }
      await route.fulfill({ status: 201, json: stored[0] });
      return;
    }
    if (transcript && method === "GET") {
      await route.fulfill({
        json: { items: messages.get(transcript[1]) ?? [], next_cursor: null },
      });
      return;
    }
    const conversationPath = path.match(/^\/conversations\/([^/]+)$/);
    if (conversationPath && method === "GET") {
      const conversation = conversations.find((item) => item.id === conversationPath[1]);
      await route.fulfill({ json: conversation });
      return;
    }
    await route.fulfill({ status: 404, json: { code: "not_found", message: "Not found." } });
  });

  await page.goto("/chat");
  await expect(page.getByRole("heading", { name: "Ask a support question" })).toBeVisible();
  await page.getByRole("textbox", { name: "Message" }).fill("Where is my order?");
  await page.getByRole("button", { name: "Send message" }).click();
  await expect(page).toHaveURL(/\/chat\/33333333-3333-4333-8333-333333333333/);
  await expect(page.getByText("Automated", { exact: true })).toBeVisible();
  await expect(page.getByText("I have not looked up an order, delivery, return, or refund.")).toBeVisible();

  await page.reload();
  await expect(page).toHaveURL(/\/chat\/33333333-3333-4333-8333-333333333333/);
  await expect(page.getByText("I have not looked up an order, delivery, return, or refund.")).toBeVisible();
});

# Instructions

- Following Playwright test failed.
- Explain why, be concise, respect Playwright best practices.
- Provide a snippet of code with the fix, if possible.

# Test info

- Name: apps/web/e2e/chat.spec.ts >> customer can start a chat, send a message, and see it after reload
- Location: apps/web/e2e/chat.spec.ts:10:5

# Error details

```
Error: page.goto: Protocol error (Page.navigate): Cannot navigate to invalid URL
Call log:
  - navigating to "/chat", waiting until "load"

```

# Test source

```ts
  1   | import { expect, test } from "@playwright/test";
  2   | 
  3   | const ACTOR = {
  4   |   label: "Ava Chen",
  5   |   organization: "Harbor Goods",
  6   |   tenant_id: "11111111-1111-4111-8111-111111111111",
  7   |   customer_id: "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaa0001",
  8   | };
  9   | 
  10  | test("customer can start a chat, send a message, and see it after reload", async ({ page }) => {
  11  |   const conversations: Array<{
  12  |     id: string;
  13  |     customer_id: string;
  14  |     channel: string;
  15  |     status: string;
  16  |     created_at: string;
  17  |     updated_at: string;
  18  |     preview: string | null;
  19  |   }> = [];
  20  |   const messages = new Map<string, Array<Record<string, unknown>>>();
  21  | 
  22  |   await page.route("**/api/**", async (route) => {
  23  |     const url = new URL(route.request().url());
  24  |     const path = url.pathname.replace(/^\/api/, "");
  25  |     const method = route.request().method();
  26  | 
  27  |     if (path === "/dev/actors" && method === "GET") {
  28  |       await route.fulfill({ json: { actors: [ACTOR] } });
  29  |       return;
  30  |     }
  31  |     if (path === "/conversations" && method === "GET") {
  32  |       await route.fulfill({ json: { items: conversations, next_cursor: null } });
  33  |       return;
  34  |     }
  35  |     if (path === "/conversations" && method === "POST") {
  36  |       const id = "33333333-3333-4333-8333-333333333333";
  37  |       const now = new Date().toISOString();
  38  |       const conversation = {
  39  |         id,
  40  |         customer_id: ACTOR.customer_id,
  41  |         channel: "web",
  42  |         status: "open",
  43  |         created_at: now,
  44  |         updated_at: now,
  45  |         preview: null,
  46  |       };
  47  |       conversations.unshift(conversation);
  48  |       messages.set(id, []);
  49  |       await route.fulfill({ status: 201, json: conversation });
  50  |       return;
  51  |     }
  52  |     const transcript = path.match(/^\/conversations\/([^/]+)\/messages$/);
  53  |     if (transcript && method === "POST") {
  54  |       const id = transcript[1];
  55  |       const body = route.request().postDataJSON() as { content: string };
  56  |       const now = new Date().toISOString();
  57  |       const stored = messages.get(id) ?? [];
  58  |       stored.push({
  59  |         id: "44444444-4444-4444-8444-444444444444",
  60  |         role: "customer",
  61  |         content: body.content,
  62  |         created_at: now,
  63  |         citations: [],
  64  |         tool_activity: [],
  65  |       });
  66  |       stored.push({
  67  |         id: "55555555-5555-4555-8555-555555555555",
  68  |         role: "assistant",
  69  |         content: "Thanks, I saved your message. I have not looked up an order, delivery, return, or refund.",
  70  |         created_at: now,
  71  |         citations: [],
  72  |         tool_activity: [],
  73  |       });
  74  |       messages.set(id, stored);
  75  |       const conversation = conversations.find((item) => item.id === id);
  76  |       if (conversation) {
  77  |         conversation.preview = body.content;
  78  |         conversation.updated_at = now;
  79  |       }
  80  |       await route.fulfill({ status: 201, json: stored[0] });
  81  |       return;
  82  |     }
  83  |     if (transcript && method === "GET") {
  84  |       await route.fulfill({
  85  |         json: { items: messages.get(transcript[1]) ?? [], next_cursor: null },
  86  |       });
  87  |       return;
  88  |     }
  89  |     const conversationPath = path.match(/^\/conversations\/([^/]+)$/);
  90  |     if (conversationPath && method === "GET") {
  91  |       const conversation = conversations.find((item) => item.id === conversationPath[1]);
  92  |       await route.fulfill({ json: conversation });
  93  |       return;
  94  |     }
  95  |     await route.fulfill({ status: 404, json: { code: "not_found", message: "Not found." } });
  96  |   });
  97  | 
> 98  |   await page.goto("/chat");
      |              ^ Error: page.goto: Protocol error (Page.navigate): Cannot navigate to invalid URL
  99  |   await expect(page.getByRole("heading", { name: "Ask a support question" })).toBeVisible();
  100 |   await page.getByRole("textbox", { name: "Message" }).fill("Where is my order?");
  101 |   await page.getByRole("button", { name: "Send message" }).click();
  102 |   await expect(page).toHaveURL(/\/chat\/33333333-3333-4333-8333-333333333333/);
  103 |   await expect(page.getByText("Automated")).toBeVisible();
  104 |   await expect(page.getByText("I have not looked up an order")).toBeVisible();
  105 | 
  106 |   await page.reload();
  107 |   await expect(page).toHaveURL(/\/chat\/33333333-3333-4333-8333-333333333333/);
  108 |   await expect(page.getByText("I have not looked up an order")).toBeVisible();
  109 | });
  110 | 
```
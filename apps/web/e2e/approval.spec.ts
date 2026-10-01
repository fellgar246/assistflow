import { expect, test } from "@playwright/test";

const ACTOR = {
  label: "Ava Chen",
  organization: "Harbor Goods",
  tenant_id: "11111111-1111-4111-8111-111111111111",
  customer_id: "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaa0001",
};

const CONVERSATION = "33333333-3333-4333-8333-333333333333";
const ADDRESS_APPROVAL = "99999999-9999-4999-8999-999999999991";
const CANCEL_APPROVAL = "99999999-9999-4999-8999-999999999992";

test("customer can confirm or cancel an address change from the chat", async ({ page }) => {
  const approvals = new Map<string, Record<string, unknown>>([
    [ADDRESS_APPROVAL, addressApproval(ADDRESS_APPROVAL, "pending", "42 Congress Avenue")],
    [CANCEL_APPROVAL, addressApproval(CANCEL_APPROVAL, "pending", "90 Cedar Avenue")],
  ]);
  let confirmStarted: (() => void) | undefined;
  const confirmGate = new Promise<void>((resolve) => {
    confirmStarted = resolve;
  });
  let releaseConfirm: (() => void) | undefined;
  const confirmRelease = new Promise<void>((resolve) => {
    releaseConfirm = resolve;
  });

  await page.route("**/api/**", async (route) => {
    const url = new URL(route.request().url());
    const path = url.pathname.replace(/^\/api/, "");
    const method = route.request().method();

    if (path === "/dev/actors" && method === "GET") {
      await route.fulfill({ json: { actors: [ACTOR] } });
      return;
    }
    if (path === "/conversations" && method === "GET") {
      await route.fulfill({
        json: {
          items: [
            {
              id: CONVERSATION,
              customer_id: ACTOR.customer_id,
              channel: "web",
              status: statusFor(approvals),
              created_at: "2026-09-30T16:00:00Z",
              updated_at: "2026-09-30T16:00:00Z",
              preview: "Please change the delivery address for ORD-10482",
            },
          ],
          next_cursor: null,
        },
      });
      return;
    }
    if (path === `/conversations/${CONVERSATION}` && method === "GET") {
      await route.fulfill({
        json: {
          id: CONVERSATION,
          customer_id: ACTOR.customer_id,
          channel: "web",
          status: statusFor(approvals),
          created_at: "2026-09-30T16:00:00Z",
          updated_at: "2026-09-30T16:01:00Z",
          preview: "Please change the delivery address for ORD-10482",
        },
      });
      return;
    }
    if (path === `/conversations/${CONVERSATION}/messages` && method === "GET") {
      await route.fulfill({ json: { items: transcript(approvals), next_cursor: null } });
      return;
    }
    const decision = path.match(
      /^\/conversations\/[^/]+\/approvals\/([^/]+)\/(confirm|reject)$/,
    );
    if (decision && method === "POST") {
      const body = route.request().postData() ?? "";
      expect(body).not.toContain("line1");
      const [, approvalId, action] = decision;
      const current = approvals.get(approvalId);
      if (!current) {
        await route.fulfill({ status: 404, json: { code: "not_found", message: "Not found." } });
        return;
      }
      if (action === "confirm") {
        confirmStarted?.();
        await confirmRelease;
        current.status = "consumed";
        current.approved_at = "2026-09-30T16:05:00Z";
      } else {
        current.status = "rejected";
      }
      await route.fulfill({ json: current });
      return;
    }
    await route.fulfill({ status: 404, json: { code: "not_found", message: "Not found." } });
  });

  await page.goto("/chat");
  await page.getByRole("link", { name: /Please change the delivery address/ }).click();
  await expect(page).toHaveURL(new RegExp(`/chat/${CONVERSATION}`));
  await expect(page.getByText("18 Market Street").first()).toBeVisible();
  await expect(page.getByText("42 Congress Avenue")).toBeVisible();
  await expect(page.getByText("Confirm or cancel the pending change above, or keep chatting.")).toBeVisible();

  await page.getByRole("button", { name: "Confirm address change" }).first().click();
  await confirmGate;
  const confirming = page.getByRole("button", { name: "Confirming…" });
  await expect(confirming).toBeDisabled();
  await expect(page.getByRole("button", { name: "Cancel" }).first()).toBeDisabled();
  releaseConfirm?.();
  await expect(page.getByText(/Delivery address changed/)).toBeVisible();
  await expect(page.getByRole("button", { name: "Cancel" })).toHaveCount(1);
  await page.getByRole("button", { name: "Cancel" }).click();
  await expect(page.getByText("You cancelled this change. Nothing was updated.")).toBeVisible();
});

function statusFor(approvals: Map<string, Record<string, unknown>>): string {
  const pending = [...approvals.values()].some((item) => item.status === "pending");
  return pending ? "waiting_approval" : "open";
}

function transcript(approvals: Map<string, Record<string, unknown>>) {
  return [
    {
      id: "44444444-4444-4444-8444-444444444444",
      role: "customer",
      content: "Please change the delivery address for ORD-10482",
      created_at: "2026-09-30T16:00:00Z",
      citations: [],
      tool_activity: [],
      approvals: [],
    },
    {
      id: "55555555-5555-4555-8555-555555555555",
      role: "assistant",
      content:
        "Here is the delivery address change I can make for ORD-10482. Please review and confirm. Nothing has changed yet.",
      created_at: "2026-09-30T16:00:30Z",
      citations: [],
      tool_activity: [],
      approvals: [...approvals.values()],
    },
  ];
}

function addressApproval(id: string, status: string, line1: string): Record<string, unknown> {
  return {
    id,
    action_type: "update_shipping_address",
    status,
    proposed_change: {
      kind: "address",
      order_number: "ORD-10482",
      current: {
        recipient: "Ava Chen",
        line1: "18 Market Street",
        line2: "Apt 4",
        city: "Austin",
        region: "TX",
        postal_code: "78701",
        country: "US",
      },
      proposed: {
        recipient: "Ava Chen",
        line1,
        line2: null,
        city: "Austin",
        region: "TX",
        postal_code: "78701",
        country: "US",
      },
    },
    requested_at: "2026-09-30T16:00:00Z",
    expires_at: "2099-09-30T16:15:00Z",
    approved_at: null,
  };
}

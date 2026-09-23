import { expect, test } from "@playwright/test";

test("home page renders the local workspace", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "AssistFlow" })).toBeVisible();
  await expect(page.getByText("Customer support, running on this machine.")).toBeVisible();
});

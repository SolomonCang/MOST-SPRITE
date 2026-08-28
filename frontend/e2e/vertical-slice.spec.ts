import { expect, test, type Page } from "@playwright/test";

async function completeSequence(page: Page, mode: "POL_Q" | "NONPOL", target: string) {
  await page.goto("/observe");
  await expect(page.getByRole("heading", { name: "观测控制台" })).toBeVisible();
  await page.getByLabel("目标名称").fill(target);
  await page.getByTestId("mode-select").selectOption(mode);
  await expect(page.getByText("预检通过")).toBeVisible();
  await page.getByTestId("start-sequence").click();

  await expect(page.getByTestId("sequence-status")).toContainText("SUCCEEDED");
  await expect(page.getByTestId("sequence-progress")).toContainText("100%");
  const exposureCount = mode === "POL_Q" ? 4 : 1;
  for (let index = 1; index <= exposureCount; index += 1) {
    await expect(page.getByTestId(`exposure-${index}`)).toContainText("COMMITTED");
    await expect(page.getByTestId(`exposure-${index}`)).toContainText("L0");
  }

  await page.goto("/data");
  await expect(page.getByText("数据处理台", { exact: true }).first()).toBeVisible();
  await page.getByPlaceholder("搜索目标").fill(target);
  const sequence = page.getByRole("button", { name: new RegExp(target) });
  await expect(sequence).toBeVisible();
  await sequence.click();
  await expect(page.getByTestId("product-L3").first()).toBeVisible();
  await page.getByTestId("product-L3").first().click();
  await expect(page.getByTestId("lineage-view")).toContainText("L0");
  await expect(page.getByTestId("lineage-view")).toContainText("L3");
  await expect(page.getByTestId("qc-list")).not.toContainText("此产品没有独立 QC 记录");
  await expect(page.getByText("不可修改", { exact: true })).toBeVisible();
}

test.describe.serial("MOST-SPRITE simulation vertical slice", () => {
  test("system dashboard launches three independent workspaces", async ({ page }) => {
    await page.goto("/");
    await expect(page).toHaveURL(/\/admin$/);
    await expect(page.getByRole("heading", { name: "系统仪表盘" })).toBeVisible();
    const observation = page.getByRole("link", { name: /观测控制台/ });
    const engineering = page.getByRole("link", { name: /仪器工程台/ });
    const data = page.getByRole("link", { name: /数据处理台/ });
    await expect(observation).toHaveAttribute("href", "/observe");
    await expect(engineering).toHaveAttribute("href", "/engineering");
    await expect(data).toHaveAttribute("href", "/data");
    await expect(observation).toHaveAttribute("target", "_blank");
  });

  test("switches local accounts and signs out without a password", async ({ page }) => {
    await page.goto("/admin");
    await page.locator(".account-menu > summary").click();
    await page.getByRole("button", { name: /Local Observer/ }).click();
    await expect(page.locator(".system-account")).toContainText("观测人员");

    await page.locator(".account-menu > summary").click();
    await page.getByRole("button", { name: "退出登录" }).click();
    await expect(page.getByRole("heading", { name: "选择本机账户登录" })).toBeVisible();
    await expect(page.locator('input[type="password"]')).toHaveCount(0);

    await page.getByRole("button", { name: /Local Administrator/ }).click();
    await expect(page.getByRole("heading", { name: "系统仪表盘" })).toBeVisible();
  });

  test("persists Chinese/English and light/dark preferences", async ({ page }) => {
    await page.goto("/observe");
    await page.getByTestId("locale-en").click();
    await expect(page.getByRole("heading", { name: "Observation workspace" })).toBeVisible();
    await expect(page.locator("html")).toHaveAttribute("lang", "en-US");
    await page.reload();
    await expect(page.getByRole("heading", { name: "Observation workspace" })).toBeVisible();

    const themeBefore = await page.locator("html").getAttribute("data-theme");
    await page.getByTestId("theme-toggle").click();
    await expect(page.locator("html")).not.toHaveAttribute("data-theme", themeBefore ?? "");
    const themeAfter = await page.locator("html").getAttribute("data-theme");
    await page.reload();
    await expect(page.locator("html")).toHaveAttribute("data-theme", themeAfter ?? "light");
  });

  test("observer completes POL_Q and sees I/P/N1/N2 lineage", async ({ page }) => {
    const target = `E2E-POL-${Date.now()}`;
    await completeSequence(page, "POL_Q", target);
    await expect(page.getByText("P", { exact: true })).toBeVisible();
    await expect(page.getByText("N1", { exact: true })).toBeVisible();
    await expect(page.getByText("N2", { exact: true })).toBeVisible();
  });

  test("observer completes NONPOL and sees TARGET/SKY/ALPHA/I", async ({ page }) => {
    const target = `E2E-NONPOL-${Date.now()}`;
    await completeSequence(page, "NONPOL", target);
    await expect(page.getByText("TARGET", { exact: true })).toBeVisible();
    await expect(page.getByText("SKY", { exact: true })).toBeVisible();
    await expect(page.getByText("ALPHA", { exact: true })).toBeVisible();
    await expect(page.getByText("I", { exact: true })).toBeVisible();
  });
});

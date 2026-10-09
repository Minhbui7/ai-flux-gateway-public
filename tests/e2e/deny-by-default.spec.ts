import { expect, test } from "@playwright/test";

const portals = [
  { name: "customer", url: "http://localhost:5173/" },
  { name: "admin", url: "http://localhost:5174/admin/" },
];

for (const p of portals) {
  test(`${p.name} portal denies access when public config is absent`, async ({ page }) => {
    const requests: string[] = [];
    page.on("request", (r) => requests.push(r.url()));
    await page.goto(p.url);
    await expect(page.getByRole("heading", { name: "Portal not configured" })).toBeVisible();
    await expect(page.getByRole("button", { name: /sign in/i })).toHaveCount(0);
    await expect(page.getByRole("navigation", { name: "Primary" })).toHaveCount(0);
    expect(requests.some((u) => u.includes("/api/") || u.includes("login.microsoftonline.com"))).toBe(false);
    expect(await page.evaluate(() => localStorage.length + sessionStorage.length)).toBe(0);
  });

  test(`${p.name} portal not-configured screen is usable on mobile`, async ({ page }) => {
    await page.setViewportSize({ width: 360, height: 640 });
    await page.goto(p.url);
    await expect(page.getByRole("heading", { name: "Portal not configured" })).toBeVisible();
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth);
    expect(overflow).toBe(false);
  });
}
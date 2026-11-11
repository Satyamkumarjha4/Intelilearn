/**
 * The public landing page in a browser: what a visitor sees and can do, what the console puts on it, and that every number
 * on it is the API's.
 *
 * Why: the unit tests prove the sample quiz, the words and the endpoints; only a browser shows that the page really is
 * assembled from them: that the quiz can be played to its end with the keyboard-reachable buttons, that a testimonial a
 * staff member publishes appears for a visitor while a sample never does, that a price edited in the console is the price
 * on the page, and that no phone width scrolls sideways.
 *
 * Use cases:
 * - a visitor sees the header (Sign in, Start free), the headline and the hero button naming the free credits
 * - the sample Quick check runs to its result ("You got 3 of 3", the level, the pages) and Try again starts it over
 * - with nothing published the "Why Socra exists" note shows; a staff member adds a testimonial in the console, cannot
 *   publish it without consent, publishes it, and it shows on the page; a sample never shows
 * - the numbers on the plan cards and in the hero equal what /api/public/pricing says, and a price edited in the console
 *   changes "about N full lessons" on the page (and is put back)
 * - at 360, 390, 430 and 1440 px wide nothing scrolls sideways, and the plans are one column on a phone and two on a desktop
 * - someone who is signed in sees "Go to my lessons" in the header instead of Sign in and Start free
 * - the page carries nothing for the team (API docs, the admin, a system status)
 */
import { expect, test, type Browser, type Page } from "@playwright/test";

import { Api } from "../support/api";
import { E2E } from "../support/config";
import { Seed } from "../support/seed";

async function staffPage(browser: Browser): Promise<{ page: Page; api: Api }> {
  const page = await (await browser.newContext()).newPage();
  const api = new Api(page);
  expect((await api.call("POST", "/auth/login", { email: E2E.STAFF_EMAIL, password: E2E.STAFF_PASSWORD })).status).toBe(200);
  return { page, api };
}

/** Takes every testimonial away, so a spec starts from nothing published (and leaves nothing behind). */
async function clearTestimonials(api: Api): Promise<void> {
  const { body } = await api.call("GET", "/console/testimonials");
  for (const row of body.testimonials) await api.call("DELETE", `/console/testimonials/${row.id}`);
}

test("a visitor sees the header, the headline and the free credits", async ({ page, request }) => {
  const pricing = await (await request.get("/api/public/pricing")).json();

  await page.goto("/");

  await expect(page.getByRole("link", { name: "Sign in" })).toBeVisible();
  await expect(page.getByRole("banner").getByRole("link", { name: "Start free" })).toBeVisible();
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("Learn anything, starting from what you already know.");
  await expect(page.getByRole("link", { name: `Start with ${pricing.signup_credits} free credits` }).first()).toBeVisible();
});

test("the sample Quick check runs to its result and Try again starts it over", async ({ page }) => {
  await page.goto("/");
  const quiz = page.locator("#top");

  await quiz.getByRole("button", { name: "Hypotenuse" }).click();
  await expect(quiz.getByText(/^Right\. The hypotenuse sits across/)).toBeVisible();
  await expect(quiz.getByRole("button", { name: "Next question" })).toBeFocused();
  await quiz.getByRole("button", { name: "Next question" }).click();

  await quiz.getByRole("button", { name: "√3/2" }).click(); // sin 30° is 1/2
  await expect(quiz.getByText(/^Not quite\./)).toBeVisible();
  await quiz.getByRole("button", { name: "Next question" }).click();

  await quiz.getByRole("button", { name: "Tangent" }).click();
  await quiz.getByRole("button", { name: "See my lesson" }).click();

  await expect(quiz.getByText("You got 2 of 3")).toBeVisible();
  await expect(quiz.getByText("Your level: Proficient")).toBeVisible();
  await expect(quiz.getByRole("link", { name: "Get my real lesson" })).toHaveAttribute("href", "/auth?mode=register");

  await quiz.getByRole("button", { name: "Try again" }).click();
  await expect(quiz.getByText("1 of 3")).toBeVisible();
  await expect(quiz.getByText("You got")).toHaveCount(0);
});

test("the maker's note shows until a testimonial is published, and a sample never shows", async ({ browser, page }) => {
  const { page: staff, api } = await staffPage(browser);
  try {
    await clearTestimonials(api);
    Seed.sampleTestimonials();

    await page.goto("/");
    await expect(page.getByText("Why Socra exists")).toBeVisible();
    await expect(page.getByText("[Learner name]")).toHaveCount(0);

    await staff.goto("/console/testimonials");
    await expect(staff.getByText("Sample: never shown").first()).toBeVisible();
    await expect(staff.getByRole("button", { name: "Publish", exact: true }).first()).toBeDisabled(); // a sample cannot be published

    const quote = `The retake had new questions ${Date.now()}`;
    await staff.getByLabel("Name", { exact: true }).fill("Asha R.");
    await staff.getByLabel("Who they are").fill("Class 12 student");
    await staff.getByLabel("What they said").fill(quote);
    await staff.getByLabel("Stars (optional)").fill("5");
    await staff.getByRole("button", { name: "Add testimonial" }).click();
    await expect(staff.getByText("Added. It goes last.")).toBeVisible();

    const added = staff.getByRole("article", { name: "Testimonial from Asha R." });
    await expect(added.getByRole("button", { name: "Publish", exact: true })).toBeDisabled(); // no consent yet
    await expect(added.getByText("No permission confirmed")).toBeVisible();
    const row = (await api.call("GET", "/console/testimonials")).body.testimonials.find((t: { name: string }) => t.name === "Asha R.");
    const refused = await api.call("PATCH", `/console/testimonials/${row.id}`, { is_published: true });
    expect(refused.status).toBe(400);
    expect(refused.body.fields.is_published[0]).toMatch(/agreed to be quoted/);

    await added.getByRole("button", { name: "Edit" }).click();
    await added.getByLabel("The learner agreed to be quoted on the landing page").check();
    await added.getByRole("button", { name: "Save changes" }).click();
    await expect(added.getByRole("button", { name: "Publish", exact: true })).toBeEnabled();
    await added.getByRole("button", { name: "Publish", exact: true }).click();
    await expect(staff.getByText(/Published\. It shows on the landing page now\./)).toBeVisible();

    await page.goto("/");
    await expect(page.getByRole("heading", { name: "What learners say" })).toBeVisible();
    await expect(page.getByText(quote)).toBeVisible();
    await expect(page.getByRole("img", { name: "5 out of 5 stars", exact: true })).toBeVisible();
    await expect(page.getByText("Why Socra exists")).toHaveCount(0);
    await expect(page.getByText("[Learner name]")).toHaveCount(0);
  } finally {
    await clearTestimonials(api);
  }
});

test("the page's numbers are the API's, and a price edited in the console changes them", async ({ browser, page, request }) => {
  const pricing = await (await request.get("/api/public/pricing")).json();
  await page.goto("/");

  const monthly = pricing.plans.find((plan: { key: string }) => plan.key === "monthly_pro");
  const card = page.getByRole("article", { name: "Monthly Pro" });
  await expect(card).toContainText(`₹${monthly.price_paise / 100}`);
  await expect(card).toContainText(`${monthly.credits} credits`);
  await expect(card).toContainText(`About ${monthly.about_lessons} full lessons`);
  await expect(page.getByRole("article", { name: "Free" })).toContainText(`${pricing.signup_credits} credits`);

  const { api } = await staffPage(browser);
  const live = async () => (await api.call("GET", "/console/credits")).body.prices.find((price: { key: string }) => price.key === "lesson.full").credits;
  const before = await live();
  try {
    expect((await api.call("PATCH", "/console/credits/prices/lesson.full", { credits: before + 5 })).status).toBe(200);
    const edited = await (await request.get("/api/public/pricing")).json();
    expect(edited.lesson_credits).toBe(before + 5);

    await page.reload();
    const expected = Math.floor(monthly.credits / (before + 5));
    await expect(card).toContainText(`About ${expected} full lessons`);
    await expect(page.getByText("Full lesson with its Test", { exact: true }).locator("xpath=..")).toContainText(String(before + 5));
  } finally {
    await api.call("PATCH", "/console/credits/prices/lesson.full", { credits: before });
  }
});

test("at 360, 390, 430 and 1440px nothing scrolls sideways and the plans are laid out as designed", async ({ page }) => {
  await page.goto("/");

  for (const width of [360, 390, 430, 1440]) {
    await page.setViewportSize({ width, height: 900 }); // one page resized, not a browser started for each width
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
    expect(overflow, `at ${width}px`).toBeLessThanOrEqual(0);
    const columns = await page.locator("#pricing ul.grid").first().evaluate((grid) => getComputedStyle(grid).gridTemplateColumns.split(" ").length);
    expect(columns, `at ${width}px`).toBe(width <= 680 ? 1 : 2);
  }
});

test("someone signed in sees Go to my lessons instead of Sign in and Start free", async ({ page }) => {
  await new Api(page).signUp(E2E.email("landing"), E2E.PASSWORD);

  await page.goto("/");

  await expect(page).toHaveURL(/\/$/);
  await expect(page.getByRole("banner").getByRole("link", { name: "Go to my lessons" })).toBeVisible();
  await expect(page.getByRole("link", { name: "Sign in" })).toHaveCount(0);
  await expect(page.getByRole("banner").getByRole("link", { name: "Start free" })).toHaveCount(0);
  await expect(page.getByRole("article", { name: "Monthly Pro" }).getByRole("link", { name: "Choose Monthly Pro" })).toHaveAttribute("href", "/buy");
});

test("the page carries nothing for the team", async ({ page, request }) => {
  const html = await (await request.get("/")).text();
  expect(html).not.toMatch(/api\/docs|\/admin|System status/i);
  await page.goto("/lessons");
  await expect(page).toHaveURL(/\/auth\?next=%2Flessons/); // signed out: asked to sign in, and told where to go after
});

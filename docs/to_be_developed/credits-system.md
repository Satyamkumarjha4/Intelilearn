# Feature Spec: Credits System

**Product:** Socra
**Status:** Finalized design, planned in [credits-implementation-plan.md](credits-implementation-plan.md) (open items in §12)
**Last updated:** 2026-11-03
**Related:** [modular-lessons.md](../architecture/modular-lessons.md), [the Phase 9 plan](../archive/modular-lessons-implementation-plan.md) (§5.5 and §6.7 are the `ActionGate` this feature plugs into; D19 is Stop, failure and Retry)

---

## Changelog

Amendment of 2026-11-03: the decisions confirmed by the product owner, and the spending section brought in line with what Phase 9 built. Docs only; nothing else in `docs/` was changed in this pass.

| # | Change | Sections |
|---|---|---|
| A1 | **Plan prices confirmed.** Monthly Pro is ₹199 for 500 credits and Pro Plus is ₹279 for 750 credits, both valid 28 days. The "proposed" asterisk is gone | 5.1, 12 |
| A2 | **Streak repair rule decided.** A repair fixes the **previous day only**, within 48 hours: a missed local day *D* can be repaired during local day *D + 1* and not after. The limits stay (1 per week, 3 per 28 days), and a repaired day earns no daily credit | 4.4, 12 |
| A3 | **Signup credits never expire.** The proposed 90 days is dropped. Bonus credits keep 90 days. Because a credit that never expires is spent last, it is the learner's long-lived reserve | 4.1, 6, 7, 12 |
| A4 | **"Create a lesson for this"** (from the result of a topic quick quiz) **costs 9** (first written as 10; **corrected in A12**). The level is already known, so there is no quick check and the whole lesson is one charge | 2.3 |
| A5 | **Spending brought in line with Phase 9.** Names follow the product copy ("Test", "retake", "Quick check", "Quick quiz"). The lesson test is 10 questions; a retake costs 2; a perfect quick check costs 3 + 7 (Expert lesson) or 3 + 2 (sheets only); follow-ups cost Foundation 5 and Advanced 7; a recommended lesson costs 9; quick quiz tiers are 5 questions = 1, 10 to 15 = 2, 20 to 30 = 3 with +1 (not stacking) for a quiz made from lessons or one with the warm-up; sheets cost 2 each with +1 once when grounded in a lesson or a quick check; a sheet is never regenerated | 2.1, 2.2, 2.3 |
| A6 | **Completion points, Stop, failure and Retry** follow D19 of the Phase 9 plan. An action is held when it starts and committed at its completion point (a table is added). Stop and a backend failure release the hold. **Retry asks again as a resume**, so it is never charged twice and may be refused. A pause (the Basics check, the warm-up) is not a settlement | 2.1, 3 |
| A7 | **Refusal is HTTP `402` with code `insufficient_credits`**, raised before any row exists. A refused quick check keeps the learner's answers in the browser so they can be sent again after topping up | 2.4 |
| A8 | **Quick quiz rules Phase 9 built are written in.** Counts are the presets 5, 10, 15, 20, 25, 30. Short and long answers need 10 or more questions. The batch size default is 5 (admin range 5 to 10). The per-batch cap of **1 long and 2 short** answers is adopted, and its open item is closed | 2.2, 12 |
| A9 | **The data-model sketch uses the real action keys** (`lesson.create`, `lesson.continue`, `lesson.followup`, `test.retake`, `quiz.create`, `quiz.retake`, `sheet.generate`, plus the ones that do not go through the gate). The sketch is superseded by the implementation plan where they differ | 11 |
| A10 | **Open items closed** (stage-1 charge of 3, the two plan prices, the long/short cap, the repair window, signup expiry). **One stays open** (expiry warnings for bonus and purchased credits). **New open items** found while checking the code and the Phase 9 pricing seam are listed with the questions put to the product owner | 12 |
| A11 | **Payments are provider-neutral.** The buy page and the ledger do not know a provider; each is an adapter. Stripe (test mode) is built first, Razorpay second. Google Pay, UPI and cards are payment *methods* inside a gateway, not gateways | 5.4, 11 |

Answers of 2026-11-03 to the open questions (second pass):

| # | Change | Sections |
|---|---|---|
| A12 | **Correction: "Create a lesson for this" is 9, not 10** (A4 and the pricing matrix) | 2.3 |
| A13 | **Quick quiz retake** costs the tier price, plus 1 only for a quiz made from lessons. The warm-up is not repeated, so it adds nothing | 2.2, 2.3 |
| A14 | **Sheets-only lessons: the +1 for a sheet "with a quiz first" *is* the quiz, so it is never charged on top of one.** Totals the learner sees: Quick check with one sheet **3** (3 now, 0 later), with both sheets **5** (3 + 2) (**for any score: the perfect-check part of this row is replaced by A26**); self-rated or from a quiz result **2 per sheet** (2 or 4), all at the start. A sheet added later to a sheets-only lesson from a Quick check is 2 (its quiz is already paid for). The +1 stays for a sheet grounded in a lesson's pages | 2.3 |
| A15 | **Recommended lesson:** the 1-credit discount is taken at stage one on the Quick check path (2 instead of 3, total 9). A self-rated recommended lesson is 9. **No discount on a sheets-only lesson** | 2.3 |
| A16 | **Day boundary:** `Profile.timezone` (an IANA name) is taken from the browser at sign-up, can be changed by the learner **once per 30 days**, and defaults to `Asia/Kolkata` for an account with none | 4.2 |
| A17 | **Existing accounts** each get the 30 non-expiring signup credits once, before credits are switched on | 4.1 |
| A18 | **Staff and admin accounts** are charged like anyone unless an explicit `credits_exempt` flag is set on the account (admin only). An exempt account's actions still leave ledger rows, at 0 | 9, 11 |
| A19 | **`retakes_per_day` is retired** as a product rule (credits are the limit). The hourly throttles and the one-open-attempt rule stay as abuse guards | 1 |
| A20 | **Gateways:** Stripe is the default, set from the environment. The buy page shows a gateway picker **only when two or more gateways are enabled**. The API accepts an optional `gateway`, checked against the enabled list | 5.4 |
| A21 | **Refunds and chargebacks:** refunds are made by an admin through the provider. A verified refund or dispute takes back only the **unspent** credits of that purchase, never takes a wallet below 0, and logs any shortfall | 5.5, 10 |
| A22 | **Sign-in methods are their own phase,** right after the credits core, and **public launch is blocked on it.** The signup grant is given on an "account ready" event: registration today, a verified email later | 4.1, 12 |
| A23 | **Expiry warnings:** bonus credits in their last 7 days; purchased credits at 30 days left and again in the last 7. In-app only until email exists | 7, 12 |
| A24 | **Tax:** ₹ prices are tax-inclusive and the provider's receipt is the invoice for now. GST registration and invoicing are decided before launch | 5.6, 12 |
| A25 | **Technical choices accepted:** a `Wallet` row per user as the lock anchor; repair limits counted over rolling 7 and 28 day windows; a release returns credits to their source buckets, or to a `refund` bucket when the source has expired; a stateless `POST /credits/quote`; a Celery beat service; `ActionRefused` for credits is HTTP 402 and the frontend handler follows | 11 |
| A26 | **Sheets-only lessons are priced by the number of sheets, whatever the score.** A Quick check with one sheet is **3** in total (3 + 0) and with both sheets **5** (3 + 2), for any score, perfect or not. The half-price rule of §2.1, and its "half your credits back" message, apply **only to the mastery choice of a lesson** (a perfect Quick check that chose the cheat sheet and the revision sheet instead of an Expert lesson). This replaces the perfect-check part of A14 | 2.1, 2.3 |
| A27 | **Confirmed:** the streak keeps counting past day 28, with +10 at every multiple of 7 and a further +10 at every multiple of 28, each paid once per run; and a sheet added later to a sheets-only lesson that started from a Quick check costs 2 | 2.3, 4.3 |
| A28 | **A blank attempt is not activity** (decided in the Phase 10.0 brief). An attempt with every answer blank, or a Quick check of only "I don't know", is stored as before but never reported to the activity sink, so it earns no daily credit and no streak day. Any attempt with at least one real answer counts, at the instant it is handed in. Spec §4.2 says so | 4.2 |

---

## 1. Overview

Every generating action in Socra costs credits.

- Users **earn** free credits by signing up and staying active (daily activity, weekly and monthly streaks).
- Users **buy** credits as one-time top-ups or prepaid plans.

All credits live in a wallet made of **buckets with expiry dates**. Every change to a wallet is recorded in an append-only **ledger**.

Design principles:

- **Credits only.** There are no daily usage limits. (The Phase 9 guard of 3 retakes a day per lesson or quiz is retired. Hourly rate limits and "one open attempt at a time" stay, as protection against abuse, not as a product rule.)
- **Users never pay for our failures.** Backend generation failures are refunded automatically.
- **Prices live in the database, not the code.** Admins can edit them.
- **Everything is prepaid.** No auto-renewal, no upgrades or downgrades.
- **No model tiers for now.** If tiers come later, the system will be extended then.

---

## 2. Spending Credits

### 2.1 Full lesson: 10 credits

The 10 credits break down as follows (shown to users in a "What's in your 10 credits" tooltip):

| Part | Credits | Reasoning |
|---|---|---|
| Level check (Quick check or self-rating) | 1 | Same as a 5-question quiz |
| Lesson (3 pages × 2) | 6 | 1 page = 1 sheet = 2 credits |
| Test (10 questions, lesson-based) | 3 | Same as a 10-question lesson-based quiz |
| **Total** | **10** | |

A lesson's **first** Test (attempt 1) is part of the lesson and costs nothing extra. Every retake costs credits (§2.3).

#### Staged charging (Quick check path)

| Stage | Charged | Running total | Held when | Committed when |
|---|---|---|---|---|
| User starts the lesson; the Quick check is generated (`lesson.create`) | 3 | 3 | the lesson is created | the Quick check is served |
| User completes the Quick check (`lesson.continue`) | 7 | 10 | the answers are handed in | the lesson is ready |

- If the user **abandons before completing the Quick check**, only the 3 credits are kept. They are committed as soon as the Quick check is served, even if it is never answered.
- Once the Quick check is handed in, the remaining 7 are held. They are committed when the lesson is **ready**, **even if the user never opens the lesson or takes the Test**.
- The Basics check (the prerequisite part of a Quick check) is a pause inside the second stage. It is not a settlement and costs nothing extra.
- If the lesson fails to build, or the user presses Stop, the held 7 are **released**. Retry asks for them again (§3).

#### Self-rating path

There is no Quick check stage. The full **10 credits** are held when lesson generation starts and committed when the lesson is ready.

#### Perfect Quick check (half-price path)

If the user scores **full marks on the Quick check**, they are offered a choice:

| Choice | Second-stage charge | Total paid |
|---|---|---|
| Continue with an Expert lesson | 7 | 10 |
| Cheat sheet + revision sheet only | 2 | **5** (half price) |

The half price is applied by charging less at stage two. No refund transaction is needed. In the UI it is presented as "You already know this. Here's half your credits back." This applies to this choice only; a learner who asked for study sheets from the start pays by the number of sheets (§2.3).

There is never a 100% refund.

### 2.2 Quick quiz

| Questions | Base | From existing lesson(s) or with the warm-up (calibration) |
|---|---|---|
| 5 | 1 | 2 |
| 10 – 15 | 2 | 3 |
| 20 – 30 | 3 | 4 |

- The question count is one of the presets **5, 10, 15, 20, 25, 30**.
- The +1 is charged **once**, even if both modifiers apply (it does not stack).
- **Short and long answers are only available for quizzes of 10 or more questions.** 5-question quizzes are restricted to MCQ, MSQ and numerical.
- Questions are generated in batches. The **batch size is configurable in admin** (default 5, range 5 to 10).
- **At most 1 long and 2 short answers per batch**, so a quiz cannot be all subjective by accident. The cap is off when the learner picked only short or long answers.
- Grading runs once, after all questions are answered (it is not batched), and is part of the quiz's price.
- A **retake** of a quick quiz generates a fresh set and costs the **tier price**, plus 1 only for a quiz made from lessons. The warm-up is not repeated (the quiz keeps its level), so it adds nothing.

### 2.3 Other actions

| Action | Credits |
|---|---|
| Retake of a lesson's Test (attempt 2 onward) | 2 |
| Quick quiz retake | the quiz's tier price (§2.2), +1 only for a quiz made from lessons |
| Cheat sheet (added to a ready lesson) | 2, +1 once when it is grounded in the lesson's pages |
| Revision sheet (added to a ready lesson) | 2, +1 once when it is grounded in the lesson's pages |
| Both sheets together | 2 + 2 + 1 (the +1 is charged once) |
| Foundation follow-up lesson | 5 (no quiz needed; level comes from the Test score) |
| Advanced follow-up lesson | 7 |
| Lesson picked from recommendations | 9 (10 − 1 discount, taken at stage one on the Quick check path: 2 + 7) |
| "Create a lesson for this" from a topic quick quiz | 9 (the level is already known, so there is no Quick check) |

- **Grounded** means the sheet is written from the pages of a ready lesson. The +1 for a sheet "with a quiz first" **is** the quiz, so it is never charged on top of one: a sheet added to a sheets-only lesson that started from a Quick check costs 2, because that Quick check is already paid for. A sheet written from the topic alone has no +1.
- The recommendation discount does **not** stack with follow-up pricing. A recommended Foundation lesson is still 5. It is not given on a sheets-only lesson.
- **Sheets cannot be regenerated.** Asking again for a sheet that exists is refused (`409`) and costs nothing.
- Retakes and other actions require enough credits. Socra **never absorbs costs**. If the user can't afford an action, it can't be generated.

#### Sheets-only lessons (study sheets asked for from a topic)

The learner sees the **total** before choosing.

| Way in | One sheet | Both sheets | Charged |
|---|---|---|---|
| Quick check, any score | **3** | **5** | 3 at the start, then 0 (one sheet) or 2 (both) when the answers are handed in |
| Self-rating | **2** | **4** | all at the start |
| From a quick quiz result | **2** | **4** | all at the start |

The score does not change a sheets-only price. The half-price rule of §2.1 belongs to the mastery choice of a lesson alone. Quick check "stage one" is 3 for every way of asking (2 for a recommended lesson, §2.3).

### 2.4 Insufficient credits

- Every action button shows its credit cost before the user clicks.
- If the balance is too low, show an "Inadequate credits" message and send the user to the **pricing / buy page**. The server answers **HTTP `402`, code `insufficient_credits`**.
- An action is never started and then failed midway for lack of credits. The full cost (or the stage cost) is checked up front, **before any row is created**. A Quick check handed in with too few credits for the second stage stores nothing, and the learner's answers stay in the browser so they can be sent again after topping up.

---

## 3. Generation Failures

| Failure type | Handling |
|---|---|
| **Frontend / network** (connection drop, timeout on the client) | Ask the user to **reload, not retry**. Reloading fetches the already-generated data. No refund, no second charge. |
| **Backend** (generation failed, incomplete or corrupt data) | **Full automatic refund** of the credits charged for that action. |
| **Stop** (the user cancels while the work runs) | The hold is released, as for a backend failure, if the action had not reached its completion point. |
| **Retry** (after a failure or a Stop) | Asks for the action again **as a resume**. The earlier hold was released, so the user is never charged twice, and the retry may be refused for lack of credits (the lesson stays failed and nothing is created). |

**Implementation requirements:**

- Generation must run **server-side, independent of the client connection** (a background job or task). A dropped client connection must not kill or duplicate the generation. This is what makes "reload" safe. (Built in Phase 9: every paid stage is a Celery task.)
- Charges use **hold → commit → release**:
  1. The stage cost is held when the action starts.
  2. It is committed when the action reaches its **completion point**.
  3. It is released on a backend failure or a Stop before that point.
- Every charge carries an **idempotency key**, so a reload or double-click never charges twice.

**Completion points** (where a hold is committed):

| Action | Committed when |
|---|---|
| `lesson.create`, Quick check path | the Quick check is served |
| `lesson.create`, self-rating or quiz-result path (the whole lesson) | the lesson is ready |
| `lesson.continue` | the lesson is ready |
| `lesson.followup` | the lesson is ready |
| `test.retake`, `quiz.create`, `quiz.retake` | the new attempt starts (its questions are ready) |
| `sheet.generate` | the sheet is saved |

Deleting a lesson or a quiz releases anything still held for it.

---

## 4. Earning Free Credits

### 4.1 Signup

- **30 credits** on registration. **They never expire.**
- The grant is given when the account is **ready**: at registration today, and when the email is verified once sign-in is built. Accounts that already exist get the 30 once, before credits are switched on.
- Sign-in methods (their own phase, right after the credits core; **public launch waits for it**):
  - Google
  - Apple
  - Microsoft
  - email + OTP verification
- Disposable email domains are blocked (use a public blocklist).

### 4.2 Daily activity: 1 credit per day

The user must perform **at least one meaningful action** that day. Visiting a page does not count. Qualifying actions:

- generating a lesson, quiz or sheet
- attempting or completing a test or quiz (including one generated earlier)

The action does **not** need to cost credits. For example, generating a lesson on day 1 and taking its included test on day 2 counts as two active days.

An attempt handed in with **every answer blank** (stored, scoring 0, as Phase 9's blank-attempt rule has it) is not an action: it does not count. For a Quick check, whose answers are an option or "I don't know", an attempt of only "I don't know" is the same. Otherwise a request that learns nothing would earn the day's credit.

The day boundary is the **user's local midnight**. The zone is `Profile.timezone`, an IANA name such as `Asia/Kolkata`, taken from the browser at sign-up. The learner can change it **once per 30 days** (so a changing zone cannot earn two days in one). An account with none uses `Asia/Kolkata`.

### 4.3 Streak bonuses

| Milestone | Bonus |
|---|---|
| Each completed 7-day streak (day 7, 14, 21, 28) | +10 (one free lesson) |
| Completed 28-day "month" (on day 28) | +10 extra |

So on day 28 the user receives 10 (week) + 10 (month) = 20. The streak keeps counting while it is unbroken: the weekly bonus is paid at every multiple of 7 and the monthly one at every multiple of 28, each once per run.

A **month is 28 days** throughout the system.

**Maximum free credits per 28-day cycle:** 28 (daily) + 40 (weekly) + 10 (monthly) = **78**, plus 30 at signup in the first cycle.

### 4.4 Streak repair

When a user misses a day, they can repair it for **1 credit**.

- A repair fixes **the previous day only**, within 48 hours: a missed local day *D* can be repaired during local day *D + 1*. After that the streak is broken for good.
- The repaired day **does not award** the daily credit.
- Limits:
  - **1 repair per week**
  - **3 repairs per 28-day month**
- These limits stop the "skip every other day and repair" loop.

---

## 5. Buying Credits

All purchases are **prepaid**. There is no auto-renewal.

### 5.1 Plans

| Plan | Credits | Validity | Price | ₹ / credit |
|---|---|---|---|---|
| One-time credits | any amount, **minimum 10** | 1 year | ₹1 per credit (min ₹10) | 1.00 |
| Weekly Pro | 100 per week | 1 week | ₹49 per week | 0.49 |
| Monthly Pro | 500 | 28 days | ₹199 | 0.40 |
| Pro Plus | 750 | 28 days | ₹279 | 0.37 |

- One-time credits have **no volume discount**. This is deliberate, to promote plans.
- One-time credits can be bought on top of any plan.

### 5.2 Buying multiple weeks

Buying several Weekly Pro plans at once **drips** the credits week by week. For example, 3 × ₹49 = ₹147 gives:

- Week 1: 100 credits, valid 1 week
- Week 2: 100 credits, valid 1 week
- Week 3: 100 credits, valid 1 week

Credits are never granted all at once.

### 5.3 Changing plans

- **No upgrades or downgrades.** Only one plan is active at a time.
- Buying a different plan while one is active **queues** it. It starts when the current cycle ends.
- Example: a user on Weekly Pro buys Monthly Pro. The monthly plan starts after the current week ends.

### 5.4 Payments

- Payments go through a **payment-gateway adapter**, so a provider can be added or swapped without touching the wallet. **Stripe in test mode** is built first, then **Razorpay**.
- The **default gateway is Stripe**, set from the environment. The buy page shows a gateway picker **only when two or more gateways are enabled**; with one, it shows none.
- Credits are granted only from a **verified provider event**, never from the browser's return to the site.
- Google Pay, UPI and cards are payment **methods** a gateway offers, not gateways.
- Before going live in India, re-check Stripe's onboarding status for Indian businesses and the RBI rules for card payments. Razorpay is the fallback.

### 5.5 Refunds and chargebacks

- There are **no self-service refunds.** An admin refunds through the provider.
- When a verified refund or dispute arrives, Socra takes back only the **unspent** credits of that purchase, in proportion to the amount refunded. A wallet is **never taken below 0**, and any shortfall (credits already spent) is logged for support.

### 5.6 Tax

₹ prices are **tax-inclusive**. The provider's receipt is the invoice for now. GST registration and invoicing are decided before launch.

---

## 6. Expiry & Spend Order

| Credit source | Expiry |
|---|---|
| Purchased (one-time) | 1 year from purchase |
| Subscription (weekly / monthly / Pro Plus) | End of that plan period |
| Bonus (daily, weekly streak, monthly streak) | 90 days from grant |
| Signup | **Never** |

**Spend order: earliest expiry first.** In practice this means subscription → bonus → purchased → signup, so the credits the user paid for directly last longest and the signup credits are the long-lived reserve.

---

## 7. Notifications

A notification area at the top of the page warns about expiring credits.

| Credit type | Warnings start |
|---|---|
| Weekly subscription | 2 days before expiry; repeats daily until the last day |
| Monthly / Pro Plus subscription | During the last 7 days of the period |
| Bonus | During the last 7 days |
| Purchased (one-time) | When 30 days are left, and again during the last 7 days |
| Signup | None: they never expire |

Example message: "This is your last day to use 40 credits."

Notices are shown **in the app** only, until email exists.

---

## 8. User-Facing Pages

- **Wallet:** current balance, broken down by bucket, with expiry dates.
- **Transaction history:**
  - credits used (by action)
  - credits bought
  - credits earned (signup, daily, streaks)
  - refunds
  - repairs
- **Pricing / buy page:** plans and one-time credits. This is also the target of the "inadequate credits" redirect.
- **Streak display:** current streak, repairs remaining this week and this month.

---

## 9. Admin

- **Edit prices** for every action. Prices are stored in an `ActionPrice` table; nothing is hardcoded.
- **Configure quiz generation batch size.**
- **Grant or revoke** credits manually for any user, with a required reason. This creates a ledger entry.
- **View any user's ledger** and wallet.
- **Mark an account `credits_exempt`** (staff doing their work, say). Nothing is exempt by default and `is_staff` does not exempt. An exempt account's actions still write ledger rows, at 0.
- **Refund a payment** (through the provider), which takes back the unspent credits of that purchase.
- **Revenue vs model cost** dashboard.

---

## 10. Legal

- **Terms & Conditions:**
  - credits are **non-refundable once used**
  - expiry rules
  - prepaid, no auto-renewal
  - the half-price perfect-Quick-check rule
  - refunds are made by an admin through the provider, and take back the unspent credits of that purchase
  - prices include tax
- **Privacy Policy:** cover the payment and usage data stored (the provider keeps card and bank details; Socra keeps order references, amounts and the ledger).

---

## 11. Proposed Data Model (sketch)

> This is a sketch. Where it differs from [the implementation plan](credits-implementation-plan.md), the plan wins.

```
Wallet              (one per user: the row every money movement locks, and the exempt flag)
  user, credits_exempt, created_at

CreditBucket
  user, source (signup | daily | weekly_streak | monthly_streak | purchase | subscription | admin_grant | refund)
  amount_granted, amount_remaining, expires_at (null = never), purchase (nullable), revoked_at, created_at

CreditTransaction   (append-only ledger)
  user, amount (+/-), type (grant | debit | hold | commit | release | refund | repair | admin_adjust | expire)
  action (nullable: lesson.create | lesson.continue | lesson.followup | test.retake | quiz.create | quiz.retake |
          sheet.generate | streak_repair | ...)
  related_object (generic FK), bucket_allocations (json), idempotency_key (unique), created_at

CreditHold
  user, amount, action, related_object, status (held | committed | released), expires_at

ActionPrice
  action_key, credits, active, updated_by, updated_at

Plan
  key (one_time | weekly_pro | monthly_pro | pro_plus), credits, period_days, price_inr

PlanPurchase
  user, plan, quantity, amount_paid, payment reference (provider-neutral), status

PlanPeriod          (one row per drip or period; supports queueing)
  user, plan_purchase, starts_at, ends_at, credits, bucket (FK), status (queued | active | ended)

StreakState
  user, current_streak, last_active_date (user-local), cycle_start_date
  (repairs used this week and this month are counted from the repaired days over rolling 7 and 28 day windows)
```

**Implementation notes:**

- **Wallet updates must be atomic.** Use `select_for_update` on the user's buckets inside a transaction.
- **Debits allocate across buckets** in earliest-expiry order. Record the allocation on the transaction so refunds return credits to the same buckets.
- **Run a scheduled job daily** that:
  - expires buckets
  - activates queued plan periods
  - drips weekly credits
  - evaluates streaks
  - sends expiry notifications

---

## 12. Open Items

**Closed in the 2026-11-03 amendments**

- [x] **Lesson stage-1 charge:** 3, with 7 at stage two (the code and the Phase 9 gate are built on it).
- [x] **Monthly Pro / Pro Plus prices:** ₹199 / ₹279 (A1).
- [x] **Short/long answer cap per batch:** 1 long + 2 short, built in Phase 9 (A8).
- [x] **Streak repair window:** the previous day only, within 48 hours (A2).
- [x] **Signup credit expiry:** never (A3).
- [x] **Expiry notifications for bonus and purchased credits:** bonus in the last 7 days; purchased at 30 days left and in the last 7; in-app only (A23).
- [x] **Prices the spec did not state:** quiz retake (A13), sheets-only lessons (A14), where the recommended discount lands (A15), "Create a lesson for this" (A12).
- [x] **Day boundary:** `Profile.timezone` (A16).
- [x] **Existing accounts:** 30 non-expiring credits once (A17).
- [x] **Staff and admin accounts:** an explicit `credits_exempt` flag (A18).
- [x] **`retakes_per_day`:** retired (A19).
- [x] **Default payment gateway and the picker** (A20).
- [x] **Refunds and chargebacks** (A21, §5.5).
- [x] **Sign-in methods:** their own phase, launch waits for it (A22).
- [x] **Tax:** inclusive; provider receipt for now (A24).

**Still open, and not blocking the build**

- [ ] **GST registration and invoicing:** decided before launch (A24).
- [ ] **Sign-in phase scope:** which of Google, Apple and Microsoft ship first, and the email provider for OTP (a plan of its own, after the credits core).

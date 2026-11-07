# Screens waiting for a design pass

Phase 9 (the Modular Lesson Parts, phases 9.2 to 9.7) built these screens from the plan and the existing components, because
the approved mockup ([socra-mockup.html](mockups/socra-mockup.html)) has none of them. They work, they use the design tokens,
the chunky buttons, `lucide-react` icons and the copy rules of [CLAUDE.md](../../CLAUDE.md), and they hold at 400px. What they
have not had is a designer's eye. This is the one list for a mockup session: add each screen to the mockup, get it approved,
then adjust the code. Nothing here blocks a release.

Phase 10 (credits and payments, [the plan](../archive/credits-implementation-plan.md)) adds section 7. Its time zone
field was built in phase 10.0 and the wallet, history, streak, notices, buy shell and cost labels in phase 10.5; the screens of
the later phases are listed here ahead of being built, each with the phase that builds it, so the designer sees the whole set
before the code does.

The order is the learner's: from asking for a lesson, to taking a test, to what follows it, to the quick quizzes. The code
for each is named so a change is easy to find. How each screen behaves is in [frontend.md](../reference/frontend.md).

## 1. Asking for something to learn

| Screen | Where | What needs a look |
|---|---|---|
| New lesson | `/lessons/new` (`app/lessons/new/page.tsx`, `ChoiceCards`) | Three questions on one screen: how to find the level (quick check or rate yourself), what to make (a lesson, or study sheets and which), and the topic. The radio-card groups are stacked one after the other; a long screen on a phone. Does it want steps? |
| Star rating | `StarRating` in the new-lesson form | Ten half-star values as a radio group, each with the approved sentence shown when it is chosen. Size of the stars, where the sentence sits, and the keyboard focus ring. |
| Journey stepper variants | `JourneyStepper` | "Rate yourself" replaces "Diagnose" for a self-rated lesson; a follow-up starts at "Your level"; a sheets-only lesson has its own three steps. Each variant is the same component with other labels, not a designed one |
| Starting-point card | `StartingPointCard` | For a self-rated lesson it shows the level and the stars and no per-question dots. The empty space where the dots were |

## 2. The lesson page

| Screen | Where | What needs a look |
|---|---|---|
| Tabs | `LessonTabBar` | Lesson, Test (with a badge: "To do", "Getting ready…", "In progress", "70% · attempt 2"), Study sheets, Quick check answers. A sheets-only lesson has two tabs. The badge wording and colour on a phone, where the tabs scroll |
| "Finish your test first" | `FinishTestFirst`, shown on the Lesson and Study sheets tabs while an attempt is open | A plain card with one button. It is the only thing on the tab, which looks empty |
| Lesson book opened at a page | `LessonViewer` with `?tab=lesson&page=core` | A learner arriving from "Study this" lands on the middle of the book with no sign of why. A line saying "You came here to study Halving the range" with the section heading would help; today only the page changes |
| Related lessons | `LessonHeader` | "Made from: …", "Foundation lesson: …", "Advanced lesson: …" links under the title. A list of links, not a designed block |
| Lesson list pills and kind lines | `LessonStatus`, the card on `/lessons` | "Test done · best 82%", "Foundation follow-up", "Study sheets", "Getting your lesson started". The pill vocabulary has grown; check the colours and the line lengths |

## 3. The test, its result and the tries after it

| Screen | Where | What needs a look |
|---|---|---|
| Question deck for every kind | `AttemptRunner`, `QuestionInput` | One card per question, forward only. Multiple select is a checkbox group ("choose all that apply"), numerical has a unit and a hint on rounding, short and long answers have a text box or the code editor. Only the multiple-choice card was designed |
| Getting a retake ready | `TestTabPanel`, `QuizBuilding` | "Getting your questions ready" with a **Cancel**. The same progress card as a lesson build, reused |
| Result | `TestResults`, `ScoreHero`, `QuestionBreakdown` | The score hero, the band, the per-question review with the solution, the criteria that earned marks on a written answer and an "AI-graded" tag. The breakdown is long for 10 questions on a phone |
| Tries and trend | `AttemptHistory` | The list of tries with the change against the previous one and the best, the time taken, and a small chart. The chart is the shared `chart-shapes` bars |
| Worth another look | `Revisit` in `TestResults` | Each topic with where it is taught, **Study this** and **Make a lesson on this**. Two buttons on one card |
| Try again | `TestResults` | A card with one marigold button. "Want a better score? Try again with new questions" |
| Code editor | `CodeEditor` (CodeMirror 6, in a dynamic import) | Light and dark themes, the "Press Esc then Tab to leave" hint, the language label, and its height on a phone. The dark theme was not checked against the page |

## 4. What follows a result

| Screen | Where | What needs a look |
|---|---|---|
| Follow-up dialog | `FollowupDialog` | One message, **Not now**, and the one button the server chose. Over a result that was just handed in |
| Follow-up card | `FollowupOfferCard` | The same message and button, kept under the score. Whether it should look different from the dialog |
| Quiet note for a low rater | `FollowupOfferCard` (no button) | "That one was a stretch…". Copy follows the spec: it never says the learner was wrong about themselves. Tone and weight |
| Mastery choice | `MasteryChoice` | After a perfect quick check: two options, "Continue with an Expert lesson" and "Cheat sheet + revision sheet only". The older three-sheet cards were removed in phase 9.8 |

## 5. Study sheets

| Screen | Where | What needs a look |
|---|---|---|
| Sheet tab row | `StudyMaterialView`, `SheetTabs`, `SheetRequests` | A chunky tab for each sheet the lesson has, a dashed "Add cheat sheet" / "Add revision sheet" for each it lacks, "Add both sheets" when it has neither, the PDF. The dashed tabs and the "both" button are new |
| Sheets building | `PipelineProgress` with the sheets' steps | The building screen for a sheets-only lesson and for sheets added to a ready lesson |

## 6. Quick quizzes

| Screen | Where | What needs a look |
|---|---|---|
| Quizzes list | `/quizzes` (`QuizCard`, `QuizList`) | Filter chips, cards with the kind line (topic or lessons), the number of questions and the best score, an empty state. A new list screen |
| New quiz wizard | `/quizzes/new` (`QuizWizard`) | Four steps: source (a topic, or up to 10 of the learner's lessons with a counter), how many questions, kinds of question (hidden when the count or the topic does not allow them), and the level (a self-rating, a warm-up, or your test scores). The lesson picker is a list of checkboxes; the level step re-uses the star rating |
| Warm-up | `CalibrationRunner` | Five multiple-choice questions, one at a time, no band shown and no way back. It re-uses the deck; it could be its own, lighter screen |
| Quiz building | `QuizBuilding` | "Making your quiz", the same progress card |
| Quiz page | `/quizzes/[id]` (`QuizTaker`, `QuizResult`) | The stage-driven page: header, the deck, and the result with the history. The result shows "Create a lesson for this" for a topic quiz, and for a quiz from lessons a card for each lesson with a row for each weak concept: its name, where it is taught, and a **Study this** (or **Open the lesson**) link; a deleted lesson is a plain note |
| Header link | `SiteHeader` | A "Quizzes" link beside "My lessons" |

## 7. Credits, the wallet and buying (Phase 10)

The approved mockup has none of these. Each is built from existing components and tokens in the phase named, and learners never
see the words hold, ledger, gateway, webhook, order state or settle ("credits" is fine). Copy for the cost labels is in
[the plan, section 5.5](../archive/credits-implementation-plan.md#55-what-the-learner-sees-stages-and-totals).

| Screen | Where | What needs a look |
|---|---|---|
| Time zone field | `/profile` (`TimezoneField` in `ProfileEditor`), built in 10.0 | A box that searches the zone names as you type (a native suggestion list today), with the note "Your day starts at midnight in this zone. You can change this once every 30 days." and, after a change, "You can change your time zone again on 5 December 2026." with the box shut. The suggestion list is the browser's own, and 400 names is a lot on a phone |
| Balance chip | Site header, linking to `/wallet` (built in 10.5: `BalanceChip`) | A ghost button with a coin and the number, beside "Quizzes", and a small marigold dot when some credits are about to run out. How it looks at 400px, where the header is already full; whether it should also say that some credits are being used for a lesson |
| Wallet | `/wallet` (built in 10.5: `app/wallet/page.tsx`) | The balance as a big number, "N credits being used for lessons being made", the notices, the credits grouped by kind and the day they run out (in the order they are used), and links to buy, the history and the streak. The grouped list is plain cards today; it wants a shape that makes "these 40 go first" obvious |
| History | `/wallet/history` (built in 10.5: `app/wallet/history/page.tsx`) | Rows grouped under Today, Yesterday and dated headings, each a plain sentence with the time and a signed change; "Show older" pages by cursor. The balance after each row is not shown. Filters and the empty state |
| Notices | A banner under the site header (`NoticesBanner`), and the top of `/wallet` (built in 10.5) | "This is your last day to use 40 credits." and its softer earlier forms, at most two at a time, each with a **Hide for today** cross. Marigold today; what it does to the page below it, and whether two is the right number |
| Streak | `/streak` (built in 10.5: `app/streak/page.tsx`, `StreakCalendar`) | The streak count with a flame, today's state, the last 28 days as a grid of seven (studied, repaired, missed, today), the next bonus, and **Repair yesterday** with the repairs left and a refusal shown in words. The grid, the repaired-day mark and today's dashed ring are new |
| Buy | `/buy` (shell in 10.5, live in 10.6: `app/buy/page.tsx`, `components/payments/`) | Credits by the amount (chips of 50, 100, 200 and 500 and a box, with the price in rupees as it changes), the plans as cards with a weeks stepper for Weekly Pro, the way-to-pay picker (shown only when two or more are on, as with Stripe and Razorpay both; today the same radio cards as the new-lesson form), and "Buying isn't open yet" when none is. Choosing Stripe leaves the site for Stripe's page; choosing Razorpay opens Razorpay's own window on top of the page (a card, UPI and net banking, theirs to style), and shutting it returns the learner to this page with the buttons back and nothing charged; a window that cannot open says "We couldn't open the payment window. Nothing was charged." The picker, the window's opening and the closed state are placeholders that want a designer's eye. The chips and the stepper are new; the whole page wants a designer's eye on how the plans compare, and on how a Pro Plus or monthly plan is shown beside credits |
| Back from paying | `/buy/return` (built in 10.6: `app/buy/return/page.tsx`) | A card that waits while the server confirms the payment (a spinner and "Confirming your payment"), says "Still confirming" calmly after two minutes, then "Your credits are here" with the new balance and **Carry on** back to where the learner came from, or a failed or timed-out state with **Try again**. No celebration until the server says so. It needs a proper success moment and a clearer failed state |
| Cost label | On every button that starts paid work (built in 10.5: `CostLabel`) | A marigold pill with a coin: "Costs 3 credits", or for a lesson from a Quick check "Costs 3 credits now, 7 after the Quick check · 10 credits in all" with the parts under it. On the new-lesson form, the mastery choice, the follow-up dialog and card, Try again on a test, Make a lesson on this, Create a lesson for this, the quiz wizard (live), quiz Try again, Add a sheet (one and both), and the Retry card. It turns red with a **Buy credits** link when there are too few; the button stays pressable. Where it sits beside each button, and whether the loading placeholder is needed |
| Not enough credits | A toast on any screen, and a card on the Quick check (built in 10.5; on coming back from buying, the Quick check shows the saved answers with a large **Send my answers**, in 10.6) | The toast says "Not enough credits" with a **Buy credits** action; the Quick check keeps its answers and shows "You need 7 credits for that and have 3 … Your answers are saved on this page" with **Get more credits** and **Send my answers**. Each screen still writes its own sentence (a toast or an alert); a single card shape would be better |
| Half-price message | The mastery choice (built in 10.5) | "You already know this. Here's half your credits back." sits under the cost of the two-sheets card, in success green. Tone and where it sits |
| Console: prices, plans, settings, wallets, payments (built in 10.9) | `/console/credits`, `/console/payments`, `/console/learners/{id}` and a revenue block on `/console/usage` | Staff screens in the console's existing style, built without a mockup: **Credits & prices** (the price table with a collapsed history per key, a card of fields per plan, the credit rules as a long list of number boxes, one save bar), **Payments** (tiles, filters, an order per row with its state pill and refunds, an inline refund form and a Mark-as-failed button, then the credits a refund could not take back), **a learner's wallet** (three tiles, live credits, the last ledger rows, a give-or-take form where the reason is required, the exempt switch) and the **revenue block** (paid, refunded, net and model cost in rupees with the dollar rate). They want a designer's eye on density, on how a long settings list is grouped, and on the refund form |

## 8. The staff console

| Screen | Where | What needs a look |
|---|---|---|
| Lesson settings, Quick quizzes section | `/console/settings` | Lessons in one quiz, the source token budget, the warm-up length, and the throttles. A section added to the existing page without a mockup, in the same style |
| Runs for quizzes | `/console/runs` | A run now belongs to a lesson or to a quiz: the lesson column, the "Open quiz" button and the filter. Quiz runs share the lesson layout |
| Usage by quiz | `/console/usage` | Model calls logged to a quiz show in the same table |

## 9. The mockup itself

The approved mockups still carry words the product retired. When the screens above are added, change these too:

- `socra-mockup.html`: "Final test" (the eyebrow of the test screen and the fourth step of two journeys), "test (one attempt)",
  and the comment "final test: mixed types, one attempt". The test can be taken again, with new questions; a Test is not "final".
- `socra-admin-mockup.html`: the "Final test questions" row of Lesson settings (the minimum and maximum were retired: the
  test is a fixed ten questions).
- Neither mockup has the names "Quick quiz" or "Basics check", or the lesson tabs.

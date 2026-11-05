# Screens waiting for a design pass

Phase 9 (the Modular Lesson Parts, phases 9.2 to 9.7) built these screens from the plan and the existing components, because
the approved mockup ([socra-mockup.html](mockups/socra-mockup.html)) has none of them. They work, they use the design tokens,
the chunky buttons, `lucide-react` icons and the copy rules of [CLAUDE.md](../../CLAUDE.md), and they hold at 400px. What they
have not had is a designer's eye. This is the one list for a mockup session: add each screen to the mockup, get it approved,
then adjust the code. Nothing here blocks a release.

Phase 10 (credits and payments, [the plan](../to_be_developed/credits-implementation-plan.md)) adds section 7. Only its
time zone field exists yet (built in phase 10.0); the other screens are listed here ahead of being built, each with the
phase that builds it, so the designer sees the whole set before the code does.

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
[the plan, section 5.5](../to_be_developed/credits-implementation-plan.md#55-what-the-learner-sees-stages-and-totals).

| Screen | Where | What needs a look |
|---|---|---|
| Time zone field | `/profile` (`TimezoneField` in `ProfileEditor`), built in 10.0 | A box that searches the zone names as you type (a native suggestion list today), with the note "Your day starts at midnight in this zone. You can change this once every 30 days." and, after a change, "You can change your time zone again on 5 December 2026." with the box shut. The suggestion list is the browser's own, and 400 names is a lot on a phone |
| Balance chip | Site header, linking to `/wallet` (10.5) | A small pill with the number of credits, beside "My lessons" and "Quizzes". How it looks at 400px, where the header already scrolls; whether it also shows that some credits are reserved for a lesson being made |
| Wallet | `/wallet` (10.5) | The balance, what is reserved for lessons being made, the credits grouped by when they run out, and a link to buy. The grouped list is a table of dates and amounts; it wants a shape that makes "these 40 go first" obvious |
| History | `/wallet/history` (10.5) | A long list of plain-language rows (what was earned, spent, given back, or ran out) with a date and the balance after. Filters and the empty state |
| Notices | A banner under the site header, and the top of `/wallet` (10.5) | "This is your last day to use 40 credits." and its softer earlier forms. Dismissable for the day. Colour role (marigold, "waiting for you") and what it does to the page below it |
| Streak | `/streak` (10.5) | The streak count, today's state, the last 28 days as a grid, what the next bonus is, and **Repair yesterday** with the repairs left. The grid and the repaired-day mark are new |
| Buy | `/buy` (10.5 shell, 10.6 live) | The plans and the one-time amount, the provider picker (shown only when two or more are enabled), the Buy button, and "Buying isn't open yet" when none is. The plan cards, the amount stepper and the price in rupees |
| Back from paying | `/buy/return` (10.6) | A waiting state while the server confirms the payment, then the new balance; a calm "still confirming" if it takes long, and a failed or cancelled state. No celebration is promised until the server says so |
| Cost label | On every button that starts paid work (10.5) | "3 credits" or a total such as "Quick check 3 + lesson 7" beside the New lesson, Take the test again, Make a lesson on this, quiz and sheet buttons. It updates as choices change |
| Not enough credits | The refusal card on the create screens, from 10.2 (the 402 path is ready in 10.0) | "You need 10 credits for that and have 4." with a **Buy credits** button. Today a refusal is a plain message |
| Half-price message | The mastery choice (10.5) | "You already know this. Here's half your credits back." Tone and where it sits |
| Console: prices, plans, settings, wallets, payments | `/console/credits` and a revenue block on `/console/usage` (10.9) | Staff screens in the console's existing style: the price table with its history, plan editor, the reward settings, a learner's wallet with grant and revoke (a reason is required), the payments list with refund |

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

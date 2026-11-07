# Legal and contact copy

The words of the `/privacy`, `/terms` and `/contact` pages live in the frontend, and **that is the only copy**:

| Page | Where the words are |
|---|---|
| `/privacy` | `frontend/content/legal/privacy.md` |
| `/terms` | `frontend/content/legal/terms.md` |
| `/contact` | `frontend/content/legal/contact.ts` (the one email address in the product, the five topics with their subject lines, the grievance officer) |

Edit those files. `LegalDocument` (`frontend/lib/legal-document.ts`) reads the markdown into a "last updated" date, an introduction, numbered sections and tables; see [frontend.md](../reference/frontend.md). The contact email is **satyamjha4@gmail.com** everywhere.

This folder used to hold a second, word-for-word copy of the two policies. It was removed so the two could not drift apart.

## Note for the owner

The texts are a careful, plain-language draft written for an Indian personal project, modelled on the Digital Personal Data Protection Act, 2023 (DPDP Act), the DPDP Rules, 2025, and the GDPR for EU visitors. They are not legal advice. Have a lawyer review them before Socra is offered to the public, especially the section on children and students.

## When you change them

- Change **Last updated** at the top of the file you edited (and the date `frontend/lib/legal-document.test.ts` expects).
- If the change matters to what people agreed to, change `User.TERMS_VERSION` (`backend/accounts/models.py`). New accounts record that version when they confirm the terms. Nothing asks existing accounts to confirm a newer version yet, and accounts made before the confirmation existed have none recorded.
- Keep the policy true to the code. One promise is not fully kept today: the Privacy page says that when you delete a lesson, its data is deleted. The lesson rows go, but its LangGraph checkpoints and model-call rows stay (see [data-model.md](../architecture/data-model.md#deleting-a-lesson) and the open work in [roadmap.md](../process/roadmap.md)). Fix the code, or soften the sentence, before the app is offered to the public.

# Socra: frontend

Next.js (App Router), managed with **bun**. Normally run through docker compose from the repo root. See [../docs/getting-started/local-setup.md](../docs/getting-started/local-setup.md) and [../docs/reference/frontend.md](../docs/reference/frontend.md).

```bash
bun install
bun run dev        # outside docker: needs DJANGO_API_ORIGIN (see .env.example)
bun run lint
bunx tsc --noEmit
```

`/api/*` is proxied to Django by the rewrite in `next.config.ts`.

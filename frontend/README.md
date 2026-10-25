# Socra: frontend

Next.js (App Router), managed with **bun**. Normally run through docker compose from the repo root. See [../docs/local-setup.md](../docs/local-setup.md) and [../docs/frontend.md](../docs/frontend.md).

```bash
bun install
bun run dev        # outside docker: needs DJANGO_API_ORIGIN (see .env.example)
bun run lint
bunx tsc --noEmit
```

`/api/*` is proxied to Django by the rewrite in `next.config.ts`.

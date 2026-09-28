# Local development image for the Next.js app.
FROM oven/bun:1.3

WORKDIR /app

COPY package.json bun.lock ./
RUN bun install --frozen-lockfile

COPY . .

ENV NEXT_TELEMETRY_DISABLED=1
EXPOSE 3000
CMD ["bun", "run", "dev", "--hostname", "0.0.0.0"]

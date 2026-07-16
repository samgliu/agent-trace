FROM mcr.microsoft.com/playwright:v1.57.0-noble

WORKDIR /app/e2e

RUN corepack enable

COPY package.json pnpm-lock.yaml* ./
RUN corepack pnpm install --frozen-lockfile

COPY playwright.config.ts ./
COPY tests ./tests

CMD ["corepack", "pnpm", "test:e2e"]

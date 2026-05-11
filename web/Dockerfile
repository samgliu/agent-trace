FROM node:24-slim

WORKDIR /app

RUN corepack enable

COPY package.json pnpm-lock.yaml* ./
RUN corepack pnpm install --frozen-lockfile

COPY index.html tsconfig.json vite.config.ts ./
COPY public ./public
COPY src ./src

RUN corepack pnpm test
RUN corepack pnpm build

EXPOSE 5173

CMD ["corepack", "pnpm", "dev"]

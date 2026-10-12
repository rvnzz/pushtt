FROM node:22-alpine

WORKDIR /app

# Зависимости (кэш слоя по package-lock)
COPY package.json package-lock.json ./
RUN npm ci

# Код
COPY tsconfig.json ./
COPY src ./src

EXPOSE 4000

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s \
  CMD node -e "fetch('http://127.0.0.1:' + (process.env.PORT || 4000) + '/health').then(r => process.exit(r.ok ? 0 : 1)).catch(() => process.exit(1))"

CMD ["npx", "tsx", "src/index.ts"]

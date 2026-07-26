FROM node:22-slim
WORKDIR /app
COPY package.json package-lock.json* ./
RUN npm install --omit=dev
COPY tsconfig.json ./
COPY src ./src
EXPOSE 8081
CMD ["npx", "tsx", "src/index.ts"]

# dashboard/Dockerfile — omega-dashboard (Vite dev server)
FROM node:20-slim

WORKDIR /app

COPY package.json package-lock.json* ./
RUN npm ci

COPY . .

EXPOSE 5173

# Vite dev server bound to 0.0.0.0 so it's reachable from the host
CMD ["npm", "run", "dev", "--", "--host", "0.0.0.0"]

# Official slim/alpine base image
FROM node:20-alpine

ENV NODE_ENV=production
WORKDIR /app

# Install dependencies first (better layer caching)
COPY package.json ./
RUN npm install --omit=dev && npm cache clean --force

# Copy source, owned by the unprivileged "node" user that ships with the image
COPY --chown=node:node . .

# Version shown in the page title/footer (1.0 by default, 1.1 for the rolling update)
ARG APP_VERSION=1.0
ENV APP_VERSION=${APP_VERSION}

USER node
EXPOSE 3000
CMD ["node", "server.js"]

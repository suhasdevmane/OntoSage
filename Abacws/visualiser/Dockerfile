# Build layer
FROM node:18-alpine AS node

COPY . /app
WORKDIR /app
RUN npm ci || npm i
# Purge any TypeScript sources to force a JS-only build
RUN find /app/src -type f \( -name "*.ts" -o -name "*.tsx" -o -name "*.d.ts" \) -exec rm -f {} + || true \
	&& rm -f /app/tsconfig.json || true
RUN npm run build
# Remove non-production node modules after build
RUN rm -rf node_modules
RUN npm i --only=prod

# Application layer
FROM nginx:alpine
ENV WEB_PORT=80
ENV API_HOST=api:5000

EXPOSE ${WEB_PORT}

# Copy frontend build
WORKDIR /app
COPY --from=node /app/build /app

# Copy NGINX config template
COPY nginx.conf.template /etc/nginx/templates/default.conf.template
FROM node:18-alpine

ENV PRODUCTION=true
ENV API_PORT=5000
ENV MONGODB_URI=mongodb://mongo:27017/abacws

EXPOSE ${API_PORT}

WORKDIR /api

COPY package*.json ./
RUN npm ci --only=production || npm i --only=production

COPY src ./src
COPY openapi.yaml ./

CMD [ "node", "src/app.js" ]
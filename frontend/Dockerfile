FROM node:22-alpine
WORKDIR /web
ARG NEXT_PUBLIC_API_URL=http://localhost:8100
ENV NEXT_PUBLIC_API_URL=$NEXT_PUBLIC_API_URL
COPY package*.json ./
RUN npm ci
COPY . .
RUN npx next build
CMD ["npx", "next", "start", "-p", "3210"]

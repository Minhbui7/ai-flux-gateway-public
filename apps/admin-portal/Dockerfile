# Build from the repository root: docker build -f apps/admin-portal/Dockerfile \
#   --build-arg VITE_ENTRA_CLIENT_ID=... --build-arg VITE_API_SCOPE=... --build-arg VITE_GATEWAY_URL=... .
FROM node:22-alpine AS build
WORKDIR /repo
COPY package.json package-lock.json tsconfig.base.json ./
COPY packages/ui packages/ui
COPY apps/admin-portal apps/admin-portal
RUN npm ci --workspaces --include-workspace-root
ARG VITE_ENTRA_CLIENT_ID
ARG VITE_ENTRA_AUTHORITY=https://login.microsoftonline.com/organizations
ARG VITE_API_SCOPE
ARG VITE_CONTROL_API_URL=/api
ARG VITE_GATEWAY_URL
RUN test -n "$VITE_ENTRA_CLIENT_ID" && test -n "$VITE_API_SCOPE" && test -n "$VITE_GATEWAY_URL" \
    || (echo "VITE_ENTRA_CLIENT_ID, VITE_API_SCOPE and VITE_GATEWAY_URL build args are required" && exit 1)
ENV VITE_ENTRA_CLIENT_ID=$VITE_ENTRA_CLIENT_ID VITE_ENTRA_AUTHORITY=$VITE_ENTRA_AUTHORITY VITE_API_SCOPE=$VITE_API_SCOPE \
    VITE_CONTROL_API_URL=$VITE_CONTROL_API_URL VITE_GATEWAY_URL=$VITE_GATEWAY_URL
RUN npm run build -w @aiflux/admin-portal

FROM nginxinc/nginx-unprivileged:1.27-alpine
LABEL com.azure.containerizationassist.createdby="containerization-assist"
WORKDIR /usr/share/nginx/html
# GATEWAY_ORIGIN (e.g. https://aiflux.example.com) and ENTRA_ORIGIN are substituted into the CSP at start.
ENV GATEWAY_ORIGIN="" CONTROL_ORIGIN=""
COPY apps/admin-portal/nginx.conf.template /etc/nginx/templates/default.conf.template
COPY --from=build /repo/apps/admin-portal/dist /usr/share/nginx/html/admin
EXPOSE 8080
USER 101
HEALTHCHECK CMD wget --spider -q http://127.0.0.1:8080/healthz || exit 1
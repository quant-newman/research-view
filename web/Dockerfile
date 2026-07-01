# 多阶段:Node 构建 React 静态包 → nginx 托管
FROM node:20-alpine AS build
WORKDIR /app
COPY package.json package-lock.json* ./
RUN npm install
COPY . .
RUN npm run build

FROM nginx:1.27-alpine
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html
# /usr/share/nginx/html/data 由 compose 挂载卷覆盖(阿里云每日同步 dashboard.json 进来)
EXPOSE 80

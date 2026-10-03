# JavaScript Filter / 中间件 清单

## 1. Express 中间件
- app.use(middleware)
- router.use(middleware)
- app.use((req, res, next) => ...)
- error-handling middleware (err, req, res, next)
- express.json() / express.urlencoded()

## 2. Koa 中间件
- app.use(async (ctx, next) => ...)
- koa-compose
- koa-body / koa-router middleware
- koa-session

## 3. NestJS 过滤与拦截
- NestMiddleware
- middleware consumer.apply(...)
- Guard (CanActivate)
- Interceptor (CallHandler)
- Pipe (transform)
- ExceptionFilter (catch)

## 4. Fastify 中间件
- addHook("onRequest"|"preParsing"|"preValidation"|"preHandler"|"preSerialization"|"onSend"|"onResponse"|"onError")
- addHook("onRoute")
- register(plugin, opts)

## 5. Hapi / AdonisJS / LoopBack
- Hapi: server.ext("onRequest"|"onPreAuth"|"onPostAuth"|"onPreHandler"|"onPostHandler"|"onPreResponse")
- Hapi: server.route options.pre
- AdonisJS: Server.middleware.register(...)
- AdonisJS: Route.middleware(...)
- LoopBack 4: middleware sequence / interceptors
- LoopBack 3: middleware.json / middleware.urlencoded

## 6. Next.js / Nuxt / Remix
- Next.js Middleware (middleware.ts)
- Next.js API Route handler wrapper
- Nuxt: server middleware (server/middleware)
- Nuxt: route rules / nitro plugins
- Remix: loader/action wrapper

## 7. GraphQL / RPC
- Apollo Server: plugins / context function
- graphql-middleware
- Yoga: plugins
- gRPC Node: ServerInterceptor / ServerCredentials wrapper

## 8. 老牌框架/自定义
- Restify: server.pre / server.use
- Restify: server.on("after")
- Restify: server.on("restifyError")
- Restify: plugins.acceptParser / plugins.queryParser / plugins.bodyParser
- Sails: policies / hooks
- Hapi v16: server.ext(...)
- 自定义中间件: function(req, res, next) { ... }

## 9. 安全漏洞相关中间件与防护
- Express: helmet
- Express: csurf
- Express: express-rate-limit
- Express: hpp
- Express: express-validator
- Express: xss-clean
- Koa: koa-helmet
- Koa: koa-csrf
- Koa: koa-ratelimit
- Koa: @koa/cors
- Fastify: @fastify/helmet
- Fastify: @fastify/csrf-protection
- Fastify: @fastify/rate-limit
- Fastify: @fastify/cors
- Hapi: @hapi/crumb
- Hapi: hapi-rate-limit

## 10. 漏洞类型对应中间件补充
- SQL 注入: express-validator / Joi 校验中间件
- 命令执行: 自定义 CommandGuard middleware
- 路径遍历: 自定义 PathGuard middleware
- SSRF: 自定义 UrlAllowlist middleware
- 反序列化: 自定义 DeserializeGuard middleware
- 模板注入: 自定义 TemplateGuard middleware
- 代码注入: 自定义 CodeGuard middleware
- 原型污染: hpp / qs 校验 / 自定义 merge-guard
- 不安全重定向: 自定义 RedirectGuard middleware
- XSS 输出: helmet / xss-clean / 自定义 output sanitizer
- 日志注入: 自定义 LogSanitizer middleware

## 11. 漏洞类型对应常见框架/库
- SQL 注入: Sequelize replacements / bind
- SQL 注入: Knex 参数化查询
- SQL 注入: Prisma 参数化 query
- SSRF: undici Dispatcher/Agent 白名单包装
- SSRF: axios 请求拦截器
- XXE: fast-xml-parser 安全选项
- XSS: DOMPurify / sanitize-html
- 原型污染: qs allowPrototypes 禁用
- 不安全重定向: Next.js middleware 重定向白名单

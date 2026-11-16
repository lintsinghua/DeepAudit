# JavaScript Interceptor 清单

## 1. Express / Koa
- Express: app.use / router.use
- Express: middleware (req, res, next)
- Koa: app.use(async (ctx, next) => ...)
- koa-compose

## 2. NestJS
- NestInterceptor (intercept)
- Guard (CanActivate)
- Pipe (transform)
- ExceptionFilter (catch)
- Middleware (NestMiddleware)

## 3. Fastify / Hapi
- Fastify: addHook("onRequest"|"preHandler"|"onSend"|"onResponse")
- Hapi: server.ext("onRequest"|"onPreHandler"|"onPreResponse")

## 4. Next.js / Remix / Nuxt
- Next.js Middleware (middleware.ts)
- Next.js API handler wrapper
- Remix: loader/action 包装
- Nuxt: server middleware / nitro plugins

## 5. GraphQL / RPC
- Apollo Server plugins
- graphql-middleware
- tRPC: middleware / procedures
- gRPC Node: interceptors

## 6. 旧框架/自定义
- Restify: server.pre / server.use
- Restify: server.on("after") / server.on("restifyError")
- Restify: plugins.acceptParser / plugins.queryParser / plugins.bodyParser
- Sails: policies
- LoopBack: interceptors
- 自定义拦截: function(req, res, next) { ... }
- Perl Mojolicious: app->hook(before_dispatch/after_dispatch)

## 7. 安全漏洞相关拦截与校验
- NestJS: AuthGuard / RolesGuard
- NestJS: ValidationPipe
- NestJS: ClassSerializerInterceptor
- Express: express-validator middleware
- Express: csurf middleware
- Express: express-rate-limit
- Koa: koa-validate
- Koa: koa-csrf
- Fastify: preValidation hook
- Fastify: @fastify/csrf-protection
- Hapi: @hapi/crumb

## 8. 漏洞类型对应拦截补充
- SQL 注入: knex raw 校验拦截 / prisma middleware
- SSRF: fetch/axios wrapper middleware
- XSS 输出: DOMPurify 前置拦截 / 自定义 sanitizer
- 原型污染: merge/assign 拦截中间件
- 不安全重定向: res.redirect 包装拦截

## 9. 漏洞类型对应常见框架/库
- SQL 注入: Sequelize beforeFind 钩子
- SQL 注入: Prisma middleware
- SQL 注入: TypeORM subscribers
- SSRF: undici Dispatcher/Agent 包装
- XXE: xml2js 安全配置
- XSS: sanitize-html
- 原型污染: lodash merge guard

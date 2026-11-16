# JavaScript 漏洞 Source 点清单

## 1. Web 请求参数（Express/Koa/Nest/Next）
- Express: req.query.xxx
- Express: req.params.xxx
- Express: req.body.xxx
- Express: req.headers["..."]
- Express: req.get("header")
- Express: req.cookies.xxx
- Koa: ctx.query.xxx
- Koa: ctx.params.xxx
- Koa: ctx.request.body
- Koa: ctx.headers["..."]
- NestJS: @Query() / @Param() / @Body()
- Next.js API: req.query / req.body
- Next.js Middleware: request.nextUrl.searchParams.get(...)
- Fastify: request.query / request.body / request.params
- Hapi: request.query / request.payload / request.params
- Sails: req.param(...)
- AdonisJS: request.input(...)
- LoopBack: req.params / ctx.args
- Remix: request.url / await request.json()
- Nuxt Server: event.node.req.url / await readBody(event)

## 2. 文件上传/多部件表单
- multer: req.file / req.files
- busboy: file stream / field value
- formidable: files / fields
- koa-body: ctx.request.files
- fastify-multipart: await req.file()
- hapi: request.payload.file

## 3. URL/路径相关输入
- req.originalUrl
- req.baseUrl
- req.path
- req.url
- new URL(req.url, base).searchParams.get(...)
- request.ip / req.ips
- req.hostname / req.protocol

## 4. 认证/会话/Token 输入
- req.session.xxx
- req.user / req.auth
- passport: req.user
- JWT: req.headers.authorization
- JWT: token payload claims
- express-session: req.session
- koa-session: ctx.session
- cookies: req.signedCookies / ctx.cookies.get(...)

## 5. GraphQL/RPC 输入
- GraphQL resolver args
- Apollo: context.req.headers
- gRPC: call.request.<field>
- JSON-RPC: params
- tRPC: ctx.input

## 6. 模板/表达式输入
- ejs: req.query / req.body 传入模板变量
- handlebars: 传入的模板上下文对象
- pug: locals 对象字段
- nunjucks: renderString 的 data 参数
- liquidjs: engine.parseAndRender(source, data)
- eta: render(source, data)

## 7. 浏览器端输入
- location.href / location.search
- URLSearchParams.get(...)
- document.cookie
- window.name
- localStorage.getItem(...)
- sessionStorage.getItem(...)
- postMessage event.data
- form input.value
- history.state
- navigator.userAgent

## 8. 消息队列/事件流输入
- KafkaJS: message.value
- amqplib: msg.content
- redis: message
- NATS: msg.data
- BullMQ: job.data
- KafkaJS: eachMessage.message.value

## 9. 数据库中不可信字段
- ORM 查询结果字段
- 外部同步数据源字段
- mongoose 文档字段
- sequelize 模型字段

## 10. 外部系统/配置输入
- process.env
- dotenv: process.env["..."]
- config.get("...")
- JSON.parse(fs.readFileSync(...))
- rc 配置文件读取
- nconf.get("...")

## 11. CLI/脚本输入
- process.argv
- yargs argv
- commander.opts()
- minimist(argv)
- zx: argv

## 12. 框架细分（NestJS / Fastify / Koa）
- NestJS: @Req() req / @Headers() headers / @Body() dto / @Query() query / @Param() param
- NestJS: ExecutionContext.switchToHttp().getRequest()
- NestJS: GraphQL @Args() / @Context() / @Req()
- Fastify: request.body / request.query / request.params / request.headers
- Fastify: request.cookies / request.ip / request.hostname
- Fastify: reply.request.body
- Koa: ctx.request.body / ctx.request.query / ctx.request.headers
- Koa: ctx.params / ctx.cookies.get(...)
- Koa: ctx.request.rawBody

## 13. 框架细分（Hapi / AdonisJS / LoopBack）
- Hapi: request.payload
- Hapi: request.query / request.params
- Hapi: request.headers / request.state
- AdonisJS: request.input(...)
- AdonisJS: request.all() / request.only(...)
- AdonisJS: request.qs() / request.params()
- LoopBack: ctx.args / req.params
- LoopBack: req.body / req.query

## 14. 其他老牌 Node/Web 框架
- Sails: req.param(...) / req.allParams()
- Express 早期: req.param(...)
- Restify: req.params / req.query / req.body
- Restify: req.header(...)
- Hapi v16: request.params / request.payload

# Python Filter / 中间件 清单

## 1. Django 中间件
- MIDDLEWARE 列表项
- django.utils.deprecation.MiddlewareMixin
- process_request(request)
- process_view(request, view_func, view_args, view_kwargs)
- process_template_response(request, response)
- process_response(request, response)
- process_exception(request, exception)

## 2. Django REST Framework
- DEFAULT_AUTHENTICATION_CLASSES
- DEFAULT_PERMISSION_CLASSES
- DEFAULT_THROTTLE_CLASSES
- DEFAULT_PARSER_CLASSES
- BaseAuthentication.authenticate(...)
- BasePermission.has_permission(...)
- BasePermission.has_object_permission(...)
- BaseThrottle.allow_request(...)

## 3. Flask 中间件
- @app.before_request
- @app.after_request
- @app.teardown_request
- @app.errorhandler
- werkzeug.middleware.* (ProxyFix, DispatcherMiddleware)
- wsgi_app / app.wsgi_app 包装

## 4. FastAPI / Starlette 中间件
- app.add_middleware(...)
- BaseHTTPMiddleware
- @app.middleware("http")
- Starlette Middleware 接口
- ExceptionMiddleware / CORSMiddleware / SessionMiddleware

## 5. Sanic / Aiohttp / Tornado
- Sanic: @app.middleware("request"|"response")
- Sanic: @app.on_request / @app.on_response
- aiohttp: @web.middleware
- aiohttp: app.middlewares.append(...)
- Tornado: RequestHandler.prepare()
- Tornado: RequestHandler.on_finish()
- Tornado: Application.add_transform(...)

## 6. Falcon / Pyramid / Bottle
- Falcon: middleware.process_request / process_response / process_resource
- Pyramid: tween_factory
- Pyramid: @subscriber(NewRequest)
- Bottle: app.add_hook("before_request"/"after_request")
- Bottle: @hook("before_request")

## 7. GraphQL / RPC 过滤
- Graphene: middleware (resolve)
- Ariadne: middleware / Extension
- Strawberry: extensions
- gRPC: ServerInterceptor
- Thrift: TProcessor / TServerEventHandler

## 8. Celery / RQ / 任务拦截
- Celery: task_prerun / task_postrun 信号
- Celery: Task.before_start / after_return
- RQ: job hooks (on_success/on_failure)

## 9. 老牌框架/自定义
- web.py: web.application.add_processor(...)
- web.py: web.webapi.handle()
- web.py: web.application.processors
- Pylons: pylons.config["pylons.response_options"]
- Pylons: pylons.wsgiapp.PylonsApp
- Pylons: pylons.middleware
- TurboGears: @before_validate / @before_call
- TurboGears: app_globals / request hooks
- 自定义 WSGI 中间件 (callable(environ, start_response))

## 10. 安全漏洞相关中间件与防护
- Django: django.middleware.security.SecurityMiddleware
- Django: django.middleware.csrf.CsrfViewMiddleware
- Django: django.middleware.clickjacking.XFrameOptionsMiddleware
- Flask: flask_wtf.csrf.CSRFProtect
- Flask: flask_talisman.Talisman
- Flask: flask_seasurf.SeaSurf
- Flask: flask_limiter.Limiter
- Starlette: TrustedHostMiddleware
- Starlette: HTTPSRedirectMiddleware
- Starlette: CORSMiddleware

## 11. 漏洞类型对应中间件补充
- SQL 注入: 自定义 SQLValidationMiddleware / connection.execute_wrapper
- 命令执行: 自定义 CommandValidationMiddleware
- 路径遍历: 自定义 PathSanitizerMiddleware
- SSRF: 自定义 UrlAllowlistMiddleware
- 反序列化: 自定义 DeserializationGuardMiddleware
- 模板注入: 自定义 TemplateSanitizerMiddleware
- 代码注入: 自定义 CodeExecutionGuardMiddleware
- 不安全重定向: 自定义 RedirectGuardMiddleware
- XSS 输出: 自定义 OutputSanitizerMiddleware
- 日志注入: 自定义 LogSanitizerMiddleware

## 12. 漏洞类型对应常见框架/库
- SQL 注入: Django ORM QuerySet 参数化
- SQL 注入: SQLAlchemy Query / text 绑定参数
- SQL 注入: Peewee Model.select().where(...)
- SSRF: requests.Session 请求白名单包装
- SSRF: aiohttp.ClientSession 自定义 TCPConnector 限制
- XXE: defusedxml 安全解析封装
- XSS: Bleach HTML 清洗中间件
- 反序列化: itsdangerous URLSafeSerializer
- 不安全重定向: Django allowed_hosts / RedirectFallbackMiddleware

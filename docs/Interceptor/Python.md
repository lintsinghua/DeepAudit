# Python Interceptor 清单

## 1. Django
- Middleware (process_request/process_view/process_response)
- View decorator (自定义装饰器)
- Signal: request_started / request_finished
- DRF: BaseAuthentication.authenticate(...)
- DRF: BasePermission.has_permission(...)
- DRF: BaseThrottle.allow_request(...)

## 2. Flask
- @app.before_request / after_request
- @app.teardown_request
- Blueprint.before_request / after_request
- Flask-Login: @login_required
- Flask-JWT-Extended: @jwt_required

## 3. FastAPI / Starlette
- @app.middleware("http")
- BaseHTTPMiddleware
- Dependency Injection (Depends)
- APIRoute.get_route_handler 自定义包装

## 4. Sanic / Aiohttp / Tornado
- Sanic: @app.middleware("request"|"response")
- aiohttp: @web.middleware
- Tornado: RequestHandler.prepare()
- Tornado: RequestHandler.on_finish()

## 5. Falcon / Pyramid / Bottle
- Falcon: middleware.process_request / process_response
- Pyramid: tween_factory
- Pyramid: @subscriber(NewRequest)
- Bottle: app.add_hook("before_request"/"after_request")

## 6. Celery / 任务拦截
- Celery: task_prerun / task_postrun
- Celery: Task.before_start / after_return
- RQ: job hooks

## 7. 旧框架/自定义
- web.py: web.application.add_processor(...)
- Pylons: pylons.middleware
- TurboGears: @before_call / @after_call
- TurboGears: @before_validate / @before_render
- web2py: response.middleware
- web2py: @auth.requires / @auth.requires_login
- Perl Mojolicious: app->hook(before_dispatch/after_dispatch)

## 8. 安全漏洞相关拦截与装饰器
- Django: django.views.decorators.csrf.csrf_protect
- Django: django.views.decorators.csrf.ensure_csrf_cookie
- Django: django.views.decorators.clickjacking.xframe_options_deny
- Django: django.views.decorators.clickjacking.xframe_options_sameorigin
- DRF: permission_classes(...)
- DRF: throttle_classes(...)
- Flask: flask_wtf.csrf.CSRFProtect
- Flask: flask_talisman.Talisman
- FastAPI: fastapi.security.HTTPBearer
- FastAPI: fastapi.security.OAuth2PasswordBearer

## 9. 漏洞类型对应拦截补充
- SQL 注入: Django connection.execute_wrapper
- SQL 注入: SQLAlchemy event.listen(engine, "before_cursor_execute", ...)
- SSRF: requests.Session.request 自定义包装
- XSS 输出: Jinja2 Environment.autoescape
- 不安全重定向: Django redirect 包装器

## 10. 漏洞类型对应常见框架/库
- SQL 注入: Django ORM QuerySet 参数化
- SQL 注入: SQLAlchemy event.listen / before_cursor_execute
- SQL 注入: Peewee pre-save hook 校验
- SSRF: httpx.Client 自定义 transport 限制
- XXE: defusedxml 元素解析
- XSS: Bleach 清洗装饰器
- 反序列化: itsdangerous BadSignature 拦截

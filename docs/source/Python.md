# Python 漏洞 Source 点清单

## 1. Web 请求参数（Django/Flask/FastAPI）
- Django: request.GET.get(...)
- Django: request.POST.get(...)
- Django: request.body
- Django: request.META.get("HTTP_*")
- Django: request.headers.get(...)
- Django: request.COOKIES.get(...)
- Flask: request.args.get(...)
- Flask: request.form.get(...)
- Flask: request.values.get(...)
- Flask: request.get_json(...)
- Flask: request.data / request.stream
- FastAPI: Query(...) / Path(...) / Header(...)
- FastAPI: Body(...) / Cookie(...)
- Starlette: request.query_params.get(...)
- Starlette: await request.json()
- Starlette: await request.body()
- Django REST Framework: request.data
- Django REST Framework: request.query_params.get(...)
- Django REST Framework: request.headers.get(...)
- Flask-RESTful: request.args / request.json
- Sanic: request.args / request.json / request.body
- Tornado: self.get_argument(...)
- Falcon: req.get_param(...)
- Pyramid: request.params.get(...)
- Bottle: request.query / request.forms / request.json
- aiohttp.web: request.query / await request.json()

## 2. 文件上传/多部件表单
- Django: request.FILES.get(...)
- Flask: request.files.get(...)
- FastAPI: UploadFile.filename
- FastAPI: await UploadFile.read()
- Django: request.FILES["..."]
- Flask: FileStorage.stream.read()
- Sanic: request.files.get(...)
- Tornado: self.request.files["..."]
- Starlette: await UploadFile.read()

## 3. URL/路径相关输入
- request.url / request.base_url
- request.path / request.full_path
- request.url_root
- request.host
- request.scheme
- request.headers.get("Host")

## 4. 认证/会话/Token 输入
- Django: request.user.get_username()
- Django: request.session.get(...)
- Flask: session.get(...)
- FastAPI: OAuth2PasswordBearer token
- JWT: jwt.get_unverified_header(...)
- JWT: jwt.decode(...) 读取 claim
- Django REST Framework: request.auth
- Flask-JWT-Extended: get_jwt_identity()
- FastAPI: OAuth2PasswordRequestForm.username / password

## 5. RPC/微服务输入
- gRPC: request.<field>
- Celery: task args/kwargs
- GraphQL: resolver args / info.context
- Celery: task.request.kwargs
- nameko: ctx.data
- thriftpy2: request.<field>
- xmlrpc.server: params

## 6. 模板/表达式输入
- Django template: {{ request.GET.xxx }}
- Jinja2: {{ request.args.xxx }}
- Jinja2: {{ request.headers.xxx }}
- Mako: ${request.params.get(...)}
- Django: {{ request.POST.xxx }}
- Jinja2: {{ request.form.xxx }}
- Tornado: self.get_argument(...)

## 7. 消息队列/事件流输入
- Kafka: msg.value()
- RabbitMQ: body
- Redis: pubsub message["data"]
- Pulsar: msg.data()
- Dramatiq: message.args / message.kwargs
- RQ: job.args / job.kwargs
- kombu: message.body

## 8. 数据库中不可信字段
- ORM 模型字段来自用户创建记录
- cursor.fetchone()/fetchall() 结果字段

## 9. 外部系统/配置输入
- os.environ.get(...)
- os.getenv(...)
- configparser.ConfigParser().get(...)
- yaml.safe_load(...) 加载配置
- json.load(...) 读取外部配置
- dynaconf: settings.get(...)
- hvac: client.read(...)

## 10. CLI/脚本输入
- sys.argv
- argparse.ArgumentParser().parse_args()
- click.get_current_context().params
- typer.Option / typer.Argument

## 11. 框架细分（Django REST Framework 等）
- DRF: APIView.request.data
- DRF: APIView.request.query_params
- DRF: APIView.request.headers.get(...)
- DRF: APIView.request.auth / request.user
- DRF: Serializer.validated_data
- DRF: Serializer.initial_data
- DRF: request._full_data
- django-filter: request.query_params.get(...)
- django-rest-framework-simplejwt: token.payload / token["claim"]

## 12. 框架细分（Falcon / Sanic / 旧框架）
- Falcon: req.media
- Falcon: req.params / req.get_param(...)
- Falcon: req.get_header(...)
- Sanic: request.json / request.args / request.form
- Sanic: request.headers / request.cookies
- Sanic: request.files / request.raw_body
- web.py: web.input()
- Pylons: request.params / request.POST
- TurboGears: request.params / request.json_body

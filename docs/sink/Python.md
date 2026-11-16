# Python 漏洞 Sink 点清单

## 1. 命令执行
- os.system(user_input)
- subprocess.run(user_input, shell=True)
- subprocess.Popen(user_input, shell=True)
- subprocess.call(user_input, shell=True)
- eval(user_input) / exec(user_input)
- os.popen(user_input)
- subprocess.check_output(user_input, shell=True)
- subprocess.check_call(user_input, shell=True)
- pexpect.run(user_input)
- os.spawnl(os.P_WAIT, cmd, ...)
- os.spawnlp(os.P_WAIT, cmd, ...)

## 2. SQL 注入
- cursor.execute(sql_string)
- cursor.executemany(sql_string)
- connection.execute(sql_string)
- ORM 中的 raw/extra 直接拼接 SQL
- sqlalchemy.text(sql_string) 直接拼接
- Model.objects.raw(sql_string)
- connection.cursor().execute(sql_string)
- pandas.read_sql(sql_string, connection)

## 3. 路径遍历/任意文件读写
- open(user_input_path, "r|w|a")
- pathlib.Path(user_input_path).read_text()
- pathlib.Path(user_input_path).write_text(...)
- shutil.copy(user_input_path, ...)
- os.remove(user_input_path)
- os.listdir(user_input_path)
- pathlib.Path(user_input_path).read_bytes()
- pathlib.Path(user_input_path).write_bytes(...)
- shutil.copy2(user_input_path, ...)
- shutil.move(user_input_path, ...)
- os.path.exists(user_input_path)
- glob.glob(user_input_path)
- tempfile.NamedTemporaryFile(dir=user_input_path)
- zipfile.ZipFile.extract(member, path=user_input_path)
- tarfile.TarFile.extractall(path=user_input_path)

## 4. 反序列化
- pickle.loads(user_input)
- pickle.load(file)
- yaml.load(user_input) / yaml.load(file)
- marshal.loads(user_input)
- jsonpickle.decode(user_input)
- dill.loads(user_input)
- shelve.open(user_input)
- joblib.load(user_input)
- numpy.load(user_input, allow_pickle=True)

## 5. SSRF / 外部请求
- requests.get(user_input_url)
- requests.post(user_input_url)
- urllib.request.urlopen(user_input_url)
- httpx.get(user_input_url)
- aiohttp.ClientSession().get(user_input_url)
- requests.put(user_input_url)
- requests.delete(user_input_url)
- httpx.post(user_input_url)
- urllib.request.Request(user_input_url)
- urllib3.PoolManager().request("GET", user_input_url)

## 6. 模板注入
- jinja2.Template(user_input).render(...)
- jinja2.Environment().from_string(user_input).render(...)
- mako.template.Template(user_input).render(...)
- tornado.template.Template(user_input).generate(...)
- django.template.Template(user_input).render(...)

## 7. 代码注入 / 动态导入
- importlib.import_module(user_input)
- __import__(user_input)
- eval/exec 处理用户输入表达式
- pkgutil.resolve_name(user_input)
- pydoc.locate(user_input)
- runpy.run_module(user_input)
- runpy.run_path(user_input)

## 8. 命令/代码生成
- ast.literal_eval(user_input) 在未限制上下文时
- compile(user_input, ..., "exec")
- code.compile_command(user_input)
- ast.parse(user_input)

## 9. 不安全重定向/跳转
- Flask/Django redirect(user_input)
- Response(location=user_input)
- werkzeug.utils.redirect(user_input)
- HttpResponseRedirect(user_input)

## 10. XSS 输出
- 返回 HTML 内容时直接拼接 user_input
- 模板 autoescape 关闭或使用 |safe
- markupsafe.Markup(user_input)
- django.utils.safestring.mark_safe(user_input)

## 11. 日志注入
- logging.info(user_input)
- logging.error(user_input)
- print(user_input) 写入审计日志
- logging.warning(user_input)
- logger.exception(user_input)

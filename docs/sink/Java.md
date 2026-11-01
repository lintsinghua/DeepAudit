# Java 漏洞 Sink 点清单

## 1. 命令执行
- Runtime.getRuntime().exec(...)
- new ProcessBuilder(...).start()
- ScriptEngine.eval(...) 当脚本拼接输入
- new GroovyShell().evaluate(...)
- new GroovyShell().parse(...).run()
- new javax.tools.ToolProvider.getSystemJavaCompiler().run(...)
- org.codehaus.groovy.control.CompilationUnit.compile(...)

## 2. SQL 注入
- Statement.execute(...)
- Statement.executeQuery(...)
- Statement.executeUpdate(...)
- PreparedStatement 直接拼接 SQL 字符串后执行
- CallableStatement.execute(...)
- CallableStatement.executeQuery(...)
- QueryRunner.query(...) 直接拼接 SQL
- EntityManager.createNativeQuery(sql)
- Session.createSQLQuery(sql) / createNativeQuery(sql)

## 3. 路径遍历/任意文件读写
- new FileInputStream(userInputPath)
- new FileOutputStream(userInputPath)
- Files.readAllBytes(Paths.get(userInputPath))
- Files.newBufferedReader(Paths.get(userInputPath))
- Files.write(Paths.get(userInputPath), ...)
- RandomAccessFile(userInputPath, "rw")
- Files.newInputStream(Paths.get(userInputPath))
- Files.newOutputStream(Paths.get(userInputPath))
- Files.copy(Paths.get(userInputPath), ...)
- Files.move(Paths.get(userInputPath), ...)
- new FileReader(userInputPath)
- new FileWriter(userInputPath)
- new BufferedReader(new FileReader(userInputPath))
- new BufferedWriter(new FileWriter(userInputPath))
- File.delete() / Files.delete(Paths.get(userInputPath))
- File.listFiles() / Files.list(Paths.get(userInputPath))

## 4. 反序列化
- ObjectInputStream.readObject()
- XMLDecoder.readObject()
- XStream.fromXML(...)
- Yaml.load(...) / SnakeYAML load(...)
- Yaml.loadAll(...)
- ObjectMapper.readValue(byte[], Object.class)
- Kryo.readClassAndObject(...)
- HessianInput.readObject()
- JSON.parseObject(...) 允许 autoType 时
- java.io.ObjectInputStream.readUnshared()

## 5. SSRF / 外部请求
- new URL(userInput).openStream()
- URLConnection.connect()
- HttpURLConnection.getInputStream()
- Apache HttpClient.execute(...)
- OkHttpClient.newCall(request).execute()
- HttpClient.newHttpClient().send(...)
- WebClient.get().uri(userInput).retrieve()
- RestTemplate.getForObject(userInput, ...)
- RestTemplate.exchange(userInput, ...)
- Jsoup.connect(userInput).get()

## 6. XXE / XML 解析
- DocumentBuilder.parse(...)
- SAXParser.parse(...)
- JAXB.unmarshal(...)
- XMLInputFactory.createXMLStreamReader(...)
- SAXReader.read(...) (dom4j)
- DocumentBuilderFactory.newDocumentBuilder().parse(...)
- TransformerFactory.newTransformer().transform(...)
- XPathFactory.newInstance().newXPath().evaluate(...)

## 7. 模板注入
- VelocityEngine.evaluate(...)
- Freemarker Template.process(...)
- Thymeleaf 解析含用户输入的模板
- Mustache.compile(userInput).execute(...)
- StringSubstitutor.replace(userInput)
- MessageFormat.format(userInput, ...)

## 8. 代码注入 / 脚本执行
- GroovyShell.evaluate(...)
- JavaCompiler.run(...) 处理用户输入源码
- javax.script.ScriptEngine.eval(...)
- NashornScriptEngine.eval(...)
- ScriptEngineManager.getEngineByName(...).eval(...)

## 9. 反射与类加载
- Class.forName(userInput)
- ClassLoader.loadClass(userInput)
- Method.invoke(...) 目标或参数来自用户输入
- Constructor.newInstance(...)
- Class.forName(userInput, true, classLoader)
- URLClassLoader.newInstance(urls)

## 10. 不安全重定向/跳转
- HttpServletResponse.sendRedirect(userInput)
- Response.temporaryRedirect(URI.create(userInput))
- Response.seeOther(URI.create(userInput))
- ModelAndView.setViewName(userInput)

## 11. XSS 输出
- response.getWriter().write(userInput)
- response.getOutputStream().print(userInput)
- JSP 表达式/脚本输出未转义内容
- response.sendError(..., userInput)
- PrintWriter.print(userInput)
- out.write(userInput) (JSP)

## 12. 日志注入
- logger.info(userInput)
- logger.warn(userInput)
- logger.error(userInput)
- Logger.log(Level.INFO, userInput)
- Logger.log(Level.WARNING, userInput)

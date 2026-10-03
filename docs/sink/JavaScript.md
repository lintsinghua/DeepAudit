# JavaScript 漏洞 Sink 点清单

## 1. 命令执行（Node.js）
- child_process.exec(userInput)
- child_process.execSync(userInput)
- child_process.spawn(command, args) command/args 来自用户输入
- child_process.spawnSync(...)
- child_process.execFile(file, args)
- child_process.execFileSync(file, args)
- child_process.fork(modulePath, args)

## 2. SQL 注入
- database.query(sqlString)
- connection.query(sqlString)
- sequelize.query(sqlString)
- knex.raw(sqlString)
- pg.Client.query(sqlString)
- mysql.createConnection().query(sqlString)
- mssql.Request().query(sqlString)
- prisma.$queryRawUnsafe(sqlString)
- sqlite3.Database().all(sqlString)

## 3. 路径遍历/任意文件读写
- fs.readFile(userInputPath, ...)
- fs.readFileSync(userInputPath, ...)
- fs.writeFile(userInputPath, ...)
- fs.writeFileSync(userInputPath, ...)
- fs.createReadStream(userInputPath)
- fs.createWriteStream(userInputPath)
- path.join(base, userInputPath) 后直接读写
- fs.promises.readFile(userInputPath)
- fs.promises.writeFile(userInputPath, ...)
- fs.promises.readdir(userInputPath)
- fs.promises.unlink(userInputPath)
- fs.promises.rename(userInputPath, ...)
- fs.open(userInputPath, ...)
- fs.rm(userInputPath, ...)
- fs.readdir(userInputPath, ...)
- tar.extract({ cwd: userInputPath })
- unzipper.Extract({ path: userInputPath })

## 4. 反序列化
- JSON.parse(userInput) 在信任边界外
- yaml.load(userInput) / yaml.safeLoad(userInput) 配置不当
- serialize/deserialize 库的 deserialize(userInput)
- safe-json-parse(userInput) 处理后续逻辑
- bson.deserialize(userInput)
- node-serialize.unserialize(userInput)
- msgpack.decode(userInput)

## 5. SSRF / 外部请求
- fetch(userInputUrl)
- axios.get(userInputUrl)
- request(userInputUrl)
- got(userInputUrl)
- http.request(userInputUrl)
- https.request(userInputUrl)
- axios.post(userInputUrl)
- node-fetch(userInputUrl)
- superagent.get(userInputUrl)
- undici.request(userInputUrl)

## 6. 模板注入
- ejs.render(userInput, ...)
- handlebars.compile(userInput)(...)
- pug.render(userInput, ...)
- lodash.template(userInput)(...)
- nunjucks.renderString(userInput, ...)
- mustache.render(userInput, ...)
- twig.render(userInput, ...)

## 7. 代码注入
- eval(userInput)
- new Function(userInput)()
- setTimeout(userInput, ...)
- setInterval(userInput, ...)
- vm.runInThisContext(userInput)
- vm.runInNewContext(userInput)
- vm.Script(userInput).runInThisContext()
- vm.runInContext(userInput, sandbox)
- require(userInput) / import(userInput)

## 8. 原型污染关键点
- lodash.merge(target, userInput)
- Object.assign(target, userInput)
- deep merge 自定义实现接收用户输入对象
- _.defaultsDeep(target, userInput)
- qs.parse(userInput)
- jQuery.extend(true, target, userInput)
- hoek.merge(target, userInput)

## 9. 不安全重定向/跳转
- res.redirect(userInput)
- window.location = userInput
- location.href = userInput
- res.writeHead(302, { Location: userInput })
- document.location = userInput

## 10. XSS 输出
- innerHTML = userInput
- dangerouslySetInnerHTML
- document.write(userInput)
- res.send(userInput) / res.write(userInput)
- res.end(userInput)
- element.outerHTML = userInput
- insertAdjacentHTML("beforeend", userInput)
- jQuery.html(userInput)

## 11. 日志注入
- console.log(userInput)
- logger.info(userInput)
- logger.error(userInput)
- console.error(userInput)
- console.warn(userInput)

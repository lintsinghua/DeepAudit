# L0 taint spec (generic, project-independent)

## Sources (attacker-controlled)
- Java Servlet/JSP: HttpServletRequest.getParameter / getParameterValues / getHeader / getCookies / getQueryString / getInputStream / getReader / getPart; JSP implicit object `request`.
- Spring: @RequestParam, @PathVariable, @RequestBody, @RequestHeader, @CookieValue, @ModelAttribute parameters.
- Express/Node: req.query, req.params, req.body, req.headers, req.cookies, req.files/req.file, req.get(), req.url.
- Python: request.args/form/json/values/files/cookies/headers (Flask), request.GET/POST/body (Django), FastAPI handler params.
- Second-order (mark separately): values read back from DB/session/cache that were earlier written from user input. Only real if you can show the write path.

## Sinks by vulnerability class
- SQLi CWE-89: Statement.executeQuery/executeUpdate/execute, JdbcTemplate.query* with concatenation, sequelize.query, *.query(raw string), knex.raw, cursor.execute(f-string/%).
- NoSQL injection CWE-943: Mongo/MarsDB find/findOne/update with $where or with object built from user input.
- Command injection CWE-78: Runtime.exec, ProcessBuilder, child_process.exec/execSync/spawn(shell:true), os.system, subprocess(shell=True).
- Code injection CWE-94: eval, Function(), vm.runIn*Context, notevil/safeEval, ScriptEngine.eval.
- Template injection CWE-1336: pug.compile/render with user-built template, ejs.render with user template, Jinja2 Template(user).
- Path traversal CWE-22: File/FileInputStream/Paths.get, fs.readFile*/createReadStream/sendFile/res.render(path), open().
- SSRF CWE-918: URL.openConnection, HttpClient.execute, fetch/axios/request/http.request, requests.get.
- XXE CWE-611: XML parsers with external entities enabled (DocumentBuilder without hardening, libxml noent:true).
- Deserialization CWE-502 / resource exhaustion CWE-776: ObjectInputStream.readObject, yaml.load (unsafe / bombs), node-serialize.unserialize.
- XSS CWE-79: user data written to HTML without encoding (JSP <%= %>, res.send(html), innerHTML/bypassSecurityTrust*).
- Open redirect CWE-601: res.redirect / sendRedirect with user-controlled URL and weak allowlist.

## Sanitizers are class-specific
- Parameterized queries / prepared statements with bound params stop SQLi; HTML escaping does not.
- Integer.parseInt / Number() casting stops injection for that value.
- Allowlists stop injection only if the check is exact (startsWith/includes on URLs is usually bypassable).
- A replace() that strips characters stops the attack only if it removes everything the sink needs.
- Single-segment path checks: if a value is rejected when it contains the path separator and is then joined as the last
  segment (path.resolve(base, name) / new File(base, name)), it cannot address files outside base on POSIX: '..' alone
  only names base's parent directory itself, and URL-decoded '%2F' is still caught by the check. Report path traversal
  there only if you show a concrete bypass (backslash on Windows, a separator the check misses, a decode after the check).
  The opposite also holds: extension allowlists (endsWith('.md')) are bypassable by null-byte or truncation tricks
  when the value is cut AFTER the check.

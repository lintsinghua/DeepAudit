# L0 taint spec (generic, project-independent)

## Sources (attacker-controlled)
- Java Servlet/JSP: HttpServletRequest.getParameter / getParameterValues / getHeader / getCookies / getQueryString / getInputStream / getReader / getPart; JSP implicit object `request`.
- Spring: @RequestParam, @PathVariable, @RequestBody, @RequestHeader, @CookieValue, @ModelAttribute parameters.
- Express/Node: req.query, req.params, req.body, req.headers, req.cookies, req.files/req.file, req.get(), req.url.
- Python: request.args/form/json/values/files/cookies/headers (Flask), request.GET/POST/body/FILES/COOKIES/META (Django), FastAPI handler params (Query/Body/Path/Form/File).
- PHP: $_GET, $_POST, $_REQUEST, $_COOKIE, $_FILES, $_SERVER (HTTP_*, REQUEST_URI, PHP_SELF), php://input; Laravel $request->input()/query()/get()/all()/file(), request(), route parameters.
- Second-order (mark separately): values read back from DB/session/cache that were earlier written from user input. Only real if you can show the write path.

## Sinks by vulnerability class
- SQLi CWE-89: Statement.executeQuery/executeUpdate/execute, JdbcTemplate.query* with concatenation, sequelize.query, *.query(raw string), knex.raw, cursor.execute(f-string/%), Django .raw()/.extra()/RawSQL, SQLAlchemy text(f"...");
  PHP mysqli_query/mysql_query/pg_query/PDO->query/->exec with interpolated strings, Laravel DB::raw/whereRaw/selectRaw/orderByRaw.
- NoSQL injection CWE-943: Mongo/MarsDB find/findOne/update with $where or with object built from user input.
- Command injection CWE-78: Runtime.exec, ProcessBuilder, child_process.exec/execSync/spawn(shell:true), os.system, os.popen, subprocess(shell=True), PHP system/exec/shell_exec/passthru/popen/proc_open/backticks.
- File inclusion CWE-98 (PHP): include/require(_once) with a user-controlled path (LFI/RFI).
- Code injection CWE-94: eval, Function(), vm.runIn*Context, notevil/safeEval, ScriptEngine.eval, Python eval/exec, PHP eval/assert/create_function/preg_replace /e.
- Template injection CWE-1336: pug.compile/render with user-built template, ejs.render with user template, Jinja2 Template(user) / render_template_string(user), Django Template(user), Blade {!! !!} with user data.
- Path traversal CWE-22: File/FileInputStream/Paths.get, fs.readFile*/createReadStream/sendFile/res.render(path), Python open()/send_file/send_from_directory, PHP file_get_contents/fopen/readfile/unlink/move_uploaded_file.
- SSRF CWE-918: URL.openConnection, HttpClient.execute, fetch/axios/request/http.request, requests.get/urlopen, PHP curl_exec/file_get_contents(url).
- XXE CWE-611: XML parsers with external entities enabled (DocumentBuilder without hardening, libxml noent:true).
- Deserialization CWE-502 / resource exhaustion CWE-776: ObjectInputStream.readObject, yaml.load (unsafe / bombs), node-serialize.unserialize, Python pickle.loads/yaml.load (unsafe Loader), PHP unserialize.
- XSS CWE-79: user data written to HTML without encoding (JSP <%= %>, res.send(html), innerHTML/bypassSecurityTrust*, PHP echo $_GET[...], Jinja |safe / Markup).
- Open redirect CWE-601: res.redirect / sendRedirect with user-controlled URL and weak allowlist.

## Sanitizers are class-specific
- Parameterized queries / prepared statements with bound params stop SQLi; HTML escaping does not.
- Integer.parseInt / Number() / int() / intval() / (int) casting stops injection for that value.
- PHP: mysqli_real_escape_string stops SQLi only inside a quoted string literal; htmlspecialchars stops XSS
  in HTML text and quoted attributes, not in JS contexts or unquoted attributes; escapeshellarg stops
  argument injection, escapeshellcmd does not stop it.
- Allowlists stop injection only if the check is exact (startsWith/includes on URLs is usually bypassable).
- A replace() that strips characters stops the attack only if it removes everything the sink needs.
- Single-segment path checks: if a value is rejected when it contains the path separator and is then joined as the last
  segment (path.resolve(base, name) / new File(base, name)), it cannot address files outside base on POSIX: '..' alone
  only names base's parent directory itself, and URL-decoded '%2F' is still caught by the check. Report path traversal
  there only if you show a concrete bypass (backslash on Windows, a separator the check misses, a decode after the check).
  The opposite also holds: extension allowlists (endsWith('.md')) are bypassable by null-byte or truncation tricks
  when the value is cut AFTER the check.

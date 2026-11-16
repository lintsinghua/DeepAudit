"""
路径遍历漏洞知识
"""

from ..base import KnowledgeDocument, KnowledgeCategory


PATH_TRAVERSAL = KnowledgeDocument(
    id="vuln_path_traversal",
    title="Path Traversal",
    category=KnowledgeCategory.VULNERABILITY,
    tags=["path", "traversal", "file", "directory", "lfi", "rfi"],
    severity="high",
    cwe_ids=["CWE-22", "CWE-23"],
    owasp_ids=["A01:2021"],
    content="""
路径遍历允许攻击者访问应用程序根目录之外的文件，可能导致敏感信息泄露或代码执行。

## 危险模式

### Python
```python
# 危险 - 直接拼接路径
file_path = "/uploads/" + user_filename
open(base_dir + request.args['file'])
os.path.join(base_dir, user_input)  # 仍然危险！

# 危险 - 文件下载
@app.route('/download')
def download():
    filename = request.args.get('file')
    return send_file(f'/files/{filename}')

# 危险 - 模板包含
render_template(user_template)
```

### Node.js
```javascript
// 危险
const filePath = path.join(__dirname, req.query.file);
fs.readFile('./uploads/' + filename);
res.sendFile(req.params.path);
```

### PHP
```php
// 危险
include($_GET['page']);
require($user_input);
file_get_contents($filename);
```

## 攻击载荷
```
../../../etc/passwd
..\\..\\..\\windows\\system32\\config\\sam
....//....//....//etc/passwd
..%2f..%2f..%2fetc/passwd
%2e%2e%2f%2e%2e%2f%2e%2e%2fetc/passwd
..%252f..%252f..%252fetc/passwd (双重编码)
```

## 敏感文件目标
```
# Linux
/etc/passwd
/etc/shadow
/etc/hosts
/proc/self/environ
/var/log/apache2/access.log

# Windows
C:\\Windows\\System32\\config\\SAM
C:\\Windows\\win.ini
C:\\inetpub\\logs\\LogFiles

# 应用配置
.env
config.php
settings.py
application.yml
```

## 检测要点
1. 所有文件操作函数
2. 用户输入是否用于构建路径
3. 是否有路径规范化
4. 是否验证最终路径在允许范围内

## 安全实践
1. 验证和规范化路径
2. 使用白名单
3. 检查路径是否在允许目录内
4. 使用安全的文件ID映射

## 修复示例
```python
import os

def safe_join(base_dir, user_path):
    # 规范化路径
    base_dir = os.path.abspath(base_dir)
    full_path = os.path.abspath(os.path.join(base_dir, user_path))
    
    # 验证路径在基础目录内
    if not full_path.startswith(base_dir + os.sep):
        raise ValueError("Path traversal detected")
    
    return full_path

# 使用
try:
    safe_path = safe_join('/uploads', user_filename)
    with open(safe_path) as f:
        content = f.read()
except ValueError:
    abort(403)

# 更安全 - 使用文件ID映射
@app.route('/download/<file_id>')
def download(file_id):
    file_record = File.query.get(file_id)
    if file_record and file_record.user_id == current_user.id:
        return send_file(file_record.path)
    abort(404)
```

### PHP
```php
// 安全 - realpath 解析后校验前缀 (LFI 防护)
function safe_path(string $user_file): string {
    $base = realpath(__DIR__ . '/uploads');
    $full = realpath($base . '/' . $user_file);
    if ($full === false || strpos($full, $base) !== 0) {
        http_response_code(403);
        exit;
    }
    return $full;
}

// 安全 - 使用文件名映射替代直接包含
$pages = ['home' => 'home.php', 'about' => 'about.php'];
$page = $pages[$_GET['p']] ?? 'home.php';   // 白名单映射
include __DIR__ . '/views/' . $page;
```
""",
)

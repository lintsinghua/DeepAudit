"""
XSS (跨站脚本) 漏洞知识
"""

from ..base import KnowledgeDocument, KnowledgeCategory


XSS_REFLECTED = KnowledgeDocument(
    id="vuln_xss_reflected",
    title="Reflected XSS",
    category=KnowledgeCategory.VULNERABILITY,
    tags=["xss", "reflected", "javascript", "html", "injection"],
    severity="high",
    cwe_ids=["CWE-79"],
    owasp_ids=["A03:2021"],
    content="""
反射型XSS：恶意脚本来自当前HTTP请求，服务器将用户输入直接反射到响应中。

## 危险模式

### Python/Flask
```python
# 危险 - 直接返回用户输入
@app.route('/search')
def search():
    query = request.args.get('q')
    return f"<h1>搜索结果: {query}</h1>"

# 危险 - 禁用自动转义
return render_template_string(user_input)
return Markup(user_input)
```

### JavaScript/Express
```javascript
// 危险
res.send(`<h1>Hello ${req.query.name}</h1>`);
res.write(req.body.content);
```

### PHP
```php
// 危险
echo "Hello " . $_GET['name'];
print($_POST['content']);
```

## 攻击载荷
```html
<script>alert('XSS')</script>
<img src=x onerror=alert('XSS')>
<svg onload=alert('XSS')>
javascript:alert('XSS')
<body onload=alert('XSS')>
```

## 安全实践
1. 输出编码/HTML转义
2. 使用模板引擎的自动转义
3. Content-Type设置正确
4. 使用CSP头

## 修复示例
```python
# 安全 - 使用escape
from markupsafe import escape
return f"<h1>搜索结果: {escape(query)}</h1>"

# 安全 - 使用模板（自动转义）
return render_template('search.html', query=query)
```

### PHP
```php
// 安全 - htmlspecialchars 输出转义
echo "Hello " . htmlspecialchars($_GET['name'], ENT_QUOTES, 'UTF-8');

// 安全 - Laravel Blade（默认转义）/ 避免 {!! !!}
{{ $name }}            // Blade 自动转义
{!! $name !!}          // 危险 - 不要用，除非已净化
```
""",
)


XSS_STORED = KnowledgeDocument(
    id="vuln_xss_stored",
    title="Stored XSS",
    category=KnowledgeCategory.VULNERABILITY,
    tags=["xss", "stored", "persistent", "javascript", "database"],
    severity="high",
    cwe_ids=["CWE-79"],
    owasp_ids=["A03:2021"],
    content="""
存储型XSS：恶意脚本被存储在服务器（数据库、文件等），当其他用户访问时执行。

## 危险场景
- 用户评论/留言板
- 用户个人资料
- 论坛帖子
- 文件名/描述
- 日志查看器

## 危险模式
```python
# 危险 - 存储未过滤的用户输入
comment = request.form['comment']
db.save_comment(comment)  # 存储

# 危险 - 显示未转义的内容
comments = db.get_comments()
return render_template_string(f"<div>{comments}</div>")
```

## 检测要点
1. 追踪用户输入到数据库的流程
2. 检查从数据库读取后的输出处理
3. 关注富文本编辑器的处理
4. 检查管理后台的数据展示

## 安全实践
1. 输入时过滤/存储时转义
2. 输出时始终转义
3. 使用白名单HTML标签（如需富文本）
4. 使用DOMPurify等库清理HTML

## 修复示例
```python
# 安全 - 使用bleach清理HTML
import bleach
clean_comment = bleach.clean(comment, tags=['p', 'b', 'i'])
db.save_comment(clean_comment)
```
""",
)


XSS_DOM = KnowledgeDocument(
    id="vuln_xss_dom",
    title="DOM-based XSS",
    category=KnowledgeCategory.VULNERABILITY,
    tags=["xss", "dom", "javascript", "client-side"],
    severity="high",
    cwe_ids=["CWE-79"],
    owasp_ids=["A03:2021"],
    content="""
DOM型XSS：漏洞存在于客户端JavaScript代码，通过修改DOM环境执行恶意脚本。

## 危险源 (Sources)
```javascript
// URL相关
location.href
location.search
location.hash
document.URL
document.referrer

// 存储相关
localStorage.getItem()
sessionStorage.getItem()

// 消息相关
window.postMessage
```

## 危险汇 (Sinks)
```javascript
// 危险 - HTML注入
element.innerHTML = userInput;
element.outerHTML = userInput;
document.write(userInput);
document.writeln(userInput);

// 危险 - JavaScript执行
eval(userInput);
setTimeout(userInput, 1000);
setInterval(userInput, 1000);
new Function(userInput);

// 危险 - URL跳转
location.href = userInput;
location.assign(userInput);
window.open(userInput);
```

## 危险模式
```javascript
// 危险 - 从URL获取并直接使用
const name = new URLSearchParams(location.search).get('name');
document.getElementById('greeting').innerHTML = 'Hello ' + name;

// 危险 - hash注入
const hash = location.hash.substring(1);
document.getElementById('content').innerHTML = decodeURIComponent(hash);
```

## 安全实践
1. 使用textContent代替innerHTML
2. 使用安全的DOM API
3. 对URL参数进行验证
4. 使用DOMPurify清理HTML

## 修复示例
```javascript
// 安全 - 使用textContent
element.textContent = userInput;

// 安全 - 使用DOMPurify
element.innerHTML = DOMPurify.sanitize(userInput);

// 安全 - 创建文本节点
element.appendChild(document.createTextNode(userInput));
```
""",
)

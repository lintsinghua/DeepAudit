"""
SSRF (服务端请求伪造) 漏洞知识
"""

from ..base import KnowledgeDocument, KnowledgeCategory


SSRF = KnowledgeDocument(
    id="vuln_ssrf",
    title="Server-Side Request Forgery (SSRF)",
    category=KnowledgeCategory.VULNERABILITY,
    tags=["ssrf", "request", "url", "network", "internal", "cloud"],
    severity="high",
    cwe_ids=["CWE-918"],
    owasp_ids=["A10:2021"],
    content="""
SSRF允许攻击者诱使服务器向内部资源或任意外部地址发起请求。

## 危险模式

### Python
```python
# 危险 - 直接使用用户URL
response = requests.get(user_provided_url)
urllib.request.urlopen(url_from_user)
httpx.get(user_url)

# 危险 - URL拼接
base_url = "http://internal-api/"
requests.get(base_url + user_path)

# 危险 - 图片/文件获取
image_url = request.args.get('url')
response = requests.get(image_url)
```

### Node.js
```javascript
// 危险
fetch(req.body.url);
axios.get(userUrl);
http.get(url, callback);
```

## 攻击目标
1. 内部服务 (localhost, 127.0.0.1, 内网IP)
2. 云元数据服务
   - AWS: http://169.254.169.254/latest/meta-data/
   - GCP: http://metadata.google.internal/
   - Azure: http://169.254.169.254/metadata/
3. 内部API和数据库
4. 文件协议 (file://)

## 绕过技术
```
# IP绕过
http://127.0.0.1 -> http://127.1 -> http://0
http://localhost -> http://[::1]
http://2130706433 (十进制)
http://0x7f000001 (十六进制)

# DNS重绑定
attacker.com -> 解析到内网IP

# URL解析差异
http://evil.com@internal/
http://internal#@evil.com
```

## 检测要点
1. 所有发起HTTP请求的地方
2. URL参数是否来自用户
3. 是否有URL白名单验证
4. 是否限制了协议和端口

## 安全实践
1. URL白名单验证
2. 禁止访问内部IP地址
3. 使用DNS解析验证
4. 限制协议（仅http/https）
5. 禁用重定向或限制重定向

## 修复示例
```python
import ipaddress
from urllib.parse import urlparse

def is_safe_url(url):
    try:
        parsed = urlparse(url)
        
        # 只允许http/https
        if parsed.scheme not in ['http', 'https']:
            return False
        
        # 解析IP
        import socket
        ip = socket.gethostbyname(parsed.hostname)
        ip_obj = ipaddress.ip_address(ip)
        
        # 禁止私有IP
        if ip_obj.is_private or ip_obj.is_loopback:
            return False
        
        # 白名单域名
        if parsed.hostname not in ALLOWED_HOSTS:
            return False
            
        return True
    except Exception:
        return False

# 使用
if is_safe_url(user_url):
    response = requests.get(user_url, allow_redirects=False)
```
""",
)

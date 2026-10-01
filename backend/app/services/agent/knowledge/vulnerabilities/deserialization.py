"""
反序列化漏洞知识
"""

from ..base import KnowledgeDocument, KnowledgeCategory


INSECURE_DESERIALIZATION = KnowledgeDocument(
    id="vuln_deserialization",
    title="Insecure Deserialization",
    category=KnowledgeCategory.VULNERABILITY,
    tags=["deserialization", "pickle", "yaml", "json", "object", "rce"],
    severity="critical",
    cwe_ids=["CWE-502"],
    owasp_ids=["A08:2021"],
    content="""
不安全的反序列化可能导致远程代码执行、拒绝服务或权限提升。

## 危险模式

### Python Pickle
```python
# 危险 - 反序列化不可信数据
import pickle
data = pickle.loads(user_data)
data = pickle.load(open(user_file, 'rb'))

# 危险 - 通过网络接收
data = pickle.loads(request.data)
```

### Python YAML
```python
# 危险 - 不安全的yaml.load
import yaml
data = yaml.load(user_input)  # 不带Loader参数
data = yaml.load(user_input, Loader=yaml.Loader)  # 不安全的Loader
```

### Python Marshal
```python
# 危险
import marshal
code = marshal.loads(user_data)
```

### Java
```java
// 危险 - ObjectInputStream
ObjectInputStream ois = new ObjectInputStream(userInput);
Object obj = ois.readObject();

// 危险 - XMLDecoder
XMLDecoder decoder = new XMLDecoder(userInput);
Object obj = decoder.readObject();
```

### PHP
```php
// 危险
$data = unserialize($_POST['data']);
```

### Node.js
```javascript
// 危险 - node-serialize
var serialize = require('node-serialize');
var obj = serialize.unserialize(userInput);
```

## 攻击原理
```python
# Pickle RCE示例
import pickle
import os

class Exploit:
    def __reduce__(self):
        return (os.system, ('id',))

payload = pickle.dumps(Exploit())
# 反序列化时执行os.system('id')
```

## 检测要点
1. 搜索pickle.loads, yaml.load, unserialize
2. 检查数据来源是否可信
3. 检查是否有签名验证
4. 关注网络接收的序列化数据

## 安全实践
1. 避免反序列化不可信数据
2. 使用安全的序列化格式（JSON）
3. 使用yaml.safe_load()
4. 实现完整性检查（HMAC签名）
5. 使用白名单限制可反序列化的类

## 修复示例
```python
# 安全 - 使用JSON
import json
data = json.loads(user_input)

# 安全 - 使用safe_load
import yaml
data = yaml.safe_load(user_input)

# 安全 - 签名验证
import hmac
import pickle

def safe_loads(data, signature, key):
    expected_sig = hmac.new(key, data, 'sha256').hexdigest()
    if not hmac.compare_digest(signature, expected_sig):
        raise ValueError("Invalid signature")
    return pickle.loads(data)
```

### PHP
```php
// 安全 - 优先 JSON，避免 unserialize 不可信数据
$data = json_decode($_POST['data'], true);

// 如必须使用 unserialize：sign 签名 + 类名白名单
$payload = base64_decode($_POST['serialized']);
if (!hash_equals(hash_hmac('sha256', $payload, SECRET_KEY), $_POST['sign'])) {
    http_response_code(403); exit;
}
// 仅允许白名单内的类，防止 gadget 链
$allowed = ['User', 'Config'];
if (preg_match('/O:\d+:"([^"]+)"/', $payload, $m)
    && !in_array($m[1], $allowed, true)) {
    throw new Exception('Disallowed class: ' . $m[1]);
}
$obj = unserialize($payload);
```
""",
)

"""
认证和授权漏洞知识
"""

from ..base import KnowledgeDocument, KnowledgeCategory


AUTH_BYPASS = KnowledgeDocument(
    id="vuln_auth_bypass",
    title="Authentication Bypass",
    category=KnowledgeCategory.VULNERABILITY,
    tags=["authentication", "bypass", "login", "session", "jwt"],
    severity="critical",
    cwe_ids=["CWE-287", "CWE-306"],
    owasp_ids=["A07:2021"],
    content="""
认证绕过允许攻击者在不提供有效凭证的情况下访问系统。

## 危险模式

### JWT验证缺失
```python
# 危险 - 不验证签名
jwt.decode(token, options={"verify_signature": False})

# 危险 - 允许none算法
jwt.decode(token, algorithms=["HS256", "none"])

# 危险 - 弱密钥
jwt.encode(payload, "secret", algorithm="HS256")
```

### 会话管理问题
```python
# 危险 - 可预测的会话ID
session_id = str(user_id)
session_id = hashlib.md5(username.encode()).hexdigest()

# 危险 - 会话固定
session['user'] = user  # 登录后未重新生成session
```

### 认证逻辑缺陷
```python
# 危险 - 逻辑绕过
if user.is_admin or request.args.get('admin') == 'true':
    return admin_panel()

# 危险 - 默认凭证
if username == "admin" and password == "admin":
    return login_success()
```

### PHP 认证/会话
```php
// 危险 - 弱密码哈希
if (md5($password) === $user['password_hash']) { login(); }
if (sha1($_POST['pw']) === $row['pass']) { grant(); }

// 危险 - 松脆比较 (type juggling)
if ($_POST['password'] == $user['password']) { login(); }  // '0' == 'abc' 可能绕过

// 危险 - 可预测令牌 / 会话未重新生成
$token = md5($username);
$_SESSION['user_id'] = $user['id'];  // 登录后未 session_regenerate_id()
```

## 检测要点
1. JWT的算法和签名验证
2. 会话ID的随机性
3. 登录后是否重新生成会话
4. 认证逻辑的完整性
5. 默认/硬编码凭证

## 安全实践
1. 强制验证JWT签名
2. 使用强随机会话ID
3. 登录后重新生成会话
4. 多因素认证
5. 账户锁定机制

## 修复示例
```python
# 安全 - 正确验证JWT
jwt.decode(token, SECRET_KEY, algorithms=["HS256"])

# 安全 - 登录后重新生成会话
session.regenerate()
session['user_id'] = user.id
```

### PHP
```php
// 安全 - password_hash / password_verify
if (password_verify($_POST['password'], $user['password_hash'])) { login(); }

// 安全 - 登录后重新生成会话 + 强随机令牌
session_regenerate_id(true);
$_SESSION['user_id'] = $user['id'];
$csrf = bin2hex(random_bytes(32));
```
""",
)


IDOR = KnowledgeDocument(
    id="vuln_idor",
    title="Insecure Direct Object Reference (IDOR)",
    category=KnowledgeCategory.VULNERABILITY,
    tags=["idor", "authorization", "access-control", "bola"],
    severity="high",
    cwe_ids=["CWE-639"],
    owasp_ids=["A01:2021"],
    content="""
IDOR（不安全的直接对象引用）允许攻击者通过修改参数访问其他用户的数据。

## 危险模式

### 直接使用用户输入的ID
```python
# 危险 - 无权限检查
@app.route('/api/user/<user_id>')
def get_user(user_id):
    return User.query.get(user_id).to_dict()

# 危险 - 文件访问
@app.route('/download/<file_id>')
def download(file_id):
    return send_file(f"/uploads/{file_id}")
```

### API端点
```python
# 危险
GET /api/orders/12345  # 可以改成其他订单ID
GET /api/users/100/profile
DELETE /api/documents/999
```

## 攻击方式
1. 递增/递减ID值
2. 使用其他用户的ID
3. 批量枚举
4. 参数污染

## 检测要点
1. 检查所有使用ID参数的端点
2. 验证是否有权限检查
3. 检查是否验证资源所有权
4. 关注批量操作接口

## 安全实践
1. 始终验证资源所有权
2. 使用UUID代替自增ID
3. 实现基于角色的访问控制
4. 记录访问日志

## 修复示例
```python
# 安全 - 验证所有权
@app.route('/api/user/<user_id>')
@login_required
def get_user(user_id):
    user = User.query.get(user_id)
    if user.id != current_user.id and not current_user.is_admin:
        abort(403)
    return user.to_dict()

# 安全 - 使用当前用户上下文
@app.route('/api/profile')
@login_required
def get_profile():
    return current_user.to_dict()
```
""",
)


BROKEN_ACCESS_CONTROL = KnowledgeDocument(
    id="vuln_broken_access_control",
    title="Broken Access Control",
    category=KnowledgeCategory.VULNERABILITY,
    tags=["access-control", "authorization", "privilege", "rbac"],
    severity="critical",
    cwe_ids=["CWE-284", "CWE-285"],
    owasp_ids=["A01:2021"],
    content="""
访问控制失效允许用户执行超出其权限的操作。

## 危险模式

### 缺少权限检查
```python
# 危险 - 管理功能无权限验证
@app.route('/admin/delete_user/<user_id>')
def delete_user(user_id):
    User.query.get(user_id).delete()
    return "Deleted"

# 危险 - 仅前端隐藏
# 前端隐藏了按钮，但API无保护
```

### 权限提升
```python
# 危险 - 可修改角色
@app.route('/api/user/update', methods=['POST'])
def update_user():
    user = current_user
    user.role = request.json.get('role')  # 用户可自己提升权限
    db.commit()
```

### 水平越权
```python
# 危险 - 可访问其他用户数据
@app.route('/api/orders')
def get_orders():
    user_id = request.args.get('user_id')  # 可指定任意用户
    return Order.query.filter_by(user_id=user_id).all()
```

## 检测要点
1. 所有敏感操作是否有权限检查
2. 权限检查是否在服务端
3. 是否可以修改自己的权限
4. 是否可以访问其他用户的资源

## 安全实践
1. 默认拒绝所有访问
2. 服务端强制权限检查
3. 使用RBAC/ABAC
4. 记录所有访问尝试
5. 定期审计权限配置

## 修复示例
```python
# 安全 - 装饰器检查权限
@app.route('/admin/delete_user/<user_id>')
@login_required
@admin_required
def delete_user(user_id):
    User.query.get(user_id).delete()
    return "Deleted"

# 安全 - 白名单可修改字段
ALLOWED_FIELDS = ['name', 'email', 'avatar']
@app.route('/api/user/update', methods=['POST'])
@login_required
def update_user():
    for field in request.json:
        if field in ALLOWED_FIELDS:
            setattr(current_user, field, request.json[field])
```
""",
)

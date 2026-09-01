"""
Laravel 框架安全知识
"""

from ..base import KnowledgeDocument, KnowledgeCategory


LARAVEL_SECURITY = KnowledgeDocument(
    id="framework_laravel",
    title="Laravel Security",
    category=KnowledgeCategory.FRAMEWORK,
    tags=["laravel", "php", "web", "eloquent", "blade", "artisan"],
    severity="high",
    content="""
Laravel 提供 Eloquent ORM、Blade 模板等内置防护，但错误用法仍会引入漏洞。

## 常见漏洞模式

### SQL注入（应使用查询构造器/ORM，避免原始SQL）
```php
// 危险 - 原始SQL字符串拼接
$users = DB::select("SELECT * FROM users WHERE id = " . $id);
$users = DB::table('users')->whereRaw("id = " . $id)->get();

// 安全 - 查询构造器 / 参数绑定
$users = DB::table('users')->where('id', $id)->get();
$users = User::find($id);
$users = DB::select("SELECT * FROM users WHERE id = ?", [$id]);
```

### XSS（Blade 默认转义，警惕 {!! !!}）
```php
// 危险 - 原样输出（会注入脚本）
{!! $userInput !!}

// 安全 - Blade 双大括号自动转义
{{ $userInput }}
```

### 批量赋值漏洞 (Mass Assignment)
```php
// 危险 - 未受保护的批量赋值
$user = User::create($request->all());   // $request 可含 role/is_admin

// 安全 - 使用请求校验 + $fillable 白名单
class User extends Model
{
    protected $fillable = ['name', 'email'];   // 白名单，不放 role
}
$user = User::create($request->only(['name', 'email']));
```

### 会话与认证
```php
// 危险 - 手工拼密码哈希
if (md5($password) === $stored_hash) { ... }

// 安全 - Laravel 认证门面
if (Hash::check($password, $user->password)) { ... }
if (Auth::attempt($request->only('email', 'password'))) { ... }

// 危险 - 弱 APP_KEY
'key' => 'some-secret-string',

// 安全 - 从环境注入
'key' => env('APP_KEY'),
```

### 文件上传与存储
```php
// 危险 - 未校验类型直接保存
$file->storeAs('uploads', $file->getClientOriginalName());

// 安全 - 校验MIME + 使用随机文件名
$request->validate(['file' => 'required|mimes:jpg,png,pdf|max:2048']);
$path = $file->store('uploads');   // 自动生成随机名
```

## 内置安全特性（推荐充分利用）
1. CSRF 中间件 VerifyCsrfToken 默认全站防护，勿在 web 路由关闭
2. `X-CSRF-TOKEN` / csrf_token() 用于 AJAX
3. 默认拒绝：路由模型绑定 + 授权策略 (Gate/Policy) 校验所有权
4. 日志与配置：生产环境 APP_DEBUG 必须为 false，避免堆栈泄露

## 检测要点
1. 出现 DB::select / whereRaw / raw() 且带 . 拼接或变量
2. Blade 模板中 `{!! !!}` 输出请求参数
3. create()/update() 直接吃 request()->all()
4. 硬编码 APP_KEY / secret
""",
)


__all__ = ["LARAVEL_SECURITY"]

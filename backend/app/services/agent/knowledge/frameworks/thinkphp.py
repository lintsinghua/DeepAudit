"""
ThinkPHP 框架安全知识
"""

from ..base import KnowledgeDocument, KnowledgeCategory


THINKPHP_SECURITY = KnowledgeDocument(
    id="framework_thinkphp",
    title="ThinkPHP Security",
    category=KnowledgeCategory.FRAMEWORK,
    tags=["thinkphp", "php", "web", "tp5", "tp6", "pdo"],
    severity="critical",
    content="""
ThinkPHP 是国内常用的 PHP 框架（3.x/5.0/5.1/6.0/8.0）。历史上多个版本存在 RCE、SQL 注入漏洞，审计时需重点排查。

## 已知高危漏洞模式

### ThinkPHP 5.0 无条件 RCE (CVE-2018-1002015 系列)
当路由解析把请求参数拼进方法调用时可能形成 RCE：
```php
// 危险 - 开启 debug 下访问
// GET /index.php?s=/index/\think\app/invokefunction&function=call_user_func_array&vars[0]=system&vars[1][]=id
// 建议：升级版本、关闭 debug、过滤路由 URL

// 安全 - 生产环境
'debug' => false,   // config/app.php
// 使用无洞版本，并对路由参数做类型/白名单校验
```

### SQL 注入（query/select 拼接）
```php
// 危险 - 直接拼接用户输入
$res = Db::query("SELECT * FROM users WHERE id = " . $id);
$res = Db::execute("DELETE FROM t WHERE id = " . $id);

// 危险 - 原生查询 + 字符串补充
$res = Db::table('users')->select("name = '" . input('name') . "'");

// 安全 - 参数绑定 / 查询构造器
$res = Db::query("SELECT * FROM users WHERE id = ?", [$id]);
$user = User::where('name', input('name'))->find();       // 占位符且自动转义
```

### 输入过滤与模板注入
```php
// 危险 - 把用户输入放进 SQL/模板后未过滤
$content = input('content');
// 若开启模板 fetch('') 并传入变量，可导致模板注入

// 安全 - 模板变量不直接拼模板源，使用绑定赋值
$this->assign('content', $content);   // 传值而非传模板
```

### 文件上传
```php
// 危险 - 未做后缀/MIME 校验
$file->move('uploads/', $file->getInfo('name'));

// 安全 - 校验扩展名 + 随机命名
$rule = ['image' => ['file', 'image', 'fileSize' => 2048000, 'ext' => 'jpg,png']];
$info = $file->validate($rule)->move('uploads/', md5(uniqid()) . '.' . $file->extension());
if (!$info) { dump($file->getError()); }
```

### 调试模式与信息泄露
```php
// 危险 - 开启 debug 泄露路径/堆栈/配置
'debug' => true,   // 生产环境必须 false
'app_debug' => true,
```

## 检测要点
1. Db::query / Db::execute / ->select() / ->whereRaw() 出现 . 拼接输入
2. 路由文件与控制器是否过滤了参数（'/think/'、'invokefunction' 等）
3. 上传是否有 ext、mime 校验
4. app_debug / app_trace 是否在生产开启
""",
)


__all__ = ["THINKPHP_SECURITY"]

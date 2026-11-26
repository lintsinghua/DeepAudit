# 安全政策

## 代码隐私与安全警告

⚠️ **重要提示**：本工具通过调用第三方 LLM 服务商 API 进行代码分析，**您的代码将被发送到所选择的 LLM 服务商服务器**。

### 严禁上传以下类型的代码

- 🔒 包含商业机密、专有算法或核心业务逻辑的代码
- 🛡️ 涉及国家秘密、国防安全或其他保密信息的代码
- 🔑 包含敏感数据（如用户数据、密钥、密码、token 等）的代码
- ⚖️ 受法律法规限制不得外传的代码
- 📋 客户或第三方的专有代码（未经授权）

### 安全建议

1. **评估代码敏感性**
   - 用户必须自行评估代码的敏感性
   - 对上传代码及其可能导致的信息泄露承担全部责任

2. **使用本地模型处理敏感代码**
   - 对于敏感代码，请使用 **Ollama 本地模型部署功能**
   - 或使用私有部署的 LLM 服务
   - 本地模型不会将代码发送到任何外部服务器

3. **代码脱敏**
   - 上传前移除敏感信息（API Key、密码、Token 等）
   - 使用占位符替换真实数据
   - 移除包含个人身份信息（PII）的代码

4. **遵守合规要求**
   - 遵守所在国家/地区关于数据保护和隐私的法律法规
   - 遵守公司或组织的保密协议和安全政策
   - 确保拥有代码的使用和分析权限

---

## 支持的安全版本

| 版本 | 支持状态 |
|------|---------|
| 3.x.x | ✅ 支持 |
| 2.x.x | ✅ 支持 |
| 1.x.x | ❌ 不再支持 |

### XCodeReviewer 1.x 升级

1.x 的浏览器客户端会接触构建时配置的密钥，导出报告时也会在应用页面中渲染项目数据。仍在使用 1.x 的部署应迁移到 [DeepAudit 3.x 的最新正式版](https://github.com/lintsinghua/DeepAudit/releases/latest)，按新版部署说明在后端配置模型服务和 Git 凭据。升级前请暂停导出来自不可信项目的报告。

撤下旧前端及其 CDN 缓存，在服务商处撤销并更换曾嵌入前端构建的 API 密钥和 Git 令牌，以及曾发往非预期服务地址的凭据。清理浏览器中旧版保存的服务凭据。已下载的前端文件仍可能含有旧密钥，替换静态资源后也需要轮换。

---

## 报告安全漏洞

如果您发现安全漏洞，请通过以下方式负责任地披露：

### 报告方式

1. **邮箱报告（推荐）**
   - 发送邮件至: lintsinghua@qq.com
   - 邮件标题请注明: `[Security] DeepAudit 安全漏洞报告`

2. **GitHub Issues**
   - 地址: [GitHub Issues](https://github.com/lintsinghua/DeepAudit/issues)
   - ⚠️ **请勿公开披露敏感漏洞详情**
   - 仅描述漏洞类型，详细信息请通过邮件发送

### 报告内容

请在报告中包含以下信息：

- 漏洞类型和严重程度评估
- 受影响的版本和组件
- 复现步骤
- 潜在影响
- 建议的修复方案（如有）

### 响应时间

- 我们会在 **48 小时内** 确认收到报告
- 在 **7 天内** 提供初步评估
- 根据漏洞严重程度，在 **30-90 天内** 发布修复

### 致谢

我们感谢所有负责任地报告安全问题的研究人员。在漏洞修复后，我们会在发布说明中致谢（除非您希望保持匿名）。

---

## 安全最佳实践

### 部署安全

1. **配置部署专用密钥**：首次部署用 `openssl rand -hex 32` 生成 `SECRET_KEY` 并安全保存。升级或轮换前请阅读[密钥配置说明](docs/DEPLOYMENT.md#配置签名密钥)。

2. **配置 HTTPS**
   - 生产环境务必启用 HTTPS
   - 使用 Let's Encrypt 或其他 SSL 证书

3. **限制 CORS**
   - 生产环境配置具体的前端域名
   - 不要使用 `allow_origins=["*"]`

4. **数据库安全**
   - 修改默认数据库密码
   - 限制数据库访问 IP
   - 定期备份数据

5. **API 限流**
   - 配置 Nginx 或应用层限流
   - 防止 API 滥用

### 运行时安全

1. **定期更新依赖**
   ```bash
   # 后端
   cd backend && pip install --upgrade -r requirements.txt
   
   # 前端
   cd frontend && pnpm update
   ```

2. **监控日志**
   - 配置日志收集
   - 设置异常告警

3. **最小权限原则**
   - 使用最小必要的权限运行服务
   - 不要以 root 用户运行容器

---

## 第三方服务安全

本项目集成以下第三方服务，使用时请遵守其各自的服务条款和隐私政策：

| 服务 | 用途 | 隐私政策 |
|------|------|---------|
| OpenAI | LLM API | [Privacy Policy](https://openai.com/privacy/) |
| Google Gemini | LLM API | [Privacy Policy](https://policies.google.com/privacy) |
| Anthropic Claude | LLM API | [Privacy Policy](https://www.anthropic.com/privacy) |
| 阿里云通义千问 | LLM API | [隐私政策](https://terms.alicdn.com/legal-agreement/terms/suit_bu1_ali_cloud/suit_bu1_ali_cloud202112071754_83380.html) |
| DeepSeek | LLM API | [Privacy Policy](https://www.deepseek.com/privacy) |
| Supabase | 数据库 | [Privacy Policy](https://supabase.com/privacy) |
| GitHub | 仓库集成 | [Privacy Policy](https://docs.github.com/en/site-policy/privacy-policies) |

---

## 免责声明

项目作者、贡献者和维护者对因用户上传敏感代码导致的任何信息泄露、知识产权侵权、法律纠纷或其他损失不承担任何责任。

详细免责声明请参阅 [DISCLAIMER.md](DISCLAIMER.md)。

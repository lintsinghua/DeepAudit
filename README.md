# DeepAudit - 人人拥有的 AI 审计战队，让漏洞挖掘触手可及 🦸‍♂️

<div style="width: 100%; max-width: 600px; margin: 0 auto;">
  <img src="frontend/public/images/logo.png" alt="DeepAudit Logo" style="width: 100%; height: auto; display: block; margin: 0 auto;">
</div>

<div align="center">

[![Version](https://img.shields.io/badge/version-3.0.4-blue.svg)](https://github.com/lintsinghua/DeepAudit/releases)
[![License: AGPL-3.0](https://img.shields.io/badge/License-AGPL--3.0-blue.svg)](https://www.gnu.org/licenses/agpl-3.0)
[![React](https://img.shields.io/badge/React-18-61dafb.svg)](https://reactjs.org/)
[![TypeScript](https://img.shields.io/badge/TypeScript-5.7-3178c6.svg)](https://www.typescriptlang.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.100+-009688.svg)](https://fastapi.tiangolo.com/)
[![Python](https://img.shields.io/badge/Python-3.11+-3776ab.svg)](https://www.python.org/)
[![Ask DeepWiki](https://deepwiki.com/badge.svg)](https://deepwiki.com/lintsinghua/DeepAudit)

[![Stars](https://img.shields.io/github/stars/lintsinghua/DeepAudit?style=social)](https://github.com/lintsinghua/DeepAudit/stargazers)
[![Forks](https://img.shields.io/github/forks/lintsinghua/DeepAudit?style=social)](https://github.com/lintsinghua/DeepAudit/network/members)

<a href="https://trendshift.io/repositories/15634" target="_blank"><img src="https://trendshift.io/api/badge/repositories/15634" alt="lintsinghua%2FDeepAudit | Trendshift" style="width: 250px; height: 55px;" width="250" height="55"/></a>

<p align="center">
  <strong>简体中文</strong> | <a href="README_EN.md">English</a>
</p>

</div>

<div align="center">
  <img src="frontend/public/DeepAudit.gif" alt="DeepAudit Demo" width="90%">
</div>

---



## 📸 界面预览

<div align="center">

### 🤖 Agent 审计入口

<img src="frontend/public/images/README-show/Agent审计入口（首页）.png" alt="Agent审计入口" width="90%">

*首页快速进入 Multi-Agent 深度审计*

</div>

<table>
<tr>
<td width="50%" align="center">
<strong>📋 审计流日志</strong><br/><br/>
<img src="frontend/public/images/README-show/审计流日志.png" alt="审计流日志" width="95%"><br/>
<em>实时查看 Agent 思考与执行过程</em>
</td>
<td width="50%" align="center">
<strong>🎛️ 智能仪表盘</strong><br/><br/>
<img src="frontend/public/images/README-show/仪表盘.png" alt="仪表盘" width="95%"><br/>
<em>一眼掌握项目安全态势</em>
</td>
</tr>
<tr>
<td width="50%" align="center">
<strong>⚡ 即时分析</strong><br/><br/>
<img src="frontend/public/images/README-show/即时分析.png" alt="即时分析" width="95%"><br/>
<em>粘贴代码 / 上传文件，秒出结果</em>
</td>
<td width="50%" align="center">
<strong>🗂️ 项目管理</strong><br/><br/>
<img src="frontend/public/images/README-show/项目管理.png" alt="项目管理" width="95%"><br/>
<em>GitHub/GitLab/Gitea 导入，多项目协同管理</em>
</td>
</tr>
</table>

<div align="center">

### 📊 专业报告

<img src="frontend/public/images/README-show/审计报告示例.png" alt="审计报告" width="90%">

*一键导出 PDF / Markdown / JSON*（图中为快速模式，非Agent模式报告）

👉 [查看Agent审计完整报告示例](https://lintsinghua.github.io/)

</div>

---

## 🏆 CVE 漏洞发现

<div align="center">

### **DeepAudit 已成功发现并获得 49 个 CVE 编号 和 6 个 GHSA 安全公告🦞**
### **涉及17个知名开源项目**
</div>

#### OpenClaw🦞 漏洞挖掘成果

DeepAudit 内测版本对 [OpenClaw](https://github.com/openclaw/openclaw) 项目进行了深度安全审计，目前已发现 **6 个安全漏洞**，均已被官方确认并发布安全公告（GHSA）。漏洞类型覆盖命令注入、签名验证绕过、远程代码执行、凭证泄露、资源耗尽及敏感信息泄露，其中包含多个 High 级别漏洞。更多漏洞仍在持续挖掘中。

| GHSA 编号 | 项目 | 项目热度 | 漏洞类型 | 严重性 |
|:---|:---|:---:|:---|:----:|
| [GHSA-g353-mgv3-8pcj](https://github.com/advisories/GHSA-g353-mgv3-8pcj) | OpenClaw | [![Stars](https://img.shields.io/github/stars/openclaw/openclaw?style=social)](https://github.com/openclaw/openclaw/stargazers) | Signature Verification Bypass | 8.6 |
| [GHSA-99qw-6mr3-36qr](https://github.com/advisories/GHSA-99qw-6mr3-36qr) | OpenClaw | [![Stars](https://img.shields.io/github/stars/openclaw/openclaw?style=social)](https://github.com/openclaw/openclaw/stargazers) | Code Execution | 8.5 |
| [GHSA-7h7g-x2px-94hj](https://github.com/advisories/GHSA-7h7g-x2px-94hj) | OpenClaw | [![Stars](https://img.shields.io/github/stars/openclaw/openclaw?style=social)](https://github.com/openclaw/openclaw/stargazers) | Credential Exposure | 6.9 |
| [GHSA-g2f6-pwvx-r275](https://github.com/openclaw/openclaw/security/advisories/GHSA-g2f6-pwvx-r275) | OpenClaw | [![Stars](https://img.shields.io/github/stars/openclaw/openclaw?style=social)](https://github.com/openclaw/openclaw/stargazers) | Command Injection | Medium |
| [GHSA-jq3f-vjww-8rq7](https://github.com/openclaw/openclaw/security/advisories/GHSA-jq3f-vjww-8rq7) | OpenClaw | [![Stars](https://img.shields.io/github/stars/openclaw/openclaw?style=social)](https://github.com/openclaw/openclaw/stargazers) | Resource Exhaustion | High |
| [GHSA-xwcj-hwhf-h378](https://github.com/openclaw/openclaw/security/advisories/GHSA-xwcj-hwhf-h378) | OpenClaw | [![Stars](https://img.shields.io/github/stars/openclaw/openclaw?style=social)](https://github.com/openclaw/openclaw/stargazers) | Information Disclosure | Medium |

| CVE 编号 | 项目 | 项目热度 | 漏洞类型 | CVSS |
|:---|:---|:---:|:---|:----:|
| [CVE-2026-1884](https://nvd.nist.gov/vuln/detail/cve-2026-1884) | Zentao PMS | [![Stars](https://img.shields.io/github/stars/easysoft/zentaopms?style=social)](https://github.com/easysoft/zentaopms/stargazers) | SSRF | 5.1  |
| [CVE-2025-13789](https://nvd.nist.gov/vuln/detail/CVE-2025-13789) | Zentao PMS | [![Stars](https://img.shields.io/github/stars/easysoft/zentaopms?style=social)](https://github.com/easysoft/zentaopms/stargazers) | SSRF | 5.3  |
| [CVE-2025-13787](https://nvd.nist.gov/vuln/detail/CVE-2025-13787) | Zentao PMS | [![Stars](https://img.shields.io/github/stars/easysoft/zentaopms?style=social)](https://github.com/easysoft/zentaopms/stargazers) | Privilege Escalation | 9.1  |
| [CVE-2025-64428](https://nvd.nist.gov/vuln/detail/CVE-2025-64428) | Dataease | [![Stars](https://img.shields.io/github/stars/dataease/dataease?style=social)](https://github.com/dataease/dataease/stargazers) | JNDI Injection | 9.8  |
| [CVE-2025-13246](https://nvd.nist.gov/vuln/detail/CVE-2025-13246) | Modulithshop | [![Stars](https://img.shields.io/github/stars/shsuishang/modulithshop?style=social)](https://github.com/shsuishang/modulithshop/stargazers) | SQL Injection | 6.3  |
| [CVE-2025-64163](https://nvd.nist.gov/vuln/detail/CVE-2025-64163) | Dataease | [![Stars](https://img.shields.io/github/stars/dataease/dataease?style=social)](https://github.com/dataease/dataease/stargazers) | SSRF | 9.8  |
| [CVE-2025-64164](https://nvd.nist.gov/vuln/detail/CVE-2025-64164) | Dataease | [![Stars](https://img.shields.io/github/stars/dataease/dataease?style=social)](https://github.com/dataease/dataease/stargazers) | JNDI Injection | 9.8  |
| [CVE-2025-11581](https://nvd.nist.gov/vuln/detail/CVE-2025-11581) | PowerJob | [![Stars](https://img.shields.io/github/stars/PowerJob/PowerJob?style=social)](https://github.com/PowerJob/PowerJob/stargazers) | Privilege Escalation | 7.5  |
| [CVE-2025-11580](https://nvd.nist.gov/vuln/detail/CVE-2025-11580) | PowerJob | [![Stars](https://img.shields.io/github/stars/PowerJob/PowerJob?style=social)](https://github.com/PowerJob/PowerJob/stargazers) | Privilege Escalation | 5.3  |
| [CVE-2025-10771](https://nvd.nist.gov/vuln/detail/CVE-2025-10771) | Jimureport | [![Stars](https://img.shields.io/github/stars/jeecgboot/JimuReport?style=social)](https://github.com/jeecgboot/JimuReport/stargazers) | Deserialization | 9.8  |
| [CVE-2025-10770](https://nvd.nist.gov/vuln/detail/CVE-2025-10770) | Jimureport | [![Stars](https://img.shields.io/github/stars/jeecgboot/JimuReport?style=social)](https://github.com/jeecgboot/JimuReport/stargazers) | Deserialization | 6.5  |
| [CVE-2025-10769](https://nvd.nist.gov/vuln/detail/CVE-2025-10769) | H2o-3 | [![Stars](https://img.shields.io/github/stars/h2oai/h2o-3?style=social)](https://github.com/h2oai/h2o-3/stargazers) | Deserialization | 9.8  |
| [CVE-2025-10768](https://nvd.nist.gov/vuln/detail/CVE-2025-10768) | H2o-3 | [![Stars](https://img.shields.io/github/stars/h2oai/h2o-3?style=social)](https://github.com/h2oai/h2o-3/stargazers) | Deserialization | 9.8  |
| [CVE-2025-58045](https://nvd.nist.gov/vuln/detail/CVE-2025-58045) | Dataease | [![Stars](https://img.shields.io/github/stars/dataease/dataease?style=social)](https://github.com/dataease/dataease/stargazers) | JNDI Injection | 9.8  |
| [CVE-2025-10423](https://nvd.nist.gov/vuln/detail/CVE-2025-10423) | Newbee-mall | [![Stars](https://img.shields.io/github/stars/newbee-ltd/newbee-mall?style=social)](https://github.com/newbee-ltd/newbee-mall/stargazers) | Guessable Captcha | 3.7  |
| [CVE-2025-10422](https://nvd.nist.gov/vuln/detail/CVE-2025-10422) | Newbee-mall | [![Stars](https://img.shields.io/github/stars/newbee-ltd/newbee-mall?style=social)](https://github.com/newbee-ltd/newbee-mall/stargazers) | Privilege Escalation | 4.3  |
| [CVE-2025-9835](https://nvd.nist.gov/vuln/detail/CVE-2025-9835) | Mall | [![Stars](https://img.shields.io/github/stars/macrozheng/mall?style=social)](https://github.com/macrozheng/mall/stargazers) | Privilege Escalation | 4.3  |
| [CVE-2025-9737](https://nvd.nist.gov/vuln/detail/CVE-2025-9737) | O2oa | [![Stars](https://img.shields.io/github/stars/o2oa/o2oa?style=social)](https://github.com/o2oa/o2oa/stargazers) | XSS | 5.4  |
| [CVE-2025-9736](https://nvd.nist.gov/vuln/detail/CVE-2025-9736) | O2oa | [![Stars](https://img.shields.io/github/stars/o2oa/o2oa?style=social)](https://github.com/o2oa/o2oa/stargazers) | XSS | 5.4  |
| [CVE-2025-9735](https://nvd.nist.gov/vuln/detail/CVE-2025-9735) | O2oa | [![Stars](https://img.shields.io/github/stars/o2oa/o2oa?style=social)](https://github.com/o2oa/o2oa/stargazers) | XSS | 5.4  |
| [CVE-2025-9734](https://nvd.nist.gov/vuln/detail/CVE-2025-9734) | O2oa | [![Stars](https://img.shields.io/github/stars/o2oa/o2oa?style=social)](https://github.com/o2oa/o2oa/stargazers) | XSS | 5.4  |
| [CVE-2025-9719](https://nvd.nist.gov/vuln/detail/CVE-2025-9719) | O2oa | [![Stars](https://img.shields.io/github/stars/o2oa/o2oa?style=social)](https://github.com/o2oa/o2oa/stargazers) | XSS | 5.4  |
| [CVE-2025-9718](https://nvd.nist.gov/vuln/detail/CVE-2025-9718) | O2oa | [![Stars](https://img.shields.io/github/stars/o2oa/o2oa?style=social)](https://github.com/o2oa/o2oa/stargazers) | XSS | 5.4  |
| [CVE-2025-9717](https://nvd.nist.gov/vuln/detail/CVE-2025-9717) | O2oa | [![Stars](https://img.shields.io/github/stars/o2oa/o2oa?style=social)](https://github.com/o2oa/o2oa/stargazers) | XSS | 5.4  |
| [CVE-2025-9716](https://nvd.nist.gov/vuln/detail/CVE-2025-9716) | O2oa | [![Stars](https://img.shields.io/github/stars/o2oa/o2oa?style=social)](https://github.com/o2oa/o2oa/stargazers) | XSS | 5.4  |
| [CVE-2025-9715](https://nvd.nist.gov/vuln/detail/CVE-2025-9715) | O2oa | [![Stars](https://img.shields.io/github/stars/o2oa/o2oa?style=social)](https://github.com/o2oa/o2oa/stargazers) | XSS | 5.4  |
| [CVE-2025-9683](https://nvd.nist.gov/vuln/detail/CVE-2025-9683) | O2oa | [![Stars](https://img.shields.io/github/stars/o2oa/o2oa?style=social)](https://github.com/o2oa/o2oa/stargazers) | XSS | 5.4  |
| [CVE-2025-9682](https://nvd.nist.gov/vuln/detail/CVE-2025-9682) | O2oa | [![Stars](https://img.shields.io/github/stars/o2oa/o2oa?style=social)](https://github.com/o2oa/o2oa/stargazers) | XSS | 5.4  |
| [CVE-2025-9681](https://nvd.nist.gov/vuln/detail/CVE-2025-9681) | O2oa | [![Stars](https://img.shields.io/github/stars/o2oa/o2oa?style=social)](https://github.com/o2oa/o2oa/stargazers) | XSS | 5.4  |
| [CVE-2025-9680](https://nvd.nist.gov/vuln/detail/CVE-2025-9680) | O2oa | [![Stars](https://img.shields.io/github/stars/o2oa/o2oa?style=social)](https://github.com/o2oa/o2oa/stargazers) | XSS | 5.4  |
| [CVE-2025-9659](https://nvd.nist.gov/vuln/detail/CVE-2025-9659) | O2oa | [![Stars](https://img.shields.io/github/stars/o2oa/o2oa?style=social)](https://github.com/o2oa/o2oa/stargazers) | XSS | 5.4  |
| [CVE-2025-9658](https://nvd.nist.gov/vuln/detail/CVE-2025-9658) | O2oa | [![Stars](https://img.shields.io/github/stars/o2oa/o2oa?style=social)](https://github.com/o2oa/o2oa/stargazers) | XSS | 5.4  |
| [CVE-2025-9657](https://nvd.nist.gov/vuln/detail/CVE-2025-9657) | O2oa | [![Stars](https://img.shields.io/github/stars/o2oa/o2oa?style=social)](https://github.com/o2oa/o2oa/stargazers) | XSS | 5.4  |
| [CVE-2025-9655](https://nvd.nist.gov/vuln/detail/CVE-2025-9655) | O2oa | [![Stars](https://img.shields.io/github/stars/o2oa/o2oa?style=social)](https://github.com/o2oa/o2oa/stargazers) | XSS | 5.4  |
| [CVE-2025-9646](https://nvd.nist.gov/vuln/detail/CVE-2025-9646) | O2oa | [![Stars](https://img.shields.io/github/stars/o2oa/o2oa?style=social)](https://github.com/o2oa/o2oa/stargazers) | XSS | 5.4  |
| [CVE-2025-9602](https://nvd.nist.gov/vuln/detail/CVE-2025-9602) | RockOA | [![Stars](https://img.shields.io/github/stars/rainrocka/xinhu?style=social)](https://github.com/rainrocka/xinhu/stargazers) | Database Backdoor | 6.5  |
| [CVE-2025-9514](https://nvd.nist.gov/vuln/detail/CVE-2025-9514) | Mall | [![Stars](https://img.shields.io/github/stars/macrozheng/mall?style=social)](https://github.com/macrozheng/mall/stargazers) | Privilege Escalation | 3.7  |
| [CVE-2025-9264](https://nvd.nist.gov/vuln/detail/CVE-2025-9264) | Xxl-job | [![Stars](https://img.shields.io/github/stars/xuxueli/xxl-job?style=social)](https://github.com/xuxueli/xxl-job/stargazers) | Privilege Escalation | 5.4  |
| [CVE-2025-9263](https://nvd.nist.gov/vuln/detail/CVE-2025-9263) | Xxl-job | [![Stars](https://img.shields.io/github/stars/xuxueli/xxl-job?style=social)](https://github.com/xuxueli/xxl-job/stargazers) | Privilege Escalation | 4.3  |
| [CVE-2025-9241](https://nvd.nist.gov/vuln/detail/CVE-2025-9241) | Eladmin | [![Stars](https://img.shields.io/github/stars/elunez/eladmin?style=social)](https://github.com/elunez/eladmin/stargazers) | CSV/XLSX Injection | 7.5  |
| [CVE-2025-9240](https://nvd.nist.gov/vuln/detail/CVE-2025-9240) | Eladmin | [![Stars](https://img.shields.io/github/stars/elunez/eladmin?style=social)](https://github.com/elunez/eladmin/stargazers) | Sensitive Information Disclosure | 4.3  |
| [CVE-2025-9239](https://nvd.nist.gov/vuln/detail/CVE-2025-9239) | Eladmin | [![Stars](https://img.shields.io/github/stars/elunez/eladmin?style=social)](https://github.com/elunez/eladmin/stargazers) | Hardcoded Credentials | 3.7  |
| [CVE-2025-8974](https://nvd.nist.gov/vuln/detail/CVE-2025-8974) | Litemall | [![Stars](https://img.shields.io/github/stars/linlinjava/litemall?style=social)](https://github.com/linlinjava/litemall/stargazers) | Hardcoded Credentials | 9.8  |
| [CVE-2025-8852](https://nvd.nist.gov/vuln/detail/CVE-2025-8852) | Wukong CRM | [![Stars](https://img.shields.io/github/stars/WuKongOpenSource/WukongCRM-11.0-JAVA?style=social)](https://github.com/WuKongOpenSource/WukongCRM-11.0-JAVA/stargazers) | Sensitive Information Disclosure | 4.3  |
| [CVE-2025-8840](https://nvd.nist.gov/vuln/detail/CVE-2025-8840) | Jsherp | [![Stars](https://img.shields.io/github/stars/jishenghua/jshERP?style=social)](https://github.com/jishenghua/jshERP/stargazers) | Privilege Escalation | 5.4  |
| [CVE-2025-8839](https://nvd.nist.gov/vuln/detail/CVE-2025-8839) | Jsherp | [![Stars](https://img.shields.io/github/stars/jishenghua/jshERP?style=social)](https://github.com/jishenghua/jshERP/stargazers) | Privilege Escalation | 8.8  |
| [CVE-2025-8764](https://nvd.nist.gov/vuln/detail/CVE-2025-8764) | Litemall | [![Stars](https://img.shields.io/github/stars/linlinjava/litemall?style=social)](https://github.com/linlinjava/litemall/stargazers) | XSS | 5.4  |
| [CVE-2025-8753](https://nvd.nist.gov/vuln/detail/CVE-2025-8753) | Litemall | [![Stars](https://img.shields.io/github/stars/linlinjava/litemall?style=social)](https://github.com/linlinjava/litemall/stargazers) | Arbitrary File Deletion | 5.4  |
| [CVE-2025-8708](https://nvd.nist.gov/vuln/detail/CVE-2025-8708) | White-Jotter | [![Stars](https://img.shields.io/github/stars/Antabot/White-Jotter?style=social)](https://github.com/Antabot/White-Jotter/stargazers) | Deserialization | 7.5  |

👉 [查看完整 CVE 列表详情](CVEList.md)

> *以上漏洞由 DeepAudit 团队成员 [@lintsinghua](https://github.com/lintsinghua) [@ez-lbz](https://github.com/ez-lbz) 使用 DeepAudit 挖掘发现*

> 如果您使用 DeepAudit 发现了漏洞，欢迎在  [Issues](https://github.com/lintsinghua/DeepAudit/issues/135)  中留言反馈。您的贡献将极大地丰富这份漏洞列表，非常感谢！

---

## ⚡ 项目概述

**DeepAudit** 是一个基于 **Multi-Agent 协作架构**的下一代代码安全审计平台。它不仅仅是一个静态扫描工具，而是模拟安全专家的思维模式，通过多个智能体（**Orchestrator**, **Recon**, **Analysis**, **Verification**）的自主协作，实现对代码的深度理解、漏洞挖掘和 **自动化沙箱 PoC 验证**。

我们致力于解决传统 SAST 工具的三大痛点：
- **误报率高** — 缺乏语义理解，大量误报消耗人力
- **业务逻辑盲点** — 无法理解跨文件调用和复杂逻辑
- **缺乏验证手段** — 不知道漏洞是否真实可利用

用户只需导入项目，DeepAudit 便全自动开始工作：识别技术栈 → 分析潜在风险 → 生成脚本 → 沙箱验证 → 生成报告，最终输出一份专业审计报告。

> **核心理念**: 让 AI 像黑客一样攻击，像专家一样防御。

## 💡 为什么选择 DeepAudit？

<div align="center">

| 😫 传统审计的痛点 | 💡 DeepAudit 解决方案 |
| :--- | :--- |
| **人工审计效率低**<br>跨不上 CI/CD 代码迭代速度，拖慢发布流程 | **🤖 Multi-Agent 自主审计**<br>AI 自动编排审计策略，全天候自动化执行 |
| **传统工具误报多**<br>缺乏语义理解，每天花费大量时间清洗噪音 | **🧠 RAG 知识库增强**<br>结合代码语义与上下文，大幅降低误报率 |
| **数据隐私担忧**<br>担心核心源码泄露给云端 AI，无法满足合规要求 | **🔒 支持 Ollama 本地部署**<br>数据不出内网，支持 Llama3/DeepSeek 等本地模型 |
| **无法确认真实性**<br>外包项目漏洞多，不知道哪些漏洞真实可被利用 | **💥 沙箱 PoC 验证**<br>自动生成并执行攻击脚本，确认漏洞真实危害 |

</div>

---

## 🏗️ 系统架构

### 整体架构图

DeepAudit 采用微服务架构，核心由 Multi-Agent 引擎驱动。

<div align="center">
<img src="frontend/public/images/README-show/架构图.png" alt="DeepAudit 架构图" width="90%">
</div>

### 🔄 审计工作流

| 步骤 | 阶段 | 负责 Agent | 主要动作 |
|:---:|:---:|:---:|:---|
| 1 | **策略规划** | **Orchestrator** | 接收审计任务，分析项目类型，制定审计计划，下发任务给子 Agent |
| 2 | **信息收集** | **Recon Agent** | 扫描项目结构，识别框架/库/API，提取攻击面（Entry Points） |
| 3 | **漏洞挖掘** | **Analysis Agent** | 结合 RAG 知识库与 AST 分析，深度审查代码，发现潜在漏洞 |
| 4 | **PoC 验证** | **Verification Agent** | **(关键)** 编写 PoC 脚本，在 Docker 沙箱中执行。如失败则自我修正重试 |
| 5 | **报告生成** | **Orchestrator** | 汇总所有发现，剔除被验证为误报的漏洞，生成最终报告 |

### 📂 项目代码结构

```text
DeepAudit/
├── backend/                        # Python FastAPI 后端
│   ├── app/
│   │   ├── agents/                 # Multi-Agent 核心逻辑
│   │   │   ├── orchestrator.py     # 总指挥：任务编排
│   │   │   ├── recon.py            # 侦察兵：资产识别
│   │   │   ├── analysis.py         # 分析师：漏洞挖掘
│   │   │   └── verification.py     # 验证者：沙箱 PoC
│   │   ├── core/                   # 核心配置与沙箱接口
│   │   ├── models/                 # 数据库模型
│   │   └── services/               # RAG, LLM 服务封装
│   └── tests/                      # 单元测试
├── frontend/                       # React + TypeScript 前端
│   ├── src/
│   │   ├── components/             # UI 组件库
│   │   ├── pages/                  # 页面路由
│   │   └── stores/                 # Zustand 状态管理
├── docker/                         # Docker 部署配置
│   ├── sandbox/                    # 安全沙箱镜像构建
│   └── postgres/                   # 数据库初始化
└── docs/                           # 详细文档
```

---

## 🚀 快速开始

### 方式一：一行命令部署（推荐）

使用预构建的 Docker 镜像，无需克隆代码，一行命令即可启动：

```bash
curl -fsSL https://raw.githubusercontent.com/lintsinghua/DeepAudit/v3.0.0/docker-compose.prod.yml | docker compose -f - up -d
```

## 🇨🇳 国内加速部署（作者亲测非常无敌之快）

使用南京大学镜像站加速拉取 Docker 镜像（将 `ghcr.io` 替换为 `ghcr.nju.edu.cn`）：

```bash
# 国内加速版 - 使用南京大学 GHCR 镜像站
curl -fsSL https://raw.githubusercontent.com/lintsinghua/DeepAudit/v3.0.0/docker-compose.prod.cn.yml | docker compose -f - up -d
```
<details>
<summary>手动拉取镜像（如需单独拉取）（点击展开）</summary>

```bash
# 前端镜像
docker pull ghcr.nju.edu.cn/lintsinghua/deepaudit-frontend:latest

# 后端镜像
docker pull ghcr.nju.edu.cn/lintsinghua/deepaudit-backend:latest

# 沙箱镜像
docker pull ghcr.nju.edu.cn/lintsinghua/deepaudit-sandbox:latest
```
</details>

> 💡 镜像源由 [南京大学开源镜像站](https://mirrors.nju.edu.cn/) 提供支持

<details>
<summary>💡 配置 Docker 镜像加速（可选，进一步提升拉取速度）（点击展开）</summary>

如果拉取镜像仍然较慢，可以配置 Docker 镜像加速器。编辑 Docker 配置文件并添加以下镜像源：

**Linux / macOS**：编辑 `/etc/docker/daemon.json`

**Windows**：右键 Docker Desktop 图标 → Settings → Docker Engine

```json
{
  "registry-mirrors": [
    "https://docker.1ms.run",
    "https://dockerproxy.com",
    "https://hub.rat.dev"
  ]
}
```

保存后重启 Docker 服务：

```bash
# Linux
sudo systemctl restart docker

# macOS / Windows
# 重启 Docker Desktop 应用
```

</details>

> 🎉 **启动成功！** 访问 http://localhost:3000 开始体验。

---

### 方式二：克隆代码部署

适合需要自定义配置或二次开发的用户：

```bash
# 1. 克隆项目
git clone https://github.com/lintsinghua/DeepAudit.git && cd DeepAudit

# 2. 配置环境变量
cp backend/env.example backend/.env
# 编辑 backend/.env 填入你的 LLM API Key

# 3. 一键启动
docker compose up -d
```

> 首次启动会自动构建沙箱镜像，可能需要几分钟。

---

## 🔧 源码开发指南

适合开发者进行二次开发调试。

### 环境要求
- Python 3.11+
- Node.js 20+
- PostgreSQL 15+
- Docker (用于沙箱)


### 1. 手动启动数据库

```bash
docker compose up -d redis db adminer
```

### 2. 后端启动



```bash
cd backend
# 配置环境
cp env.example .env

# 使用 uv 管理环境（推荐）
uv sync
source .venv/bin/activate

# 启动 API 服务
uvicorn app.main:app --reload
```

### 3. 前端启动

```bash
cd frontend
# 配置环境
cp .env.example .env

pnpm install
pnpm dev
```

### 3. 沙箱环境

开发模式下需要本地 Docker 拉取沙箱镜像：

```bash
# 标准拉取
docker pull ghcr.io/lintsinghua/deepaudit-sandbox:latest

# 国内加速（南京大学镜像站）
docker pull ghcr.nju.edu.cn/lintsinghua/deepaudit-sandbox:latest
```

---

## 🤖 Multi-Agent 智能审计

### 支持的漏洞类型

<table>
<tr>
<td>

| 漏洞类型 | 描述 |
|---------|------|
| `sql_injection` | SQL 注入 |
| `xss` | 跨站脚本攻击 |
| `command_injection` | 命令注入 |
| `path_traversal` | 路径遍历 |
| `ssrf` | 服务端请求伪造 |
| `xxe` | XML 外部实体注入 |

</td>
<td>

| 漏洞类型 | 描述 |
|---------|------|
| `insecure_deserialization` | 不安全反序列化 |
| `hardcoded_secret` | 硬编码密钥 |
| `weak_crypto` | 弱加密算法 |
| `authentication_bypass` | 认证绕过 |
| `authorization_bypass` | 授权绕过 |
| `idor` | 不安全直接对象引用 |

</td>
</tr>
</table>

> 📖 详细文档请查看 **[Agent 审计指南](docs/AGENT_AUDIT.md)**

---

## 🔌 支持的 LLM 平台

<table>
<tr>
<td align="center" width="33%">
<h3>🌍 国际平台</h3>
<p>
OpenAI GPT-4o / GPT-4<br/>
Claude 3.5 Sonnet / Opus<br/>
Google Gemini Pro<br/>
DeepSeek V3
</p>
</td>
<td align="center" width="33%">
<h3>🇨🇳 国内平台</h3>
<p>
通义千问 Qwen<br/>
智谱 GLM-4<br/>
Moonshot Kimi<br/>
文心一言 · MiniMax · 豆包
</p>
</td>
<td align="center" width="33%">
<h3>🏠 本地部署</h3>
<p>
<strong>Ollama</strong><br/>
Llama3 · Qwen2.5 · CodeLlama<br/>
DeepSeek-Coder · Codestral<br/>
<em>代码不出内网</em>
</p>
</td>
</tr>
</table>

💡 支持 API 中转站，解决网络访问问题 | 详细配置 → [LLM 平台支持](docs/LLM_PROVIDERS.md)

---

## 🎯 功能矩阵

| 功能 | 说明 | 模式 |
|------|------|------|
| 🤖 **Agent 深度审计** | Multi-Agent 协作，自主编排审计策略 | Agent |
| 🧠 **RAG 知识增强** | 代码语义理解，CWE/CVE 知识库检索 | Agent |
| 🔒 **沙箱 PoC 验证** | Docker 隔离执行，验证漏洞有效性 | Agent |
| 🗂️ **项目管理** | GitHub/GitLab/Gitea 导入，ZIP 上传，10+ 语言支持 | 通用 |
| ⚡ **即时分析** | 代码片段秒级分析，粘贴即用 | 通用 |
| 🔍 **五维检测** | Bug · 安全 · 性能 · 风格 · 可维护性 | 通用 |
| 💡 **What-Why-How** | 精准定位 + 原因解释 + 修复建议 | 通用 |
| 📋 **审计规则** | 内置 OWASP Top 10，支持自定义规则集 | 通用 |
| 📝 **提示词模板** | 可视化管理，支持中英文双语 | 通用 |
| 📊 **报告导出** | PDF / Markdown / JSON 一键导出 | 通用 |
| ⚙️ **运行时配置** | 浏览器配置 LLM，无需重启服务 | 通用 |

## 🦖 发展路线图

我们正在持续演进，未来将支持更多语言和更强大的 Agent 能力。

- [x] 基础静态分析，集成 Semgrep
- [x] 引入 RAG 知识库，支持 Docker 安全沙箱
- [x] **Multi-Agent 协作架构** (Current)
- [ ] 支持更真实的模拟服务环境，进行更真实漏洞验证流程
- [ ] 沙箱从function_call优化集成为稳定MCP服务
- [ ] **自动修复 (Auto-Fix)**: Agent 直接提交 PR 修复漏洞
- [ ] **增量PR审计**: 持续跟踪 PR 变更，智能分析漏洞，并集成CI/CD流程
- [ ] **优化RAG**: 支持自定义知识库

---

## 🤝 贡献与社区

### 贡献指南
我们非常欢迎您的贡献！无论是提交 Issue、PR 还是完善文档。
请查看 [CONTRIBUTING.md](./CONTRIBUTING.md) 了解详情。

### 📬 联系作者

<div align="center">

**欢迎大家来和我交流探讨！无论是技术问题、功能建议还是合作意向，都期待与你沟通~**
（平台定制、代码审计服务、技术咨询、合作洽谈等请通过邮箱联系）
| 联系方式 | |
|:---:|:---:|
| 📧 **邮箱** | **lintsinghua@qq.com** |
| 🐙 **GitHub** | [@lintsinghua](https://github.com/lintsinghua) |

</div>

## 📄 许可证

本项目采用 [AGPL-3.0 License](LICENSE) 开源。

## 📈 项目热度

<a href="https://star-history.com/#lintsinghua/DeepAudit&Date">
 <picture>
   <source media="(prefers-color-scheme: dark)" srcset="https://api.star-history.com/svg?repos=lintsinghua/DeepAudit&type=Date&theme=dark" />
   <source media="(prefers-color-scheme: light)" srcset="https://api.star-history.com/svg?repos=lintsinghua/DeepAudit&type=Date" />
   <img alt="Star History Chart" src="https://api.star-history.com/svg?repos=lintsinghua/DeepAudit&type=Date" />
 </picture>
</a>

---

<div align="center">
  <strong>Made with ❤️ by <a href="https://github.com/lintsinghua">lintsinghua</a></strong>
</div>

---

## 致谢

感谢以下开源项目的支持：

[FastAPI](https://fastapi.tiangolo.com/) · [LangChain](https://langchain.com/) · [LangGraph](https://langchain-ai.github.io/langgraph/) · [ChromaDB](https://www.trychroma.com/) · [LiteLLM](https://litellm.ai/) · [Tree-sitter](https://tree-sitter.github.io/) · [Kunlun-M](https://github.com/LoRexxar/Kunlun-M) · [Strix](https://github.com/usestrix/strix) · [React](https://react.dev/) · [Vite](https://vitejs.dev/) · [Radix UI](https://www.radix-ui.com/) · [TailwindCSS](https://tailwindcss.com/) · [shadcn/ui](https://ui.shadcn.com/)

---

## ⚠️ 重要安全声明

### 法律合规声明
1. 禁止**任何未经授权的漏洞测试、渗透测试或安全评估**
2. 本项目仅供网络空间安全学术研究、教学和学习使用
3. 严禁将本项目用于任何非法目的或未经授权的安全测试

### 漏洞上报责任
1. 发现任何安全漏洞时，请及时通过合法渠道上报
2. 严禁利用发现的漏洞进行非法活动
3. 遵守国家网络安全法律法规，维护网络空间安全

### 使用限制
- 仅限在授权环境下用于教育和研究目的
- 禁止用于对未授权系统进行安全测试
- 使用者需对自身行为承担全部法律责任

### 免责声明
作者不对任何因使用本项目而导致的直接或间接损失负责，使用者需对自身行为承担全部法律责任。

---

## 📖 详细安全政策

有关安装政策、免责声明、代码隐私、API使用安全和漏洞报告的详细信息，请参阅 [DISCLAIMER.md](DISCLAIMER.md) 和 [SECURITY.md](SECURITY.md) 文件。

### 快速参考
- **代码隐私警告**: 您的代码将被发送到所选择的LLM服务商服务器
- **敏感代码处理**: 使用本地模型处理敏感代码
- **合规要求**: 遵守数据保护和隐私法律法规
- **漏洞报告**: 发现安全问题请通过合法渠道上报

# DeepAudit 项目修改清单 - 完整版

## 📋 问题概览

| 问题 | 严重性 | 影响范围 | 修复难度 |
|------|--------|---------|---------|
| 1. 知识库错位 (Web2 vs Web3) | 🔴 Critical | Analysis Agent | 中等 |
| 2. 错误提示误导 | 🟠 High | 所有 Agent | 低 |
| 3. Agent 幻觉 (调用不存在的工具) | 🔴 Critical | Verification Agent | 中等 |
| 4. 上下文污染 (Token 消耗) | 🟠 High | 所有 Agent | 高 |
| 5. PoC 编写缺陷 (Foundry) | 🟠 High | Verification Agent | 中等 |

---

## 🔴 问题1: 知识库内容严重错位

### 根源
- 文件: `backend/app/services/agent/knowledge/vulnerabilities/__init__.py`
- 问题: Web2 漏洞库（SQL注入、XSS）与 Web3 漏洞库混在一起
- 表现: Analysis Agent 查询 delegatecall 漏洞时，返回的是 sql_injection, xss_reflected 等

### 修改清单

#### 1.1 分离知识库
**文件**: `backend/app/services/agent/knowledge/vulnerabilities/__init__.py`

**操作**:
- [ ] 创建 `WEB2_VULNERABILITY_DOCS` 列表，包含: SQL_INJECTION, NOSQL_INJECTION, XSS_*, CSRF, SSRF 等
- [ ] 创建 `WEB3_VULNERABILITY_DOCS` 列表，包含: ACCESS_CONTROL, INTEGER_OVERFLOW_UNDERFLOW, FLASH_LOAN, REENTRANCY 等
- [ ] 添加 `get_vulnerability_docs_for_audit_type(audit_type)` 函数
- [ ] 将 `ALL_VULNERABILITY_DOCS` 默认指向 `WEB3_VULNERABILITY_DOCS`

#### 1.2 更新 RAG 知识库初始化
**文件**: `backend/app/services/agent/knowledge/rag_knowledge.py`

**操作**:
- [ ] 在 `_load_builtin_knowledge()` 中添加审计类型检测
- [ ] 根据审计类型加载对应的漏洞知识库
- [ ] 添加 `_get_audit_type()` 方法，从 Agent 上下文获取审计类型

#### 1.3 更新工具的漏洞类型列表
**文件**: `backend/app/services/agent/knowledge/tools.py`

**操作**:
- [ ] 更新 `GetVulnerabilityKnowledgeTool.description` 中的漏洞类型列表
- [ ] 删除所有 Web2 漏洞类型（sql_injection, xss, csrf 等）
- [ ] 添加 Web3 特定漏洞类型（access_control, flash_loan, proxy_upgradeability 等）

#### 1.4 更新 System Prompt
**文件**: `backend/app/services/agent/prompts/system_prompts.py`

**操作**:
- [ ] 在 `ANALYSIS_SYSTEM_PROMPT` 中更新"重点关注的漏洞类型"部分
- [ ] 删除 Web2 漏洞（SQL注入、XSS、CSRF）
- [ ] 添加 Web3 漏洞（重入、闪电贷、代理升级、整数溢出等）

---

## 🟠 问题2: 系统错误提示存在严重误导

### 根源
- 文件: `backend/app/services/agent/core/fallback.py`, `backend/app/services/agent/core/errors.py`
- 问题: foundry_test 失败时，系统给出的是 read_file 的恢复建议
- 表现: "尝试使用不同的参数（如指定较小的行范围）" 被拼接到编译错误中

### 修改清单

#### 2.1 创建工具特定的错误处理
**文件**: `backend/app/services/agent/core/errors.py`

**操作**:
- [ ] 添加 `TOOL_SPECIFIC_RECOVERY_HINTS` 字典，包含各工具的错误恢复建议
- [ ] 为 foundry_test 添加: compilation_error, execution_error, timeout 等错误类型的建议
- [ ] 为 read_file 添加: file_not_found, line_out_of_range 等错误类型的建议
- [ ] 创建 `ToolSpecificError` 类，自动拼接工具特定的恢复建议

#### 2.2 更新 Foundry 工具的错误处理
**文件**: `backend/app/services/agent/tools/foundry_tools.py`

**操作**:
- [ ] 在 `_execute()` 方法中添加错误类型判断逻辑
- [ ] 根据 stderr 内容判断是 compilation_error 还是 execution_error
- [ ] 使用 `ToolSpecificError` 抛出工具特定的错误
- [ ] 确保错误消息中包含工具特定的恢复建议

#### 2.3 更新其他工具的错误处理
**文件**: `backend/app/services/agent/tools/file_tool.py`

**操作**:
- [ ] 为 read_file 添加 file_not_found 错误处理
- [ ] 为 read_file 添加 line_out_of_range 错误处理
- [ ] 使用 `ToolSpecificError` 抛出错误

---

## 🔴 问题3: Agent 幻觉 - 调用不存在的工具

### 根源
- 文件: `backend/app/services/agent/prompts/system_prompts.py`
- 问题: System Prompt 中错误地暗示了 analyze_file, create_vulnerability_report 等不存在的工具
- 表现: Agent 调用 analyze_file 时报错 "工具不存在"

### 修改清单

#### 3.1 审计 System Prompt 中的工具列表
**文件**: `backend/app/services/agent/prompts/system_prompts.py`

**操作**:
- [ ] 检查 `VERIFICATION_SYSTEM_PROMPT` 中的工具列表
- [ ] 删除虚假工具: analyze_file, create_vulnerability_report, execute_poc
- [ ] 确保只列出实际存在的工具: read_file, write_file, list_files, search_code, foundry_test, think, reflect
- [ ] 检查 `ANALYSIS_SYSTEM_PROMPT` 中的工具列表
- [ ] 确保 Analysis Agent 的工具列表不包含 Verification Agent 的工具

#### 3.2 创建工具注册表和验证机制
**文件**: `backend/app/services/agent/core/registry.py`

**操作**:
- [ ] 添加 `ToolRegistry` 类，管理工具注册
- [ ] 添加 `register_tool()` 方法，支持按 Agent 类型注册工具
- [ ] 添加 `get_available_tools()` 方法，获取特定 Agent 类型的可用工具
- [ ] 添加 `validate_tool_call()` 方法，验证工具调用是否合法
- [ ] 添加 `get_tool_not_found_error()` 方法，生成清晰的错误消息

#### 3.3 在 Agent 执行器中添加工具验证
**文件**: `backend/app/services/agent/core/executor.py`

**操作**:
- [ ] 在 `execute_tool()` 方法中添加工具验证逻辑
- [ ] 调用 `tool_registry.validate_tool_call()` 验证工具
- [ ] 如果工具不存在，返回清晰的错误消息，列出可用工具
- [ ] 记录工具调用的验证结果

#### 3.4 初始化工具注册表
**文件**: `backend/app/services/agent/agents/base.py`

**操作**:
- [ ] 在 Agent 初始化时，注册该 Agent 类型的所有可用工具
- [ ] Verification Agent 注册: read_file, write_file, list_files, search_code, foundry_test, think, reflect
- [ ] Analysis Agent 注册: read_file, list_files, search_code, query_security_knowledge, get_vulnerability_knowledge, think, reflect
- [ ] Recon Agent 注册: read_file, list_files, search_code, think, reflect

---

## 🟠 问题4: 极高 Token 消耗与上下文污染

### 根源
- 文件: `backend/app/services/agent/core/context.py`, `backend/app/services/agent/core/executor.py`
- 问题: 缺乏上下文裁剪机制，每次失败的完整错误栈都被保留在对话历史中
- 表现: Verification Agent 验证一个漏洞消耗 151,792 tokens，进行了 10 轮思考

### 修改清单

#### 4.1 创建上下文管理器
**文件**: `backend/app/services/agent/core/context.py`

**操作**:
- [ ] 添加 `ContextManager` 类，管理 Agent 的对话历史
- [ ] 添加 `max_history_length` 参数，限制保留的消息数量
- [ ] 添加 `max_context_tokens` 参数，限制上下文的总 token 数
- [ ] 添加 `prune_context()` 方法，根据重要性裁剪上下文
- [ ] 添加 `compress_error_messages()` 方法，压缩冗长的错误消息

#### 4.2 实现上下文裁剪策略
**文件**: `backend/app/services/agent/core/context.py`

**操作**:
- [ ] 实现"保留最近 N 条消息"的策略
- [ ] 实现"保留最重要的消息"的策略（基于消息类型和内容）
- [ ] 实现"压缩重复错误"的策略（如多次相同的编译错误）
- [ ] 实现"删除冗长的代码片段"的策略（只保留关键行）

#### 4.3 在 Agent 执行器中集成上下文管理
**文件**: `backend/app/services/agent/core/executor.py`

**操作**:
- [ ] 在每次 LLM 调用前，检查上下文大小
- [ ] 如果超过 `max_context_tokens`，调用 `prune_context()`
- [ ] 记录上下文裁剪的统计信息（删除了多少 tokens）
- [ ] 在日志中输出上下文大小和裁剪情况

#### 4.4 优化错误消息格式
**文件**: `backend/app/services/agent/tools/foundry_tools.py`

**操作**:
- [ ] 压缩 foundry_test 的 stderr 输出，只保留关键错误行
- [ ] 删除重复的错误消息
- [ ] 限制错误消息的最大长度（如 2000 字符）
- [ ] 添加"完整错误日志"的链接，而不是直接输出

#### 4.5 添加重试限制和早期退出
**文件**: `backend/app/services/agent/core/retry.py`

**操作**:
- [ ] 添加 `max_retries` 参数，限制重试次数（如 3 次）
- [ ] 添加 `early_exit_on_repeated_error` 参数，如果连续出现相同错误则退出
- [ ] 添加 `backoff_strategy` 参数，实现指数退避
- [ ] 在达到重试限制时，返回清晰的失败消息

---

## 🔴 问题5: PoC 编写逻辑缺乏 Foundry 深度认知

### 根源
- 文件: `backend/app/services/agent/agents/smart_contract_verification.py`
- 问题: Agent 使用底层 EVM 语法（如 sstore, call）而不是 Foundry Cheatcodes
- 表现: 编写的 PoC 代码无法编译或执行失败

### 修改清单

#### 5.1 创建 Foundry Cheatcodes 知识库
**文件**: `backend/app/services/agent/knowledge/vulnerabilities/SC_foundry_cheatcodes.py`

**操作**:
- [ ] 创建新文件，包含 Foundry Cheatcodes 的完整文档
- [ ] 包含常用 Cheatcodes: vm.deal, vm.prank, vm.store, vm.startPrank, vm.stopPrank
- [ ] 包含高级 Cheatcodes: vm.expectRevert, vm.expectEmit, vm.mockCall
- [ ] 包含每个 Cheatcode 的使用示例和最佳实践

#### 5.2 更新 Verification Agent 的 System Prompt
**文件**: `backend/app/services/agent/prompts/system_prompts.py`

**操作**:
- [ ] 在 `VERIFICATION_SYSTEM_PROMPT` 中添加"Foundry PoC 编写铁律"部分
- [ ] 添加"必须使用 Cheatcodes 而不是底层 EVM 语法"的强制要求
- [ ] 添加常见错误模式和正确做法的对比
- [ ] 添加"console.log 输出格式"的严格要求（如 "Profit: XXX"）

#### 5.3 创建 Foundry PoC 模板
**文件**: `backend/app/services/agent/knowledge/templates/foundry_poc_template.sol`

**操作**:
- [ ] 创建标准的 Foundry PoC 模板
- [ ] 包含正确的 SPDX 声明、pragma、导入
- [ ] 包含 setUp() 函数的标准结构
- [ ] 包含 testExploit() 函数的标准结构
- [ ] 包含常见的 Cheatcodes 使用示例

#### 5.4 添加 PoC 验证工具
**文件**: `backend/app/services/agent/tools/poc_validator.py`

**操作**:
- [ ] 创建 `POCValidator` 工具，在执行前验证 PoC 代码
- [ ] 检查是否包含必要的导入和声明
- [ ] 检查是否正确使用了 Cheatcodes
- [ ] 检查是否有明显的语法错误
- [ ] 提供改进建议

#### 5.5 优化 Foundry 工具的反馈
**文件**: `backend/app/services/agent/tools/foundry_tools.py`

**操作**:
- [ ] 改进错误消息的可读性
- [ ] 提取关键错误行（如行号、错误类型）
- [ ] 提供针对性的修复建议
- [ ] 记录成功的 PoC 代码作为参考

---

## 📝 实施顺序建议

### 第一阶段（高优先级，立即修复）
1. **问题3: Agent 幻觉** - 防止调用不存在的工具
   - 修改 System Prompt，删除虚假工具
   - 添加工具验证机制
   - 预计时间: 2-3 小时

2. **问题2: 错误提示误导** - 改善用户体验
   - 创建工具特定的错误处理
   - 更新 Foundry 工具的错误消息
   - 预计时间: 2-3 小时

### 第二阶段（中优先级，本周完成）
3. **问题1: 知识库错位** - 确保正确的知识库
   - 分离 Web2 和 Web3 漏洞库
   - 更新 RAG 初始化逻辑
   - 预计时间: 3-4 小时

4. **问题5: PoC 编写缺陷** - 提高 PoC 质量
   - 创建 Foundry Cheatcodes 知识库
   - 更新 System Prompt
   - 创建 PoC 模板和验证工具
   - 预计时间: 4-5 小时

### 第三阶段（优化，下周完成）
5. **问题4: 上下文污染** - 优化 Token 消耗
   - 创建上下文管理器
   - 实现上下文裁剪策略
   - 添加重试限制
   - 预计时间: 5-6 小时

---

## 🧪 测试清单

### 问题1 测试
- [ ] 测试 Analysis Agent 查询 Web3 漏洞知识
- [ ] 验证返回的漏洞类型是 Web3 特定的
- [ ] 测试 Analysis Agent 查询 Web2 漏洞知识（如果支持）
- [ ] 验证返回的漏洞类型是 Web2 特定的

### 问题2 测试
- [ ] 测试 foundry_test 编译失败时的错误消息
- [ ] 验证错误消息包含 Foundry 特定的恢复建议
- [ ] 测试 read_file 行号超出范围时的错误消息
- [ ] 验证错误消息包含 read_file 特定的恢复建议

### 问题3 测试
- [ ] 测试 Agent 调用不存在的工具时的错误消息
- [ ] 验证错误消息列出了可用的工具
- [ ] 测试 System Prompt 中的工具列表是否准确
- [ ] 验证没有虚假工具引用

### 问题4 测试
- [ ] 测试长时间运行的 Agent 任务
- [ ] 验证上下文大小不会无限增长
- [ ] 测试上下文裁剪后 Agent 仍能正常工作
- [ ] 验证 Token 消耗显著降低

### 问题5 测试
- [ ] 测试 PoC 代码是否使用了 Cheatcodes
- [ ] 验证 PoC 代码能够编译
- [ ] 验证 PoC 代码能够执行
- [ ] 测试 console.log 输出格式是否正确

---

## 📚 参考资源

- Foundry 官方文档: https://book.getfoundry.sh/
- Foundry Cheatcodes: https://book.getfoundry.sh/cheatcodes/
- Smart Contract Security: https://docs.openzeppelin.com/contracts/
- OWASP Smart Contract Top 10: https://owasp.org/www-project-smart-contract-top-10/


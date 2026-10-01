"""
报告生成服务 - 多格式 + 统计概览 (WeasyPrint + Jinja2)

支持 PDF / Markdown / HTML / JSON 四种格式输出。
PDF 走 WeasyPrint（保留既有能力）；MD / HTML / JSON 走纯模板输出，无系统依赖。

⭐ M3 增强:
- 统计概览区（按严重级别分布、按问题类型分布、Top 问题）
- 四种导出格式
"""

import io
import json
import html
from datetime import datetime
from typing import List, Dict, Any, Optional
import math
import os
import sys
import base64

# macOS Homebrew compatibility fix
if sys.platform == 'darwin':
    os.environ['DYLD_FALLBACK_LIBRARY_PATH'] = '/opt/homebrew/lib:' + os.environ.get('DYLD_FALLBACK_LIBRARY_PATH', '')

from jinja2 import Template
from weasyprint import HTML
from weasyprint.text.fonts import FontConfiguration

# 支持的导出格式
SUPPORTED_FORMATS = ("pdf", "markdown", "md", "html", "json")

# 严重级别排序与配色
SEVERITY_ORDER = {'critical': 0, 'high': 1, 'medium': 2, 'low': 3, 'info': 4}
SEVERITY_LABELS = {
    'critical': 'CRITICAL',
    'high': 'HIGH',
    'medium': 'MEDIUM',
    'low': 'LOW',
    'info': 'INFO'
}
SEVERITY_COLORS = {
    'critical': '#dc2626',
    'high': '#ea580c',
    'medium': '#d97706',
    'low': '#65a30d',
    'info': '#2563eb'
}


class ReportGenerator:
    """
    基于 HTML/CSS 的专业报告生成器
    风格：严谨、高密度、企业级审计报告风格
    支持：PDF (WeasyPrint) / Markdown / HTML / JSON
    """

    # --- HTML 模板 (PDF) ---
    _TEMPLATE = """
    <!DOCTYPE html>
    <html lang="zh-CN">
    <head>
        <meta charset="UTF-8">
        <title>代码审计报告</title>
        <style>
            @page {
                size: A4;
                margin: 2.5cm 2cm;
                @top-left {
                    content: element(logoRunning);
                    vertical-align: middle;
                }
                @top-right {
                    content: "DeepAudit Audit Report";
                    font-size: 8pt;
                    color: #666;
                    font-family: sans-serif;
                    vertical-align: middle;
                }
                @bottom-center {
                    content: counter(page);
                    font-size: 9pt;
                    font-family: serif;
                }
            }

            body {
                font-family: "Songti SC", "SimSun", "Times New Roman", serif;
                color: #000;
                line-height: 1.3;
                font-size: 10pt;
                margin: 0;
            }

            .running-logo {
                position: running(logoRunning);
                height: 30px;
                width: auto;
                margin-bottom: 10px;
            }

            .header {
                padding-bottom: 10px;
                display: table;
                width: 100%;
            }

            .header-line {
                border-bottom: 2px solid #000;
                margin-bottom: 20px;
                margin-top: 5px;
            }

            .header-left {
                display: table-cell;
                vertical-align: middle;
            }

            .title-group {
                display: block;
                vertical-align: middle;
            }

            .title {
                font-size: 18pt;
                font-weight: bold;
                font-family: sans-serif;
                margin: 0 0 5px 0;
                color: #000;
                line-height: 1.1;
            }

            .subtitle {
                font-size: 10pt;
                color: #444;
                font-family: sans-serif;
                margin: 0;
                line-height: 1.3;
            }

            .meta-info {
                display: table-cell;
                text-align: right;
                vertical-align: middle;
                font-size: 9pt;
                color: #333;
                width: 250px;
            }

            .meta-item {
                margin-bottom: 2px;
            }

            .text-right { text-align: right; }
            .text-center { text-align: center; }
            .bold { font-weight: bold; }
            .mono { font-family: "Menlo", "Consolas", "Courier New", "PingFang SC", "Microsoft YaHei", monospace; }

            .section-header {
                font-size: 11pt;
                font-weight: bold;
                font-family: sans-serif;
                border-left: 4px solid #000;
                padding-left: 8px;
                margin-top: 25px;
                margin-bottom: 10px;
                background-color: #f3f4f6;
                padding-top: 5px;
                padding-bottom: 5px;
            }

            .score-box {
                border: 1px solid #000;
                padding: 15px;
                margin-bottom: 20px;
                display: table;
                width: 100%;
                box-sizing: border-box;
            }

            .score-left {
                display: table-cell;
                vertical-align: middle;
                width: 40%;
            }

            .score-right {
                display: table-cell;
                vertical-align: middle;
                text-align: right;
                width: 60%;
            }

            .score-val {
                font-size: 24pt;
                font-weight: bold;
                font-family: sans-serif;
                line-height: 1;
            }

            .stats-table {
                width: 100%;
                border-collapse: collapse;
            }

            .stats-table td {
                text-align: center;
                padding: 0 10px;
                border-left: 1px solid #ddd;
            }

            .stats-table td:first-child {
                border-left: none;
            }

            .stat-label {
                font-size: 8pt;
                color: #666;
                text-transform: uppercase;
                margin-bottom: 3px;
                display: block;
            }

            .stat-value {
                font-size: 11pt;
                font-weight: bold;
                display: block;
            }

            /* ===== 统计概览 ===== */
            .overview-grid {
                display: table;
                width: 100%;
                table-layout: fixed;
                margin-bottom: 6px;
            }

            .overview-cell {
                display: table-cell;
                vertical-align: top;
                padding-right: 14px;
            }

            .overview-cell:last-child {
                padding-right: 0;
            }

            .ov-card {
                border: 1px solid #e5e7eb;
                padding: 10px 12px;
                margin-bottom: 12px;
                break-inside: avoid;
            }

            .ov-title {
                font-size: 9.5pt;
                font-weight: bold;
                font-family: sans-serif;
                text-transform: uppercase;
                letter-spacing: .04em;
                margin-bottom: 8px;
                color: #111;
                border-bottom: 1px solid #eee;
                padding-bottom: 5px;
            }

            .sev-row {
                margin-bottom: 6px;
            }

            .sev-top {
                display: table;
                width: 100%;
                font-size: 8.5pt;
                font-family: sans-serif;
                margin-bottom: 2px;
            }

            .sev-name {
                display: table-cell;
                width: 38%;
                font-weight: bold;
            }

            .sev-num {
                display: table-cell;
                text-align: right;
                font-weight: bold;
            }

            .sev-bar-bg {
                height: 6px;
                background: #f1f1f1;
                border-radius: 3px;
                overflow: hidden;
            }

            .sev-bar {
                height: 6px;
                border-radius: 3px;
            }

            .type-list {
                font-size: 8.5pt;
            }

            .type-row {
                display: table;
                width: 100%;
                margin-bottom: 4px;
            }

            .type-name {
                display: table-cell;
                width: 60%;
                color: #333;
            }

            .type-num {
                display: table-cell;
                text-align: right;
                font-weight: bold;
                width: 40%;
            }

            .top-list {
                margin: 0;
                padding-left: 18px;
                font-size: 8.5pt;
            }

            .top-list li {
                margin-bottom: 5px;
                line-height: 1.35;
            }

            .top-sev {
                font-weight: bold;
                font-family: sans-serif;
                font-size: 8pt;
                text-transform: uppercase;
            }

            /* ===== 问题列表 ===== */
            .issue-item {
                border-bottom: 1px solid #e5e7eb;
                padding: 10px 0;
            }

            .issue-item:last-child {
                border-bottom: none;
            }

            .issue-title-row {
                display: flex;
                justify-content: space-between;
                align-items: flex-start;
                margin-bottom: 6px;
                break-inside: avoid;
                break-after: avoid;
            }

            .issue-title {
                font-size: 10.5pt;
                font-weight: bold;
                font-family: sans-serif;
                flex: 1;
                margin-right: 15px;
            }

            .issue-severity {
                font-size: 8.5pt;
                font-weight: bold;
                text-transform: uppercase;
                font-family: sans-serif;
                white-space: nowrap;
            }

            .issue-meta {
                font-size: 8pt;
                color: #555;
                margin-bottom: 6px;
                background: #f3f4f6;
                padding: 2px 6px;
                display: inline-block;
                border-radius: 2px;
                font-family: monospace;
                break-after: avoid;
            }

            .issue-desc {
                text-align: justify;
                margin-bottom: 8px;
                line-height: 1.4;
                font-size: 9.5pt;
            }

            .code-snippet {
                background-color: #f8f9fa;
                border: 1px solid #e5e7eb;
                border-left: 3px solid #333;
                color: #1f2937;
                padding: 8px;
                font-size: 8.5pt;
                line-height: 1.3;
                white-space: pre-wrap;
                word-break: break-all;
                margin: 8px 0;
                font-family: "Menlo", "Consolas", "Courier New", "PingFang SC", "Microsoft YaHei", monospace;
            }

            .suggestion {
                margin-top: 6px;
                font-style: italic;
                color: #333;
                font-size: 9pt;
                line-height: 1.4;
            }
        </style>
    </head>
    <body>
        {% if logo_b64 %}
        <img src="data:image/png;base64,{{ logo_b64 }}" class="running-logo" alt="Logo"/>
        {% endif %}

        <div class="header">
            <div class="header-left">
                <div class="title-group">
                    <h1 class="title">{{ title }}</h1>
                    <div class="subtitle">{{ subtitle }}</div>
                </div>
            </div>
            <div class="meta-info">
                <div class="meta-item">报告编号: <span class="mono">{{ report_id }}</span></div>
                <div class="meta-item">生成时间: {{ generated_at }}</div>
            </div>
        </div>
        <div class="header-line"></div>

        <!-- 概览区域 -->
        <div class="score-box">
            <div class="score-left">
                <span style="font-size: 10pt; font-weight: bold; margin-right: 10px; vertical-align: middle;">代码质量评分</span>
                <span class="score-val" style="vertical-align: middle;">{{ score|int }}</span>
                <span style="font-size: 10pt; color: #666; margin-left: 5px; vertical-align: middle;">/ 100</span>
            </div>
            <div class="score-right">
                <table class="stats-table">
                    <tr>
                        {% for label, value in stats %}
                        <td>
                            <span class="stat-label">{{ label }}</span>
                            <span class="stat-value">{{ value }}</span>
                        </td>
                        {% endfor %}
                    </tr>
                </table>
            </div>
        </div>

        <!-- 统计概览 -->
        <div class="section-header">统计概览</div>
        <div class="overview-grid">
            <div class="overview-cell">
                <div class="ov-card">
                    <div class="ov-title">按严重级别分布</div>
                    {% for sev in overview.severity_rows %}
                    <div class="sev-row">
                        <div class="sev-top">
                            <span class="sev-name">{{ sev.label }}</span>
                            <span class="sev-num">{{ sev.count }}</span>
                        </div>
                        <div class="sev-bar-bg">
                            <div class="sev-bar" style="width: {{ sev.pct }}%; background-color: {{ sev.color }};"></div>
                        </div>
                    </div>
                    {% endfor %}
                </div>
            </div>
            <div class="overview-cell">
                <div class="ov-card">
                    <div class="ov-title">按问题类型分布</div>
                    <div class="type-list">
                        {% for t in overview.type_rows %}
                        <div class="type-row">
                            <span class="type-name">{{ t.label }}</span>
                            <span class="type-num">{{ t.count }}</span>
                        </div>
                        {% endfor %}
                    </div>
                </div>
            </div>
        </div>
        <div class="ov-card">
            <div class="ov-title">Top 严重问题</div>
            {% if overview.top_issues %}
            <ol class="top-list">
                {% for t in overview.top_issues %}
                <li>
                    <span class="top-sev" style="color: {{ t.color }};">[{{ t.label }}]</span>
                    {{ t.title }}
                    <span style="color: #666;">({{ t.file_path }})</span>
                </li>
                {% endfor %}
            </ol>
            {% else %}
            <div style="font-size: 8.5pt; color: #666;">无严重问题。</div>
            {% endif %}
        </div>

        <!-- 问题详情 -->
        {% if issues %}
        <div class="section-header">审计发现明细 ({{ issues|length }})</div>

        <div class="issue-list">
            {% for issue in issues %}
            <div class="issue-item">
                <div class="issue-title-row">
                    <div class="issue-title">{{ loop.index }}. {{ issue.title }}</div>
                    <div class="issue-severity" style="color: {{ issue.color }};">[{{ issue.severity_label }}]</div>
                </div>

                {% if issue.file_path or issue.line %}
                <div class="issue-meta mono">
                    {% if issue.file_path %}FILE: {{ issue.file_path }}{% endif %}
                    {% if issue.line %}{% if issue.file_path %} | {% endif %}LINE: {{ issue.line }}{% endif %}
                </div>
                {% endif %}

                {% if issue.description %}
                <div class="issue-desc">{{ issue.description }}</div>
                {% endif %}

                {% if issue.code_snippet %}
                <div class="code-snippet mono">{{ issue.code_snippet }}</div>
                {% endif %}

                {% if issue.suggestion %}
                <div class="suggestion">
                    <strong>建议:</strong> {{ issue.suggestion }}
                </div>
                {% endif %}
            </div>
            {% endfor %}
        </div>
        {% else %}
        <div style="padding: 20px; text-align: center; border: 1px dashed #ccc; margin-top: 20px;">
            <strong>未发现代码问题</strong>
            <p style="font-size: 9pt; color: #666; margin-top: 5px;">本次扫描未发现任何违规或潜在风险，代码质量符合标准。</p>
        </div>
        {% endif %}

        <div style="margin-top: 40px; font-size: 8pt; color: #999; text-align: center; border-top: 1px solid #eee; padding-top: 10px;">
            本报告由 AI 自动生成，注意核实鉴别。
        </div>
    </body>
    </html>
    """

    # --- Markdown 模板 ---
    _MD_TEMPLATE = """# {title}

{subtitle}

- **报告编号**: `{report_id}`
- **生成时间**: {generated_at}
- **代码质量评分**: **{score:.1f} / 100**

## 统计概览

| 严重级别 | 数量 |
| --- | --- |
{severity_rows}

### 按问题类型分布
{type_rows}

### Top 严重问题
{top_issues}

## 审计发现明细 ({issue_count})

{issues_section}
---
> 本报告由 AI 自动生成，注意核实鉴别。
"""

    # --- HTML 模板（独立格式，无 WeasyPrint 依赖）---
    _HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<title>代码审计报告</title>
<style>
{% raw %}
  *{ box-sizing: border-box; }
  body { font-family: -apple-system, "PingFang SC", "Microsoft YaHei", "SimHei", sans-serif;
         background: #f5f7fc; color: #18213a; margin: 0; padding: 32px 20px; line-height: 1.6; }
  .wrap { max-width: 960px; margin: 0 auto; background: #fff; border-radius: 12px;
          box-shadow: 0 8px 30px rgba(36,86,230,.08); padding: 40px 44px; }
  h1 { font-size: 24px; margin: 0 0 4px; }
  .sub { color: #5b6478; margin: 0 0 20px; }
  .meta { font-size: 13px; color: #5b6478; border-bottom: 2px solid #e2e6f1; padding-bottom: 16px; margin-bottom: 24px; }
  .score-box { display: flex; align-items: center; justify-content: space-between; gap: 20px;
         border: 1px solid #e2e6f1; border-radius: 10px; padding: 18px 22px; margin-bottom: 26px; }
  .score-num { font-size: 40px; font-weight: 700; color: #2456e6; line-height: 1; }
  .score-lbl { color: #5b6478; font-size: 13px; }
  .score-stats { text-align: right; }
  .score-stats .sv { display: inline-block; margin-left: 22px; text-align: center; }
  .score-stats .sv b { display: block; font-size: 18px; }
  .score-stats .sv span { font-size: 11px; color: #5b6478; text-transform: uppercase; }
  h2 { font-size: 17px; border-left: 4px solid #2456e6; padding-left: 10px; margin: 30px 0 14px; }
  .cards { display: grid; grid-template-columns: 1fr 1fr; gap: 14px; }
  @media (max-width:720px){ .cards { grid-template-columns: 1fr; } }
  .card { border: 1px solid #e2e6f1; border-radius: 10px; padding: 16px 18px; }
  .card h3 { margin: 0 0 10px; font-size: 13px; text-transform: uppercase; letter-spacing: .04em; color: #5b6478; }
  .sev { display: grid; grid-template-columns: 52px 1fr 30px; align-items: center; gap: 8px; margin-bottom: 6px; font-size: 13px; }
  .sev .bar { height: 6px; background: #f1f1f1; border-radius: 3px; }
  .sev .fill { height: 6px; border-radius: 3px; }
  .sev b { text-align: right; }
  table { width: 100%; border-collapse: collapse; font-size: 13px; }
  th { text-align: left; background: #eef3ff; padding: 8px 10px; }
  td { padding: 8px 10px; border-top: 1px solid #e2e6f1; vertical-align: top; }
  .issue { border: 1px solid #e2e6f1; border-radius: 10px; padding: 16px 18px; margin-bottom: 14px; }
  .issue-head { display: flex; justify-content: space-between; align-items: flex-start; gap: 12px; }
  .issue-head h3 { margin: 0; font-size: 15px; }
  .sev-tag { font-size: 11px; font-weight: 700; padding: 3px 9px; border-radius: 999px; color:#fff;
         white-space: nowrap; }
  .issue-meta { font-family: monospace; font-size: 12px; color: #556; background: #f6f7f9;
         padding: 2px 8px; border-radius: 4px; display: inline-block; margin: 8px 0; }
  pre { background: #f8f9fa; border: 1px solid #e2e6f1; border-left: 3px solid #333;
         padding: 10px 12px; font-size: 12px; overflow-x: auto; border-radius: 6px; }
  .sug { margin-top: 8px; font-style: italic; font-size: 13px; color: #333; }
  .footer { margin-top: 34px; font-size: 12px; color: #9aa; text-align: center;
         border-top: 1px solid #eee; padding-top: 12px; }
{% endraw %}
</style>
</head>
<body>
<div class="wrap">
  <h1>{{ title }}</h1>
  <p class="sub">{{ subtitle }}</p>
  <div class="meta">
    报告编号 <code>{{ report_id }}</code> · 生成时间 {{ generated_at }}
  </div>

  <div class="score-box">
    <div>
      <div class="score-lbl">代码质量评分</div>
      <div class="score-num">{{ score|int }}<span style="font-size:16px;color:#888;">&nbsp;/ 100</span></div>
    </div>
    <div class="score-stats">
      {% for label, value in stats %}
      <div class="sv"><b>{{ value }}</b><span>{{ label }}</span></div>
      {% endfor %}
    </div>
  </div>

  <h2>统计概览</h2>
  <div class="cards">
    <div class="card">
      <h3>按严重级别分布</h3>
      {% for sev in overview.severity_rows %}
      <div class="sev">
        <span>{{ sev.label }}</span>
        <div class="bar"><div class="fill" style="width:{{ sev.pct }}%;background:{{ sev.color }};"></div></div>
        <b>{{ sev.count }}</b>
      </div>
      {% endfor %}
    </div>
    <div class="card">
      <h3>按问题类型分布</h3>
      <table>
        {% for t in overview.type_rows %}
        <tr><td>{{ t.label }}</td><td style="text-align:right;font-weight:700;">{{ t.count }}</td></tr>
        {% endfor %}
      </table>
    </div>
  </div>

  {% if overview.top_issues %}
  <div class="card" style="margin-top:14px;">
    <h3>Top 严重问题</h3>
    <ol>
      {% for t in overview.top_issues %}
      <li><b style="color:{{ t.color }};">[{{ t.label }}]</b> {{ t.title }} <span style="color:#667;font-size:12px;">({{ t.file_path }})</span></li>
      {% endfor %}
    </ol>
  </div>
  {% endif %}

  <h2>审计发现明细 ({{ issues|length }})</h2>
  {% if issues %}
    {% for issue in issues %}
    <div class="issue">
      <div class="issue-head">
        <h3>{{ loop.index }}. {{ issue.title }}</h3>
        <span class="sev-tag" style="background: {{ issue.color }};">{{ issue.severity_label }}</span>
      </div>
      {% if issue.file_path or issue.line %}
      <div class="issue-meta">{% if issue.file_path %}FILE: {{ issue.file_path }}{% endif %}{% if issue.line %}{% if issue.file_path %} | {% endif %}LINE: {{ issue.line }}{% endif %}</div>
      {% endif %}
      {% if issue.description %}<p>{{ issue.description }}</p>{% endif %}
      {% if issue.code_snippet %}<pre>{{ issue.code_snippet }}</pre>{% endif %}
      {% if issue.suggestion %}<div class="sug"><b>建议:</b> {{ issue.suggestion }}</div>{% endif %}
    </div>
    {% endfor %}
  {% else %}
  <div style="padding:20px;text-align:center;border:1px dashed #ccc;border-radius:8px;color:#667;">未发现代码问题</div>
  {% endif %}

  <div class="footer">本报告由 AI 自动生成，注意核实鉴别。</div>
</div>
</body>
</html>
"""

    @classmethod
    def _get_logo_base64(cls) -> str:
        """读取并编码 Logo 图片"""
        try:
            current_dir = os.path.dirname(os.path.abspath(__file__))
            possible_paths = [
                os.path.join(current_dir, '../../static/images/logo_nobg.png'),
                os.path.abspath(os.path.join(current_dir, '../../../frontend/public/images/logo_nobg.png')),
            ]
            for logo_path in possible_paths:
                if os.path.exists(logo_path):
                    with open(logo_path, "rb") as image_file:
                        return base64.b64encode(image_file.read()).decode('utf-8')
        except Exception as e:
            print(f"Error loading logo: {e}")
            return ""
        return ""

    @classmethod
    def _escape_html(cls, text: str) -> str:
        """安全转义 HTML 特殊字符"""
        if text is None:
            return None
        return html.escape(str(text))

    @classmethod
    def _process_issues(cls, issues: List[Dict]) -> List[Dict]:
        """加工问题列表：排序、转义、补充分级信息与配色"""
        processed = []
        sorted_issues = sorted(
            issues, key=lambda x: SEVERITY_ORDER.get(x.get('severity', 'low'), 4))

        for i in sorted_issues:
            item = i.copy()
            sev = item.get('severity', 'low')
            if isinstance(sev, str) and ',' in sev:
                sev = sev.split(',')[0].strip().lower()
            item['severity'] = sev
            item['severity_label'] = SEVERITY_LABELS.get(sev, 'UNKNOWN')
            item['color'] = SEVERITY_COLORS.get(sev, '#6b7280')
            item['line'] = item.get('line_number') or item.get('line')

            code = item.get('code_snippet') or item.get('code') or item.get('context')
            if isinstance(code, list):
                code = '\n'.join(code)
            item['code_snippet'] = cls._escape_html(code) if code else None

            desc = item.get('description')
            if not desc or desc == 'None':
                desc = item.get('title', '')
            item['description'] = cls._escape_html(desc)

            suggestion = item.get('suggestion')
            if suggestion == 'None' or suggestion is None:
                item['suggestion'] = None
            else:
                item['suggestion'] = cls._escape_html(suggestion)

            item['title'] = cls._escape_html(item.get('title', ''))
            item['file_path'] = cls._escape_html(item.get('file_path'))

            processed.append(item)
        return processed

    @classmethod
    def _ratio_safe(cls, count: int, total: int) -> str:
        """计算占比（百分比字符串），防止除零"""
        return f"{round(count * 100.0 / total, 1)}" if total else "0"

    @classmethod
    def _compute_overview(cls, issues: List[Dict]) -> Dict[str, Any]:
        """计算统计概览数据：严重级别分布 / 类型分布 / Top 问题"""
        total = len(issues) or 1

        severity_counts = {k: 0 for k in SEVERITY_ORDER}
        type_counts: Dict[str, int] = {}
        for issue in issues:
            sev = issue.get('severity', 'low')
            if ',' in str(sev):
                sev = str(sev).split(',')[0].strip().lower()
            if sev in severity_counts:
                severity_counts[sev] += 1
            else:
                severity_counts.setdefault(sev, 0)
                severity_counts[sev] += 1
            itype = str(issue.get('issue_type') or issue.get('type') or 'other').strip() or 'other'
            type_counts[itype] = type_counts.get(itype, 0) + 1

        severity_rows = []
        for sev in SEVERITY_ORDER:
            count = severity_counts[sev]
            severity_rows.append({
                'key': sev,
                'label': SEVERITY_LABELS.get(sev, sev.upper()),
                'count': count,
                'pct': cls._ratio_safe(count, total),
                'color': SEVERITY_COLORS.get(sev, '#6b7280'),
            })

        type_rows = [
            {'label': k or 'other', 'count': v}
            for k, v in sorted(type_counts.items(), key=lambda x: -x[1])
        ]

        sorted_issues = sorted(
            issues, key=lambda x: SEVERITY_ORDER.get(x.get('severity', 'low'), 4))
        top_issues = []
        for issue in sorted_issues[:5]:
            sev = issue.get('severity', 'low')
            top_issues.append({
                'label': SEVERITY_LABELS.get(sev, 'UNKNOWN'),
                'color': SEVERITY_COLORS.get(sev, '#6b7280'),
                'title': issue.get('title') or '',
                'file_path': issue.get('file_path') or '-',
            })

        return {
            'severity_rows': severity_rows,
            'type_rows': type_rows,
            'top_issues': top_issues,
        }

    @classmethod
    def _render_pdf(cls, context: Dict[str, Any]) -> bytes:
        context['logo_b64'] = cls._get_logo_base64()
        template = Template(cls._TEMPLATE)
        html_content = template.render(**context)
        font_config = FontConfiguration()
        pdf_file = io.BytesIO()
        HTML(string=html_content).write_pdf(
            pdf_file,
            font_config=font_config,
            presentational_hints=True,
        )
        pdf_file.seek(0)
        return pdf_file.getvalue()

    @classmethod
    def _render_markdown(cls, context: Dict[str, Any]) -> bytes:
        """渲染 Markdown 报告（纯模板，无系统依赖）"""
        overview = context['overview']
        line = []
        for sev in overview['severity_rows']:
            line.append(f"| {sev['label']} | {sev['count']} |")
        severity_rows = '\n'.join(line)

        type_lines = '\n'.join(
            f"- {t['label']}: **{t['count']}**" for t in overview['type_rows']) or '- 无'
        type_rows = type_lines

        if overview['top_issues']:
            top_lines = []
            for i, t in enumerate(overview['top_issues'], 1):
                top_lines.append(
                    f"{i}. **{t['title']}** `[{t['label']}]` ({t['file_path']})")
            top_issues = '\n'.join(top_lines)
        else:
            top_issues = '- 无严重问题'

        issues = context.get('issues', [])
        if issues:
            parts = []
            for i, issue in enumerate(issues, 1):
                parts.append(f"### {i}. [{issue['severity_label']}] {issue['title']}")
                loc = issue.get('file_path') or '-'
                loc = str(loc).replace('&#x27;', "'")
                if issue.get('line'):
                    loc += f":{issue['line']}"
                parts.append(f"- **位置**: `{loc}`")
                if issue.get('description'):
                    parts.append(f"- **描述**: {issue['description']}")
                if issue.get('code_snippet'):
                    parts.append("\n```\n{}\n```".format(
                        issue['code_snippet'].replace('&#x27;', "'")))
                if issue.get('suggestion'):
                    parts.append(f"- **建议**: {issue['suggestion']}")
                parts.append("")
            issues_section = '\n'.join(parts)
        else:
            issues_section = "本次扫描未发现任何违规或潜在风险，代码质量符合标准。"

        md = cls._MD_TEMPLATE.format(
            title=context['title'],
            subtitle=context['subtitle'],
            report_id=context['report_id'],
            generated_at=context['generated_at'],
            score=float(context['score'] or 0),
            severity_rows=severity_rows,
            type_rows=type_rows,
            top_issues=top_issues,
            issue_count=len(issues),
            issues_section=issues_section,
        )
        return md.encode('utf-8')

    @classmethod
    def _render_html(cls, context: Dict[str, Any]) -> bytes:
        """渲染独立 HTML 报告（纯模板，无 WeasyPrint 依赖）"""
        template = Template(cls._HTML_TEMPLATE)
        html_content = template.render(**context)
        return html_content.encode('utf-8')

    @classmethod
    def _render_json(cls, context: Dict[str, Any], task: Dict[str, Any],
                     issues: List[Dict], project: str) -> bytes:
        """渲染 JSON 报告（结构化数据）"""
        overview = context['overview']
        payload = {
            "metadata": {
                "title": context['title'],
                "subtitle": context['subtitle'],
                "report_id": context['report_id'],
                "generated_at": context['generated_at'],
                "format": "JSON",
                "version": "1.0.0",
                "project": project,
            },
            "task": task,
            "summary": {
                "quality_score": context['score'],
                "issues_count": len(issues),
                "by_severity": {
                    sev['key']: sev['count'] for sev in overview['severity_rows']
                },
                "by_type": {
                    t['label']: t['count'] for t in overview['type_rows']
                },
                "top_issues": overview['top_issues'],
            },
            "issues": issues,
        }
        return json.dumps(payload, ensure_ascii=False, indent=2).encode('utf-8')

    @classmethod
    def _normalize_format(cls, fmt: str) -> str:
        """规整格式名"""
        fmt = (fmt or 'pdf').lower()
        if fmt == 'md':
            return 'markdown'
        if fmt not in SUPPORTED_FORMATS:
            raise ValueError(
                f"不支持的报告格式 '{fmt}'，可选: pdf, markdown/md, html, json")
        return fmt

    @classmethod
    def render_report(cls, context: Dict[str, Any], task: Dict[str, Any],
                      issues: List[Dict], project: str, fmt: str) -> bytes:
        """按指定格式渲染完整报告"""
        fmt = cls._normalize_format(fmt)
        if fmt == 'pdf':
            return cls._render_pdf(context)
        if fmt == 'markdown':
            return cls._render_markdown(context)
        if fmt == 'html':
            return cls._render_html(context)
        if fmt == 'json':
            return cls._render_json(context, task, issues, project)
        raise ValueError(f"不支持的报告格式 '{fmt}'")

    @classmethod
    def generate_instant_report(cls, result: Dict[str, Any], language: str,
                                time: float, format: str = "pdf") -> bytes:
        score = result.get('quality_score', 0)
        issues = result.get('issues', [])
        processed = cls._process_issues(issues)

        context = {
            'title': '代码审计报告',
            'subtitle': f'即时分析 | 语言: {language.capitalize()}',
            'generated_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'report_id': f"INST-{int(datetime.now().timestamp())}",
            'score': score,
            'stats': [
                ('问题总数', len(processed)),
                ('耗时', f"{time:.2f}s"),
            ],
            'overview': cls._compute_overview(processed),
            'issues': processed,
        }
        return cls.render_report(context, {}, processed, '', format)

    @classmethod
    def generate_task_report(cls, task: Dict[str, Any],
                             issues: List[Dict[str, Any]],
                             project: str = "项目",
                             format: str = "pdf") -> bytes:
        score = task.get('quality_score', 0)
        processed = cls._process_issues(issues)

        context = {
            'title': '项目代码审计报告',
            'subtitle': f"项目: {project} | 分支: {task.get('branch_name', 'default')}",
            'generated_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'report_id': f"TASK-{task.get('id', '')[:8]}",
            'score': score,
            'stats': [
                ('扫描文件', task.get('scanned_files', 0)),
                ('代码行数', f"{task.get('total_lines', 0):,}"),
                ('问题总数', len(processed)),
            ],
            'overview': cls._compute_overview(processed),
            'issues': processed,
        }
        return cls.render_report(context, task, processed, project, format)

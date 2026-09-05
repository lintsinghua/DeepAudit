"""
PDF 报告生成服务 - 专业审计版 (WeasyPrint)
"""

import io
import html
from datetime import datetime
from typing import List, Dict, Any
import math
import os
import sys
import base64

# macOS Homebrew compatibility fix
if sys.platform == 'darwin':
    os.environ['DYLD_FALLBACK_LIBRARY_PATH'] = '/opt/homebrew/lib:' + os.environ.get('DYLD_FALLBACK_LIBRARY_PATH', '')

from jinja2 import Template

class ReportGenerator:
    """
    基于 HTML/CSS 的专业 PDF 报告生成器
    风格：严谨、高密度、企业级审计报告风格
    """
    
    # --- HTML 模板 ---
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
                line-height: 1.3; /* Tighter line height */
                font-size: 10pt;
                margin: 0;
            }
            
            /* 页眉 Logo 定义 */
            .running-logo {
                position: running(logoRunning);
                height: 30px;
                width: auto;
                margin-bottom: 10px;
            }
            
            /* 头部 */
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
            
            /* Logo removed from here */
            
            .title-group {
                display: block; /* Changed to block since it's the only child */
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
            
            /* 通用工具类 */
            .text-right { text-align: right; }
            .text-center { text-align: center; }
            .bold { font-weight: bold; }
            .mono { font-family: "Menlo", "Consolas", "Courier New", "PingFang SC", "Microsoft YaHei", monospace; }
            
            /* 概览表格 */
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
            
            /* 评分栏 */
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
            
            /* 统计数据表格 */
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
            
            /* 问题列表 - 高密度排版 */
            .issue-item {
                border-bottom: 1px solid #e5e7eb;
                padding: 10px 0; /* Reduced padding */
                /* 移除 break-inside: avoid，允许问题块跨页 */
            }
            
            .issue-item:last-child {
                border-bottom: none;
            }
            
            .issue-title-row {
                display: flex;
                justify-content: space-between;
                align-items: flex-start;
                margin-bottom: 6px; /* Reduced margin */
                break-inside: avoid; /* 标题行不断开 */
                break-after: avoid; /* 标题后不断页 */
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
                margin-bottom: 6px; /* Reduced margin */
                background: #f3f4f6;
                padding: 2px 6px;
                display: inline-block;
                border-radius: 2px;
                font-family: monospace;
                break-after: avoid; /* 元信息后不断页 */
            }
            
            .issue-desc {
                text-align: justify;
                margin-bottom: 8px; /* Reduced margin */
                line-height: 1.4;
                font-size: 9.5pt;
            }
            
            /* 代码块 - 浅色主题，紧凑 */
            .code-snippet {
                background-color: #f8f9fa;
                border: 1px solid #e5e7eb;
                border-left: 3px solid #333;
                color: #1f2937;
                padding: 8px; /* Reduced padding */
                font-size: 8.5pt; /* Smaller font */
                line-height: 1.3;
                white-space: pre-wrap;
                word-break: break-all;
                margin: 8px 0; /* Reduced margin */
                font-family: "Menlo", "Consolas", "Courier New", "PingFang SC", "Microsoft YaHei", monospace;
            }
            
            /* 建议 - 无框风格 */
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
        <!-- 定义页眉 Logo (Running Element) -->
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
        
        <!-- 问题详情 -->
        {% if issues %}
        <div class="section-header">审计发现明细 ({{ issues|length }})</div>
        
        <div class="issue-list">
            {% for issue in issues %}
            <div class="issue-item">
                <div class="issue-title-row">
                    <div class="issue-title">{{ loop.index }}. {{ issue.title }}</div>
                    <div class="issue-severity color-{{ issue.severity }}">[{{ issue.severity_label }}]</div>
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
        
        <!-- 页脚声明 -->
        <div style="margin-top: 40px; font-size: 8pt; color: #999; text-align: center; border-top: 1px solid #eee; padding-top: 10px;">
            本报告由 AI 自动生成，注意核实鉴别。
        </div>
    </body>
    </html>
    """
    
    @classmethod
    def _get_logo_base64(cls) -> str:
        """读取并编码 Logo 图片"""
        try:
            current_dir = os.path.dirname(os.path.abspath(__file__))
            # 尝试多个可能的路径
            possible_paths = [
                # Docker 容器内路径
                os.path.join(current_dir, '../../static/images/logo_nobg.png'),
                # 本地开发路径
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
        processed = []
        order = {'critical': 0, 'high': 1, 'medium': 2, 'low': 3}
        sorted_issues = sorted(issues, key=lambda x: order.get(x.get('severity', 'low'), 4))

        sev_labels = {
            'critical': 'CRITICAL',
            'high': 'HIGH',
            'medium': 'MEDIUM',
            'low': 'LOW'
        }

        for i in sorted_issues:
            item = i.copy()
            item['severity'] = item.get('severity', 'low')
            item['severity_label'] = sev_labels.get(item['severity'], 'UNKNOWN')
            item['line'] = item.get('line_number') or item.get('line')

            # 确保代码片段存在 (处理可能的字段名差异)
            code = item.get('code_snippet') or item.get('code') or item.get('context')
            if isinstance(code, list):
                code = '\n'.join(code)
            item['code_snippet'] = cls._escape_html(code) if code else None

            # 确保 description 不为 None
            desc = item.get('description')
            if not desc or desc == 'None':
                desc = item.get('title', '')  # 如果没有描述，使用标题
            item['description'] = cls._escape_html(desc)

            # 确保 suggestion 不为 None
            suggestion = item.get('suggestion')
            if suggestion == 'None' or suggestion is None:
                item['suggestion'] = None
            else:
                item['suggestion'] = cls._escape_html(suggestion)

            # 转义标题和文件路径
            item['title'] = cls._escape_html(item.get('title', ''))
            item['file_path'] = cls._escape_html(item.get('file_path'))

            processed.append(item)
        return processed

    @classmethod
    def _render_pdf(cls, context: Dict[str, Any]) -> bytes:
        # Load native PDF dependencies only when rendering a PDF.
        from weasyprint import HTML
        from weasyprint.text.fonts import FontConfiguration

        # 注入 Logo
        context['logo_b64'] = cls._get_logo_base64()
        
        template = Template(cls._TEMPLATE)
        html_content = template.render(**context)
        font_config = FontConfiguration()
        pdf_file = io.BytesIO()
        HTML(string=html_content).write_pdf(
            pdf_file,
            font_config=font_config,
            presentational_hints=True
        )
        pdf_file.seek(0)
        return pdf_file.getvalue()

    @classmethod
    def generate_instant_report(cls, result: Dict[str, Any], language: str, time: float) -> bytes:
        score = result.get('quality_score', 0)
        issues = result.get('issues', [])
        
        context = {
            'title': '代码审计报告',
            'subtitle': f'即时分析 | 语言: {language.capitalize()}',
            'generated_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'report_id': f"INST-{int(datetime.now().timestamp())}",
            'score': score,
            'stats': [
                ('问题总数', len(issues)),
                ('耗时', f"{time:.2f}s"),
            ],
            'issues': cls._process_issues(issues)
        }
        return cls._render_pdf(context)

    @classmethod
    def generate_task_report(cls, task: Dict[str, Any], issues: List[Dict[str, Any]], project: str = "项目") -> bytes:
        score = task.get('quality_score', 0)
        
        context = {
            'title': '项目代码审计报告',
            'subtitle': f"项目: {project} | 分支: {task.get('branch_name', 'default')}",
            'generated_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'report_id': f"TASK-{task.get('id', '')[:8]}",
            'score': score,
            'stats': [
                ('扫描文件', task.get('scanned_files', 0)),
                ('代码行数', f"{task.get('total_lines', 0):,}"),
                ('问题总数', len(issues))
            ],
            'issues': cls._process_issues(issues)
        }
        return cls._render_pdf(context)

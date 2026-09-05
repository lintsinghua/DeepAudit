/**
 * 日志记录模块
 * 提供统一的日志记录、存储和导出功能
 */

export enum LogLevel {
    DEBUG = 'DEBUG',
    INFO = 'INFO',
    WARN = 'WARN',
    ERROR = 'ERROR',
    FATAL = 'FATAL',
}

export enum LogCategory {
    USER_ACTION = 'USER_ACTION',      // 用户操作
    API_CALL = 'API_CALL',            // API调用
    PERFORMANCE = 'PERFORMANCE',      // 请求性能
    SYSTEM = 'SYSTEM',                // 系统事件
    CONSOLE_ERROR = 'CONSOLE_ERROR',  // 控制台错误
}

export interface LogEntry {
    id: string;
    timestamp: number;
    level: LogLevel;
    category: LogCategory;
    message: string;
    data?: any;
    stack?: string;
    userAgent?: string;
    url?: string;
    userId?: string;
}

class Logger {
    private logs: LogEntry[] = [];
    private maxLogs = 1000; // 最多保存1000条日志
    private storageKey = 'app_logs';
    private listeners: Set<(log: LogEntry) => void> = new Set();
    private isEnabled = true;

    constructor() {
        this.loadLogsFromStorage();
        this.setupConsoleInterceptor();
        this.setupErrorHandler();
        this.setupUnhandledRejectionHandler();
    }

    /**
     * 从localStorage加载历史日志
     */
    private loadLogsFromStorage() {
        try {
            const stored = localStorage.getItem(this.storageKey);
            if (stored) {
                this.logs = JSON.parse(stored);
            }
        } catch (error) {
            console.error('Failed to load logs from storage:', error);
        }
    }

    /**
     * 保存日志到localStorage
     */
    private saveLogsToStorage() {
        try {
            // 只保存最近的日志
            const logsToSave = this.logs.slice(-this.maxLogs);
            localStorage.setItem(this.storageKey, JSON.stringify(logsToSave));
        } catch (error) {
            console.error('Failed to save logs to storage:', error);
        }
    }

    /**
     * 拦截console方法
     */
    private setupConsoleInterceptor() {
        const originalError = console.error;

        // 只拦截错误，不拦截警告
        console.error = (...args: any[]) => {
            originalError.apply(console, args);
            // 过滤掉一些常见的无关错误
            const message = args.join(' ');
            if (!message.includes('ResizeObserver') &&
                !message.includes('favicon') &&
                !message.includes('Download the React DevTools')) {
                this.log(LogLevel.ERROR, LogCategory.CONSOLE_ERROR, message, { args });
            }
        };
    }

    /**
     * 设置全局错误处理
     */
    private setupErrorHandler() {
        window.addEventListener('error', (event) => {
            this.log(
                LogLevel.ERROR,
                LogCategory.CONSOLE_ERROR,
                event.message,
                {
                    filename: event.filename,
                    lineno: event.lineno,
                    colno: event.colno,
                    error: event.error,
                },
                event.error?.stack
            );
        });
    }

    /**
     * 设置未处理的Promise拒绝处理
     */
    private setupUnhandledRejectionHandler() {
        window.addEventListener('unhandledrejection', (event) => {
            this.log(
                LogLevel.ERROR,
                LogCategory.CONSOLE_ERROR,
                `Unhandled Promise Rejection: ${event.reason}`,
                { reason: event.reason },
                event.reason?.stack
            );
        });
    }

    /**
     * 记录日志
     */
    log(
        level: LogLevel,
        category: LogCategory,
        message: string,
        data?: any,
        stack?: string
    ) {
        if (!this.isEnabled) return;

        const entry: LogEntry = {
            id: `${Date.now()}-${Math.random().toString(36).substr(2, 9)}`,
            timestamp: Date.now(),
            level,
            category,
            message,
            data,
            stack,
            userAgent: navigator.userAgent,
            url: window.location.href,
        };

        this.logs.push(entry);

        // 限制日志数量
        if (this.logs.length > this.maxLogs) {
            this.logs = this.logs.slice(-this.maxLogs);
        }

        // 保存到localStorage
        this.saveLogsToStorage();

        // 通知监听器
        this.listeners.forEach(listener => listener(entry));

        // 在开发环境输出到控制台
        if (import.meta.env.DEV) {
            this.logToConsole(entry);
        }
    }

    /**
     * 输出到控制台
     */
    private logToConsole(entry: LogEntry) {
        // 生产环境只输出ERROR和FATAL级别
        if (!import.meta.env.DEV && entry.level !== LogLevel.ERROR && entry.level !== LogLevel.FATAL) {
            return;
        }

        const style = this.getConsoleStyle(entry.level);
        console.log(
            `%c[${entry.level}] [${entry.category}] ${new Date(entry.timestamp).toISOString()}`,
            style,
            entry.message,
            entry.data || ''
        );
    }

    /**
     * 获取控制台样式
     */
    private getConsoleStyle(level: LogLevel): string {
        const styles = {
            [LogLevel.DEBUG]: 'color: #888',
            [LogLevel.INFO]: 'color: #0066cc',
            [LogLevel.WARN]: 'color: #ff9900',
            [LogLevel.ERROR]: 'color: #cc0000; font-weight: bold',
            [LogLevel.FATAL]: 'color: #fff; background: #cc0000; font-weight: bold',
        };
        return styles[level];
    }

    /**
     * 便捷方法
     */
    debug(category: LogCategory, message: string, data?: any) {
        this.log(LogLevel.DEBUG, category, message, data);
    }

    info(category: LogCategory, message: string, data?: any) {
        this.log(LogLevel.INFO, category, message, data);
    }

    warn(category: LogCategory, message: string, data?: any) {
        this.log(LogLevel.WARN, category, message, data);
    }

    error(category: LogCategory, message: string, data?: any, stack?: string) {
        this.log(LogLevel.ERROR, category, message, data, stack);
    }

    fatal(category: LogCategory, message: string, data?: any, stack?: string) {
        this.log(LogLevel.FATAL, category, message, data, stack);
    }

    /**
     * 记录用户操作
     */
    logUserAction(action: string, details?: any) {
        this.info(LogCategory.USER_ACTION, action, details);
    }

    /**
     * 记录API调用
     */
    logApiCall(method: string, url: string, status?: number, duration?: number, error?: any) {
        const level = error ? LogLevel.ERROR : LogLevel.INFO;
        this.log(level, LogCategory.API_CALL, `${method} ${url}`, {
            method,
            url,
            status,
            duration,
            error,
        });
    }

    /**
     * 记录性能指标
     */
    logPerformance(metric: string, value: number, unit = 'ms') {
        this.info(LogCategory.SYSTEM, `${metric}: ${value}${unit}`, { metric, value, unit });
    }

    /**
     * 获取所有日志
     */
    getLogs(filter?: {
        level?: LogLevel;
        category?: LogCategory;
        startTime?: number;
        endTime?: number;
        search?: string;
    }): LogEntry[] {
        let filtered = [...this.logs];

        if (filter) {
            if (filter.level) {
                filtered = filtered.filter(log => log.level === filter.level);
            }
            if (filter.category) {
                filtered = filtered.filter(log => log.category === filter.category);
            }
            if (filter.startTime) {
                filtered = filtered.filter(log => log.timestamp >= filter.startTime!);
            }
            if (filter.endTime) {
                filtered = filtered.filter(log => log.timestamp <= filter.endTime!);
            }
            if (filter.search) {
                const search = filter.search.toLowerCase();
                filtered = filtered.filter(log =>
                    log.message.toLowerCase().includes(search) ||
                    JSON.stringify(log.data).toLowerCase().includes(search)
                );
            }
        }

        return filtered;
    }

    /**
     * 清空日志
     */
    clearLogs() {
        this.logs = [];
        localStorage.removeItem(this.storageKey);
    }

    /**
     * 导出日志为JSON
     */
    exportLogsAsJson(): string {
        return JSON.stringify(this.logs, null, 2);
    }

    /**
     * 导出日志为CSV
     */
    exportLogsAsCsv(): string {
        const headers = ['Timestamp', 'Level', 'Category', 'Message', 'Data', 'URL'];
        const rows = this.logs.map(log => [
            new Date(log.timestamp).toISOString(),
            log.level,
            log.category,
            log.message,
            JSON.stringify(log.data || {}),
            log.url || '',
        ]);

        return [
            headers.join(','),
            ...rows.map(row => row.map(cell => `"${cell}"`).join(',')),
        ].join('\n');
    }

    /**
     * 下载日志文件
     */
    downloadLogs(format: 'json' | 'csv' = 'json') {
        const content = format === 'json' ? this.exportLogsAsJson() : this.exportLogsAsCsv();
        const blob = new Blob([content], { type: format === 'json' ? 'application/json' : 'text/csv' });
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = `logs-${new Date().toISOString()}.${format}`;
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        URL.revokeObjectURL(url);
    }

    /**
     * 添加日志监听器
     */
    addListener(listener: (log: LogEntry) => void) {
        this.listeners.add(listener);
        return () => this.listeners.delete(listener);
    }

    /**
     * 启用/禁用日志记录
     */
    setEnabled(enabled: boolean) {
        this.isEnabled = enabled;
    }

    /**
     * 获取日志统计
     */
    getStats() {
        const stats = {
            total: this.logs.length,
            byLevel: {} as Record<LogLevel, number>,
            byCategory: {} as Record<LogCategory, number>,
            errors: 0,
        };

        this.logs.forEach(log => {
            stats.byLevel[log.level] = (stats.byLevel[log.level] || 0) + 1;
            stats.byCategory[log.category] = (stats.byCategory[log.category] || 0) + 1;
            if (log.level === LogLevel.ERROR || log.level === LogLevel.FATAL) {
                stats.errors++;
            }
        });

        return stats;
    }
}

// 导出单例
export const logger = new Logger();

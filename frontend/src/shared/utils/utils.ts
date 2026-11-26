import { type ClassValue, clsx } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

export function formatDate(date: string | Date, options?: Intl.DateTimeFormatOptions) {
  const defaultOptions: Intl.DateTimeFormatOptions = {
    year: 'numeric',
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit'
  };
  
  return new Date(date).toLocaleDateString('zh-CN', { ...defaultOptions, ...options });
}

export function formatFileSize(bytes: number): string {
  if (bytes === 0) return '0 B';
  
  const k = 1024;
  const sizes = ['B', 'KB', 'MB', 'GB'];
  const i = Math.floor(Math.log(bytes) / Math.log(k));
  
  return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + ' ' + sizes[i];
}

export function formatNumber(num: number): string {
  return new Intl.NumberFormat('zh-CN').format(num);
}

export function generateId(): string {
  return Math.random().toString(36).substring(2) + Date.now().toString(36);
}

export function debounce<T extends (...args: any[]) => any>(
  func: T,
  wait: number
): (...args: Parameters<T>) => void {
  let timeout: number | undefined;
  return (...args: Parameters<T>) => {
    clearTimeout(timeout);
    timeout = setTimeout(() => func(...args), wait) as unknown as number;
  };
}

export function throttle<T extends (...args: any[]) => any>(
  func: T,
  limit: number
): (...args: Parameters<T>) => void {
  let inThrottle: boolean;
  return (...args: Parameters<T>) => {
    if (!inThrottle) {
      func(...args);
      inThrottle = true;
      setTimeout(() => inThrottle = false, limit);
    }
  };
}

export function isValidEmail(email: string): boolean {
  const emailRegex = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
  return emailRegex.test(email);
}

export function isValidPhone(phone: string): boolean {
  const phoneRegex = /^1[3-9]\d{9}$/;
  return phoneRegex.test(phone);
}

export function truncateText(text: string, maxLength: number): string {
  if (text.length <= maxLength) return text;
  return text.substring(0, maxLength) + '...';
}

export function getFileExtension(filename: string): string {
  return filename.split('.').pop()?.toLowerCase() || '';
}

export function getLanguageFromExtension(extension: string): string {
  const languageMap: Record<string, string> = {
    'js': 'javascript',
    'jsx': 'javascript',
    'ts': 'typescript',
    'tsx': 'typescript',
    'py': 'python',
    'java': 'java',
    'go': 'go',
    'rs': 'rust',
    'cpp': 'cpp',
    'c': 'cpp',
    'cc': 'cpp',
    'h': 'cpp',
    'hh': 'cpp',
    'cs': 'csharp',
    'php': 'php',
    'rb': 'ruby',
    'kt': 'kotlin',
    'swift': 'swift'
  };
  
  return languageMap[extension] || 'text';
}

export function calculateQualityGrade(score: number): {
  grade: string;
  color: string;
  description: string;
} {
  if (score >= 90) {
    return {
      grade: 'A',
      color: 'text-green-600',
      description: '优秀'
    };
  } else if (score >= 80) {
    return {
      grade: 'B',
      color: 'text-blue-600',
      description: '良好'
    };
  } else if (score >= 70) {
    return {
      grade: 'C',
      color: 'text-yellow-600',
      description: '一般'
    };
  } else if (score >= 60) {
    return {
      grade: 'D',
      color: 'text-orange-600',
      description: '较差'
    };
  } else {
    return {
      grade: 'F',
      color: 'text-red-600',
      description: '差'
    };
  }
}

export function sleep(ms: number): Promise<void> {
  return new Promise(resolve => setTimeout(resolve, ms));
}

export function copyToClipboard(text: string): Promise<void> {
  if (navigator.clipboard) {
    return navigator.clipboard.writeText(text);
  } else {
    // Fallback for older browsers
    const textArea = document.createElement('textarea');
    textArea.value = text;
    document.body.appendChild(textArea);
    textArea.focus();
    textArea.select();
    try {
      document.execCommand('copy');
    } catch (err) {
      console.error('Failed to copy text: ', err);
    }
    document.body.removeChild(textArea);
    return Promise.resolve();
  }
}

/**
 * 计算任务扫描进度百分比
 * @param scannedFiles 已扫描文件数
 * @param totalFiles 总文件数
 * @returns 进度百分比（0-100），安全处理NaN情况
 */
export function calculateTaskProgress(scannedFiles?: number, totalFiles?: number, status?: string): number {
  if (status === "completed") return 100;
  // 处理未定义或无效值
  const scanned = scannedFiles || 0;
  const total = totalFiles || 0;
  
  // 避免除以0
  if (total === 0) {
    return 0;
  }
  
  // 计算百分比并四舍五入
  const percentage = (scanned / total) * 100;
  
  // 确保返回值在0-100之间
  return Math.min(100, Math.max(0, Math.round(percentage)));
}

/**
 * 获取任务进度的完整信息
 * @param scannedFiles 已扫描文件数
 * @param totalFiles 总文件数
 * @returns 包含百分比、显示文本等信息的对象
 */
export function getTaskProgressInfo(scannedFiles?: number, totalFiles?: number) {
  const scanned = scannedFiles || 0;
  const total = totalFiles || 0;
  const percentage = calculateTaskProgress(scanned, total);
  
  return {
    percentage,
    scanned,
    total,
    text: `${scanned} / ${total} 文件`,
    percentText: `${percentage}%`,
    isComplete: total > 0 && scanned >= total,
    isStarted: scanned > 0
  };
}
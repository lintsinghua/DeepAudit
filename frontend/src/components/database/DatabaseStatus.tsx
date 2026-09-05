/**
 * 数据库状态指示器
 * 显示当前使用的数据库模式
 */

import { Server } from 'lucide-react';
import { Badge } from '@/components/ui/badge';
import { dbMode } from '@/shared/config/database';

export function DatabaseStatus() {
  const getStatusConfig = () => {
    switch (dbMode) {
      case 'api':
        return {
          icon: Server,
          label: '后端数据库',
          variant: 'default' as const,
          description: '数据存储在后端 PostgreSQL 数据库'
        };
    }
  };

  const config = getStatusConfig();
  const Icon = config.icon;

  return (
    <Badge variant={config.variant} className="gap-1.5">
      <Icon className="h-3 w-3" />
      {config.label}
    </Badge>
  );
}

export function DatabaseStatusDetail() {
  const getStatusConfig = () => {
    switch (dbMode) {
      case 'api':
        return {
          icon: Server,
          label: '后端数据库模式',
          variant: 'default' as const,
          description: '数据存储在后端 PostgreSQL 数据库中，通过 REST API 访问。支持多用户、多设备同步。',
          tips: '提示：所有数据操作都通过后端 API 进行，确保网络连接正常。'
        };
    }
  };

  const config = getStatusConfig();
  const Icon = config.icon;

  return (
    <div className="flex items-start gap-3 rounded-lg border p-4">
      <div className="rounded-full bg-muted p-2">
        <Icon className="h-5 w-5" />
      </div>
      <div className="flex-1 space-y-1">
        <div className="flex items-center gap-2">
          <h4 className="text-sm font-semibold">{config.label}</h4>
          <Badge variant={config.variant} className="text-xs">
            {dbMode}
          </Badge>
        </div>
        <p className="text-sm text-muted-foreground">{config.description}</p>
        {config.tips && (
          <p className="text-xs text-muted-foreground italic">{config.tips}</p>
        )}
      </div>
    </div>
  );
}

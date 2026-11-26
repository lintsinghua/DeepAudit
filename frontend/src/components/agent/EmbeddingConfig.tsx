/**
 * 嵌入模型配置组件
 * Cyberpunk Terminal Aesthetic
 * 独立于 LLM 配置，专门用于 Agent 审计的 RAG 系统
 */

import { useState, useEffect } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Badge } from "@/components/ui/badge";
import {
  Brain,
  Cpu,
  Check,
  X,
  Loader2,
  RefreshCw,
  Server,
  Key,
  Zap,
  Info,
  CheckCircle2,
  AlertCircle,
  PlayCircle,
} from "lucide-react";
import { toast } from "sonner";
import { apiClient } from "@/shared/api/serverClient";

interface EmbeddingProvider {
  id: string;
  name: string;
  description: string;
  models: string[];
  requires_api_key: boolean;
  default_model: string;
}

interface EmbeddingConfig {
  provider: string;
  model: string;
  has_api_key: boolean;
  base_url: string | null;
  dimensions: number;
  batch_size: number;
}

interface TestResult {
  success: boolean;
  message: string;
  dimensions?: number;
  sample_embedding?: number[];
  latency_ms?: number;
}

export default function EmbeddingConfigPanel() {
  const [providers, setProviders] = useState<EmbeddingProvider[]>([]);
  const [currentConfig, setCurrentConfig] = useState<EmbeddingConfig | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [testing, setTesting] = useState(false);
  const [testResult, setTestResult] = useState<TestResult | null>(null);

  // 表单状态
  const [selectedProvider, setSelectedProvider] = useState("");
  const [selectedModel, setSelectedModel] = useState("");
  const [apiKey, setApiKey] = useState("");
  const [clearSavedKey, setClearSavedKey] = useState(false);
  const [baseUrl, setBaseUrl] = useState("");
  const [customDimension, setCustomDimension] = useState<number | null>(null);
  const [batchSize, setBatchSize] = useState(100);

  // 加载数据
  useEffect(() => {
    loadData();
  }, []);

  // 用户手动切换 provider 时更新为默认模型
  const handleProviderChange = (newProvider: string) => {
    setSelectedProvider(newProvider);
    setApiKey("");
    setClearSavedKey(false);
    // 切换 provider 时重置为该 provider 的默认模型
    const provider = providers.find((p) => p.id === newProvider);
    if (provider) {
      setSelectedModel(provider.default_model);
    }
  };

  const loadData = async () => {
    try {
      setLoading(true);
      const [providersRes, configRes] = await Promise.all([
        apiClient.get("/embedding/providers"),
        apiClient.get("/embedding/config"),
      ]);

      setProviders(providersRes.data);
      setCurrentConfig(configRes.data);

      // 设置表单默认值
      if (configRes.data) {
        setSelectedProvider(configRes.data.provider);
        setSelectedModel(configRes.data.model);
        setApiKey("");
        setClearSavedKey(false);
        setBaseUrl(configRes.data.base_url || "");
        setCustomDimension(configRes.data.dimensions || null);
        setBatchSize(configRes.data.batch_size);
      }
    } catch (error) {
      toast.error("加载配置失败");
    } finally {
      setLoading(false);
    }
  };

  const hasSavedKey = currentConfig?.has_api_key && currentConfig.provider === selectedProvider
    && (currentConfig.base_url || "") === baseUrl;
  const requestKey = apiKey || (clearSavedKey ? null : undefined);

  const handleSave = async () => {
    if (!selectedProvider || !selectedModel) {
      toast.error("请选择提供商和模型");
      return;
    }

    try {
      setSaving(true);
      await apiClient.put("/embedding/config", {
        provider: selectedProvider,
        model: selectedModel,
        api_key: requestKey,
        base_url: baseUrl || undefined,
        dimensions: customDimension || undefined,
        batch_size: batchSize,
      });

      toast.success("配置已保存");
      await loadData();
    } catch (error: any) {
      toast.error(error.response?.data?.detail || "保存失败");
    } finally {
      setSaving(false);
    }
  };

  const handleTest = async () => {
    if (!selectedProvider || !selectedModel) {
      toast.error("请选择提供商和模型");
      return;
    }

    try {
      setTesting(true);
      setTestResult(null);

      const response = await apiClient.post("/embedding/test", {
        provider: selectedProvider,
        model: selectedModel,
        api_key: requestKey,
        base_url: baseUrl || undefined,
        dimension: customDimension || undefined,
      });

      setTestResult(response.data);

      if (response.data.success) {
        toast.success("测试成功");
      } else {
        toast.error("测试失败");
      }
    } catch (error: any) {
      setTestResult({
        success: false,
        message: error.response?.data?.detail || "测试失败",
      });
      toast.error("测试失败");
    } finally {
      setTesting(false);
    }
  };

  const selectedProviderInfo = providers.find((p) => p.id === selectedProvider);

  if (loading) {
    return (
      <div className="flex items-center justify-center min-h-[300px]">
        <div className="text-center space-y-4">
          <div className="loading-spinner mx-auto" />
          <p className="text-muted-foreground font-mono text-sm uppercase tracking-wider">加载配置中...</p>
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {/* 当前配置状态 */}
      {currentConfig && (
        <div className="cyber-card p-4 border-primary/30">
          <div className="flex items-center gap-2 mb-3">
            <Server className="w-4 h-4 text-primary" />
            <span className="font-mono font-bold text-sm uppercase text-foreground">当前配置</span>
          </div>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
            <div className="bg-muted p-3 rounded-lg border border-border">
              <p className="text-xs text-muted-foreground uppercase mb-1">提供商</p>
              <Badge className="bg-primary/20 text-primary border-primary/50 font-mono">
                {currentConfig.provider}
              </Badge>
            </div>
            <div className="bg-muted p-3 rounded-lg border border-border">
              <p className="text-xs text-muted-foreground uppercase mb-1">模型</p>
              <p className="font-mono text-sm text-foreground truncate">{currentConfig.model}</p>
            </div>
            <div className="bg-muted p-3 rounded-lg border border-border">
              <p className="text-xs text-muted-foreground uppercase mb-1">向量维度</p>
              <p className="font-mono text-sm text-foreground">{currentConfig.dimensions}</p>
            </div>
            <div className="bg-muted p-3 rounded-lg border border-border">
              <p className="text-xs text-muted-foreground uppercase mb-1">批处理大小</p>
              <p className="font-mono text-sm text-foreground">{currentConfig.batch_size}</p>
            </div>
          </div>
        </div>
      )}

      {/* 配置表单 */}
      <div className="cyber-card p-6 space-y-6">
        {/* 提供商选择 */}
        <div className="space-y-2">
          <Label className="text-xs font-bold text-muted-foreground uppercase">嵌入模型提供商</Label>
          <Select value={selectedProvider} onValueChange={handleProviderChange}>
            <SelectTrigger className="h-12 cyber-input">
              <SelectValue placeholder="选择提供商" />
            </SelectTrigger>
            <SelectContent className="cyber-dialog border-border">
              {providers.map((provider) => (
                <SelectItem key={provider.id} value={provider.id} className="font-mono">
                  <div className="flex items-center gap-2">
                    <span>{provider.name}</span>
                    {provider.requires_api_key ? (
                      <Key className="w-3 h-3 text-amber-400" />
                    ) : (
                      <Cpu className="w-3 h-3 text-emerald-400" />
                    )}
                  </div>
                </SelectItem>
              ))}
            </SelectContent>
          </Select>

          {selectedProviderInfo && (
            <p className="text-xs text-muted-foreground flex items-center gap-1">
              <Info className="w-3 h-3 text-sky-400" />
              {selectedProviderInfo.description}
            </p>
          )}
        </div>

        {/* 模型选择/输入 */}
        {selectedProviderInfo && (
          <div className="space-y-2">
            <Label className="text-xs font-bold text-muted-foreground uppercase">模型</Label>
            <Input
              type="text"
              value={selectedModel}
              onChange={(e) => setSelectedModel(e.target.value)}
              placeholder="输入模型名称"
              className="h-10 cyber-input"
            />
            {selectedProviderInfo.models.length > 0 && (
              <div className="flex flex-wrap gap-2 mt-2">
                <span className="text-xs text-muted-foreground">预设模型：</span>
                {selectedProviderInfo.models.map((model) => (
                  <button
                    key={model}
                    type="button"
                    onClick={() => setSelectedModel(model)}
                    className={`px-2 py-1 text-xs font-mono rounded border transition-colors ${
                      selectedModel === model
                        ? "bg-primary/20 border-primary/50 text-primary"
                        : "bg-muted border-border text-muted-foreground hover:border-border hover:text-foreground"
                    }`}
                  >
                    {model}
                  </button>
                ))}
              </div>
            )}
          </div>
        )}

        {/* API Key */}
        {selectedProviderInfo?.requires_api_key && (
          <div className="space-y-2">
            <Label className="text-xs font-bold text-muted-foreground uppercase">
              API Key
            </Label>
            <Input
              type="password"
              value={apiKey}
              onChange={(e) => setApiKey(e.target.value)}
              placeholder={hasSavedKey && !clearSavedKey ? "已保存，输入新密钥可替换" : "留空以使用部署者配置的 API Key"}
              className="h-10 cyber-input"
            />
            {hasSavedKey && !apiKey && (
              <Button type="button" variant="ghost" onClick={() => setClearSavedKey(!clearSavedKey)}>
                {clearSavedKey ? "保留已保存的密钥" : "改用部署者密钥"}
              </Button>
            )}
          </div>
        )}

        {/* 自定义端点 */}
        <div className="space-y-2">
          <Label className="text-xs font-bold text-muted-foreground uppercase">
            自定义 API 端点 <span className="text-muted-foreground">(可选)</span>
          </Label>
          <Input
            type="url"
            value={baseUrl}
            onChange={(e) => setBaseUrl(e.target.value)}
            placeholder={
              selectedProvider === "ollama"
                ? "http://localhost:11434"
                : selectedProvider === "huggingface"
                ? "https://router.huggingface.co"
                : selectedProvider === "cohere"
                ? "https://api.cohere.com/v2"
                : selectedProvider === "jina"
                ? "https://api.jina.ai/v1"
                : "https://api.openai.com/v1"
            }
            className="h-10 cyber-input"
          />
          <p className="text-xs text-muted-foreground">
            用于 API 代理或自托管服务
          </p>
        </div>

        {/* 自定义向量维度 */}
        <div className="space-y-2">
          <Label className="text-xs font-bold text-muted-foreground uppercase">
            自定义向量维度 <span className="text-muted-foreground">(可选)</span>
          </Label>
          <Input
            type="number"
            value={customDimension || ""}
            onChange={(e) => setCustomDimension(e.target.value ? parseInt(e.target.value) : null)}
            placeholder="留空使用默认值"
            min={64}
            max={8192}
            className="h-10 cyber-input w-40"
          />
          <p className="text-xs text-muted-foreground">
            适用于 Ollama 等场景：同一模型不同参数规模可能有不同维度
            <br />
            例如 qwen3-embedding:0.6b=1024, qwen3-embedding:8b=4096
          </p>
        </div>

        {/* 批处理大小 */}
        <div className="space-y-2">
          <Label className="text-xs font-bold text-muted-foreground uppercase">批处理大小</Label>
          <Input
            type="number"
            value={batchSize}
            onChange={(e) => setBatchSize(parseInt(e.target.value) || 100)}
            min={1}
            max={500}
            className="h-10 cyber-input w-32"
          />
          <p className="text-xs text-muted-foreground">
            每批嵌入的文本数量，建议 50-100
          </p>
        </div>

        {/* 测试结果 */}
        {testResult && (
          <div
            className={`p-4 rounded-lg ${
              testResult.success
                ? "bg-emerald-500/10 border border-emerald-500/30"
                : "bg-rose-500/10 border border-rose-500/30"
            }`}
          >
            <div className="flex items-center gap-2 mb-2">
              {testResult.success ? (
                <CheckCircle2 className="w-5 h-5 text-emerald-400" />
              ) : (
                <AlertCircle className="w-5 h-5 text-rose-400" />
              )}
              <span
                className={`font-bold ${
                  testResult.success ? "text-emerald-400" : "text-rose-400"
                }`}
              >
                {testResult.success ? "测试成功" : "测试失败"}
              </span>
            </div>
            <p className="text-sm text-muted-foreground">{testResult.message}</p>
            {testResult.success && (
              <div className="mt-3 pt-3 border-t border-border text-xs text-muted-foreground space-y-1 font-mono">
                <div>向量维度: <span className="text-foreground">{testResult.dimensions}</span></div>
                <div>延迟: <span className="text-foreground">{testResult.latency_ms}ms</span></div>
                {testResult.sample_embedding && (
                  <div className="truncate">
                    示例向量: <span className="text-muted-foreground">[{testResult.sample_embedding.slice(0, 5).map((v) => v.toFixed(4)).join(", ")}...]</span>
                  </div>
                )}
              </div>
            )}
          </div>
        )}

        {/* 操作按钮 */}
        <div className="flex items-center gap-3 pt-4 border-t border-border border-dashed">
          <Button
            onClick={handleTest}
            disabled={testing || !selectedProvider || !selectedModel}
            variant="outline"
            className="cyber-btn-outline h-10"
          >
            {testing ? (
              <Loader2 className="w-4 h-4 mr-2 animate-spin" />
            ) : (
              <PlayCircle className="w-4 h-4 mr-2" />
            )}
            测试连接
          </Button>

          <Button
            onClick={handleSave}
            disabled={saving || !selectedProvider || !selectedModel}
            className="cyber-btn-primary h-10"
          >
            {saving ? (
              <Loader2 className="w-4 h-4 mr-2 animate-spin" />
            ) : (
              <Check className="w-4 h-4 mr-2" />
            )}
            保存配置
          </Button>

          <Button
            onClick={loadData}
            variant="ghost"
            className="cyber-btn-ghost ml-auto h-10"
          >
            <RefreshCw className="w-4 h-4" />
          </Button>
        </div>
      </div>

      {/* 说明 */}
      <div className="bg-muted border border-border p-4 rounded-lg text-xs space-y-3">
        <p className="font-bold uppercase text-muted-foreground flex items-center gap-2">
          <Info className="w-4 h-4 text-sky-400" />
          关于嵌入模型
        </p>
        <ul className="text-muted-foreground space-y-1 ml-6">
          <li>• 嵌入模型用于 Agent 审计的代码语义搜索 (RAG)</li>
          <li>• 与分析使用的 LLM 独立配置，互不影响</li>
          <li>• 推荐使用 <span className="text-foreground">OpenAI text-embedding-3-small</span> 或本地 <span className="text-foreground">Ollama</span></li>
          <li>• 向量维度影响存储空间和检索精度</li>
        </ul>

        {/* OpenAI 兼容 API 引导 */}
        <div className="mt-3 pt-3 border-t border-border/50">
          <p className="font-bold text-amber-400 flex items-center gap-2 mb-2">
            <Zap className="w-4 h-4" />
            使用 OpenAI 兼容 API
          </p>
          <p className="text-muted-foreground mb-2">
            许多服务商提供 OpenAI 兼容的 API，可以直接使用 <span className="text-foreground">openai</span> 作为提供商：
          </p>
          <ul className="text-muted-foreground space-y-1 ml-4">
            <li>• <span className="text-foreground">DeepSeek</span>: 端点填写 <code className="text-primary bg-primary/10 px-1 rounded">https://api.deepseek.com/v1</code></li>
            <li>• <span className="text-foreground">Moonshot</span>: 端点填写 <code className="text-primary bg-primary/10 px-1 rounded">https://api.moonshot.cn/v1</code></li>
            <li>• <span className="text-foreground">智谱 GLM</span>: 端点填写 <code className="text-primary bg-primary/10 px-1 rounded">https://open.bigmodel.cn/api/paas/v4</code></li>
          </ul>
          <p className="text-muted-foreground mt-2 text-[11px]">
            提示：选择 openai 提供商，填入对应服务的 API Key 和自定义端点即可
          </p>
        </div>
      </div>
    </div>
  );
}

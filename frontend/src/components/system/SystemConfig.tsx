/**
 * System Config Component
 * Cyberpunk Terminal Aesthetic
 */

import { useState, useEffect } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Textarea } from "@/components/ui/textarea";
import { AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent, AlertDialogDescription, AlertDialogFooter, AlertDialogHeader, AlertDialogTitle } from "@/components/ui/alert-dialog";
import {
  Settings, Save, RotateCcw, Eye, EyeOff, CheckCircle2, AlertCircle,
  Info, Zap, Globe, PlayCircle, Brain, Key, Copy, Trash2, Terminal, ServerCrash
} from "lucide-react";
import { toast } from "sonner";
import { api } from "@/shared/api/database";
import EmbeddingConfig from "@/components/agent/EmbeddingConfig";
import { generateSSHKey, getSSHKey, deleteSSHKey, testSSHKey, clearKnownHosts } from "@/shared/api/sshKeys";

// LLM Providers - 2025
const LLM_PROVIDERS = [
  { value: 'openai', label: 'OpenAI GPT', icon: '🟢', category: 'litellm', hint: 'gpt-5, gpt-5-mini, o3 等' },
  { value: 'claude', label: 'Anthropic Claude', icon: '🟣', category: 'litellm', hint: 'claude-sonnet-4.5, claude-opus-4 等' },
  { value: 'gemini', label: 'Google Gemini', icon: '🔵', category: 'litellm', hint: 'gemini-3-pro, gemini-3-flash 等' },
  { value: 'deepseek', label: 'DeepSeek', icon: '🔷', category: 'litellm', hint: 'deepseek-v3.1-terminus, deepseek-v3 等' },
  { value: 'qwen', label: '通义千问', icon: '🟠', category: 'litellm', hint: 'qwen3-max-instruct, qwen3-plus 等' },
  { value: 'zhipu', label: '智谱AI (GLM)', icon: '🔴', category: 'litellm', hint: 'glm-4.6, glm-4.5-flash 等' },
  { value: 'moonshot', label: 'Moonshot (Kimi)', icon: '🌙', category: 'litellm', hint: 'kimi-k2, kimi-k1.5 等' },
  { value: 'atlascloud', label: 'Atlas Cloud', icon: '☁️', category: 'litellm', hint: 'deepseek-ai/DeepSeek-V3.1-Terminus, zai-org/glm-4.7 等' },
  { value: 'ollama', label: 'Ollama 本地', icon: '🖥️', category: 'litellm', hint: 'llama3.3-70b, qwen3-8b 等' },
  { value: 'baidu', label: '百度文心', icon: '📘', category: 'native', hint: 'ernie-4.5 (需要 API_KEY:SECRET_KEY)' },
  { value: 'minimax', label: 'MiniMax', icon: '⚡', category: 'native', hint: 'minimax-m2, minimax-m1 等' },
  { value: 'doubao', label: '字节豆包', icon: '🎯', category: 'native', hint: 'doubao-1.6-pro, doubao-1.5-pro 等' },
];

const DEFAULT_MODELS: Record<string, string> = {
  openai: 'gpt-5', claude: 'claude-sonnet-4.5', gemini: 'gemini-3-pro',
  deepseek: 'deepseek-v3.1-terminus', qwen: 'qwen3-max-instruct', zhipu: 'glm-4.6', moonshot: 'kimi-k2',
  atlascloud: 'deepseek-ai/DeepSeek-V3.1-Terminus',
  ollama: 'llama3.3-70b', baidu: 'ernie-4.5', minimax: 'minimax-m2', doubao: 'doubao-1.6-pro',
};

interface SystemConfigData {
  llmProvider: string; llmApiKey: string; llmModel: string; llmBaseUrl: string;
  llmTimeout: number; llmTemperature: number; llmMaxTokens: number;
  // Agent超时配置
  llmFirstTokenTimeout: number; llmStreamTimeout: number;
  agentTimeout: number; subAgentTimeout: number; toolTimeout: number;
  githubToken: string; gitlabToken: string; giteaToken: string;
  maxAnalyzeFiles: number; llmConcurrency: number; llmGapMs: number; outputLanguage: string;
}

export function SystemConfig() {
  const [config, setConfig] = useState<SystemConfigData | null>(null);
  const [loading, setLoading] = useState(true);
  const [showApiKey, setShowApiKey] = useState(false);
  const [hasChanges, setHasChanges] = useState(false);
  const [testingLLM, setTestingLLM] = useState(false);
  const [llmTestResult, setLlmTestResult] = useState<{ success: boolean; message: string; debug?: Record<string, unknown> } | null>(null);
  const [showDebugInfo, setShowDebugInfo] = useState(true);

  // SSH Key states
  const [sshKey, setSSHKey] = useState<{ has_key: boolean; public_key?: string; fingerprint?: string }>({ has_key: false });
  const [generatingKey, setGeneratingKey] = useState(false);
  const [deletingKey, setDeletingKey] = useState(false);
  const [clearingKnownHosts, setClearingKnownHosts] = useState(false);
  const [testingKey, setTestingKey] = useState(false);
  const [testRepoUrl, setTestRepoUrl] = useState("");
  const [showDeleteKeyDialog, setShowDeleteKeyDialog] = useState(false);

  useEffect(() => { loadConfig(); loadSSHKey(); }, []);

  const loadConfig = async () => {
    try {
      setLoading(true);
      console.log('[SystemConfig] 开始加载配置...');

      const backendConfig = await api.getUserConfig();

      console.log('[SystemConfig] 后端返回的原始数据:', JSON.stringify(backendConfig, null, 2));

      if (backendConfig) {
        const llmConfig = backendConfig.llmConfig || {};
        const otherConfig = backendConfig.otherConfig || {};

        const newConfig = {
          llmProvider: llmConfig.llmProvider || 'openai',
          llmApiKey: llmConfig.llmApiKey || '',
          llmModel: llmConfig.llmModel || '',
          llmBaseUrl: llmConfig.llmBaseUrl || '',
          llmTimeout: llmConfig.llmTimeout || 150000,
          llmTemperature: llmConfig.llmTemperature ?? 0.1,
          llmMaxTokens: llmConfig.llmMaxTokens || 4096,
          // Agent超时配置
          llmFirstTokenTimeout: llmConfig.llmFirstTokenTimeout || 30,
          llmStreamTimeout: llmConfig.llmStreamTimeout || 60,
          agentTimeout: llmConfig.agentTimeout || 1800,
          subAgentTimeout: llmConfig.subAgentTimeout || 600,
          toolTimeout: llmConfig.toolTimeout || 60,
          githubToken: otherConfig.githubToken || '',
          gitlabToken: otherConfig.gitlabToken || '',
          giteaToken: otherConfig.giteaToken || '',
          maxAnalyzeFiles: otherConfig.maxAnalyzeFiles ?? 0,
          llmConcurrency: otherConfig.llmConcurrency || 3,
          llmGapMs: otherConfig.llmGapMs || 2000,
          outputLanguage: otherConfig.outputLanguage || 'zh-CN',
        };

        console.log('[SystemConfig] 解析后的配置:', newConfig);
        setConfig(newConfig);

        console.log('✓ 配置已加载:', {
          provider: llmConfig.llmProvider,
          hasApiKey: !!llmConfig.llmApiKey,
          model: llmConfig.llmModel,
        });
      } else {
        console.warn('[SystemConfig] 后端返回空数据，使用默认配置');
        setConfig({
          llmProvider: 'openai', llmApiKey: '', llmModel: '', llmBaseUrl: '',
          llmTimeout: 150000, llmTemperature: 0.1, llmMaxTokens: 4096,
          llmFirstTokenTimeout: 30, llmStreamTimeout: 60,
          agentTimeout: 1800, subAgentTimeout: 600, toolTimeout: 60,
          githubToken: '', gitlabToken: '', giteaToken: '',
          maxAnalyzeFiles: 0, llmConcurrency: 3, llmGapMs: 2000, outputLanguage: 'zh-CN',
        });
      }
    } catch (error) {
      console.error('Failed to load config:', error);
      setConfig({
        llmProvider: 'openai', llmApiKey: '', llmModel: '', llmBaseUrl: '',
        llmTimeout: 150000, llmTemperature: 0.1, llmMaxTokens: 4096,
        llmFirstTokenTimeout: 30, llmStreamTimeout: 60,
        agentTimeout: 1800, subAgentTimeout: 600, toolTimeout: 60,
        githubToken: '', gitlabToken: '', giteaToken: '',
        maxAnalyzeFiles: 0, llmConcurrency: 3, llmGapMs: 2000, outputLanguage: 'zh-CN',
      });
    } finally {
      setLoading(false);
    }
  };

  // SSH Key functions
  const loadSSHKey = async () => {
    try {
      const data = await getSSHKey();
      setSSHKey(data);
    } catch (error) {
      console.error('Failed to load SSH key:', error);
    }
  };

  const handleGenerateSSHKey = async () => {
    try {
      setGeneratingKey(true);
      const data = await generateSSHKey();
      setSSHKey({ has_key: true, public_key: data.public_key, fingerprint: data.fingerprint });
      toast.success(data.message);
    } catch (error: any) {
      console.error('Failed to generate SSH key:', error);
      toast.error(error.response?.data?.detail || "生成SSH密钥失败");
    } finally {
      setGeneratingKey(false);
    }
  };

  const handleDeleteSSHKey = async () => {
    try {
      setDeletingKey(true);
      await deleteSSHKey();
      setSSHKey({ has_key: false });
      toast.success("SSH密钥已删除");
      setShowDeleteKeyDialog(false);
    } catch (error: any) {
      console.error('Failed to delete SSH key:', error);
      toast.error(error.response?.data?.detail || "删除SSH密钥失败");
    } finally {
      setDeletingKey(false);
    }
  };

  const handleTestSSHKey = async () => {
    if (!testRepoUrl) {
      toast.error("请输入仓库URL");
      return;
    }
    try {
      setTestingKey(true);
      const result = await testSSHKey(testRepoUrl);
      if (result.success) {
        toast.success("SSH连接测试成功");
        if (result.output) {
          console.log("SSH测试输出:", result.output);
        }
      } else {
        toast.error(result.message || "SSH连接测试失败", {
          description: result.output ? `详情: ${result.output.substring(0, 100)}...` : undefined,
          duration: 5000,
        });
        if (result.output) {
          console.error("SSH测试失败:", result.output);
        }
      }
    } catch (error: any) {
      console.error('Failed to test SSH key:', error);
      toast.error(error.response?.data?.detail || "测试SSH密钥失败");
    } finally {
      setTestingKey(false);
    }
  };

  const handleClearKnownHosts = async () => {
    try {
      setClearingKnownHosts(true);
      const result = await clearKnownHosts();
      if (result.success) {
        toast.success(result.message || "known_hosts已清理");
      } else {
        toast.error("清理known_hosts失败");
      }
    } catch (error: any) {
      console.error('Failed to clear known_hosts:', error);
      toast.error(error.response?.data?.detail || "清理known_hosts失败");
    } finally {
      setClearingKnownHosts(false);
    }
  };

  const handleCopyPublicKey = () => {
    if (sshKey.public_key) {
      navigator.clipboard.writeText(sshKey.public_key);
      toast.success("公钥已复制到剪贴板");
    }
  };

  const saveConfig = async () => {
    if (!config) return;
    try {
      const savedConfig = await api.updateUserConfig({
        llmConfig: {
          llmProvider: config.llmProvider, llmApiKey: config.llmApiKey,
          llmModel: config.llmModel, llmBaseUrl: config.llmBaseUrl,
          llmTimeout: config.llmTimeout, llmTemperature: config.llmTemperature,
          llmMaxTokens: config.llmMaxTokens,
          // Agent超时配置
          llmFirstTokenTimeout: config.llmFirstTokenTimeout,
          llmStreamTimeout: config.llmStreamTimeout,
          agentTimeout: config.agentTimeout,
          subAgentTimeout: config.subAgentTimeout,
          toolTimeout: config.toolTimeout,
        },
        otherConfig: {
          githubToken: config.githubToken, gitlabToken: config.gitlabToken, giteaToken: config.giteaToken,
          maxAnalyzeFiles: config.maxAnalyzeFiles, llmConcurrency: config.llmConcurrency,
          llmGapMs: config.llmGapMs, outputLanguage: config.outputLanguage,
        },
      });

      if (savedConfig) {
        const llmConfig = savedConfig.llmConfig || {};
        const otherConfig = savedConfig.otherConfig || {};
        setConfig({
          llmProvider: llmConfig.llmProvider || config.llmProvider,
          llmApiKey: llmConfig.llmApiKey || '',
          llmModel: llmConfig.llmModel || '',
          llmBaseUrl: llmConfig.llmBaseUrl || '',
          llmTimeout: llmConfig.llmTimeout || 150000,
          llmTemperature: llmConfig.llmTemperature ?? 0.1,
          llmMaxTokens: llmConfig.llmMaxTokens || 4096,
          // Agent超时配置
          llmFirstTokenTimeout: llmConfig.llmFirstTokenTimeout || 30,
          llmStreamTimeout: llmConfig.llmStreamTimeout || 60,
          agentTimeout: llmConfig.agentTimeout || 1800,
          subAgentTimeout: llmConfig.subAgentTimeout || 600,
          toolTimeout: llmConfig.toolTimeout || 60,
          githubToken: otherConfig.githubToken || '',
          gitlabToken: otherConfig.gitlabToken || '',
          giteaToken: otherConfig.giteaToken || '',
          maxAnalyzeFiles: otherConfig.maxAnalyzeFiles ?? 0,
          llmConcurrency: otherConfig.llmConcurrency || 3,
          llmGapMs: otherConfig.llmGapMs || 2000,
          outputLanguage: otherConfig.outputLanguage || 'zh-CN',
        });
      }

      setHasChanges(false);
      toast.success("配置已保存！");
    } catch (error) {
      toast.error(`保存失败: ${error instanceof Error ? error.message : '未知错误'}`);
    }
  };

  const resetConfig = async () => {
    if (!window.confirm("确定要重置为默认配置吗？")) return;
    try {
      await api.deleteUserConfig();
      await loadConfig();
      setHasChanges(false);
      toast.success("已重置为默认配置");
    } catch (error) {
      toast.error(`重置失败: ${error instanceof Error ? error.message : '未知错误'}`);
    }
  };

  const updateConfig = (key: keyof SystemConfigData, value: string | number) => {
    if (!config) return;
    setConfig(prev => prev ? { ...prev, [key]: value } : null);
    setHasChanges(true);
  };

  const testLLMConnection = async () => {
    if (!config) return;
    if (!config.llmApiKey && config.llmProvider !== 'ollama') {
      toast.error('请先配置 API Key');
      return;
    }
    setTestingLLM(true);
    setLlmTestResult(null);
    try {
      const result = await api.testLLMConnection({
        provider: config.llmProvider,
        apiKey: config.llmApiKey,
        model: config.llmModel || undefined,
        baseUrl: config.llmBaseUrl || undefined,
      });
      setLlmTestResult(result);
      if (result.success) toast.success(`连接成功！模型: ${result.model}`);
      else toast.error(`连接失败: ${result.message}`);
    } catch (error) {
      const msg = error instanceof Error ? error.message : '未知错误';
      setLlmTestResult({ success: false, message: msg });
      toast.error(`测试失败: ${msg}`);
    } finally {
      setTestingLLM(false);
    }
  };

  if (loading || !config) {
    return (
      <div className="flex items-center justify-center min-h-[400px]">
        <div className="text-center space-y-4">
          <div className="loading-spinner mx-auto" />
          <p className="text-muted-foreground font-mono text-sm uppercase tracking-wider">加载配置中...</p>
        </div>
      </div>
    );
  }

  const currentProvider = LLM_PROVIDERS.find(p => p.value === config.llmProvider);
  const isConfigured = config.llmApiKey !== '' || config.llmProvider === 'ollama';

  return (
    <div className="space-y-6">
      {/* Status Bar */}
      <div className={`cyber-card p-4 ${isConfigured ? 'border-emerald-500/30' : 'border-amber-500/30'}`}>
        <div className="flex items-center justify-between flex-wrap gap-4">
          <div className="flex items-center gap-4">
            <Info className="h-5 w-5 text-sky-400" />
            <span className="font-mono text-sm">
              {isConfigured ? (
                <span className="text-emerald-400 flex items-center gap-2">
                  <CheckCircle2 className="h-4 w-4" /> LLM 已配置 ({currentProvider?.label})
                </span>
              ) : (
                <span className="text-amber-400 flex items-center gap-2">
                  <AlertCircle className="h-4 w-4" /> 请配置 LLM API Key
                </span>
              )}
            </span>
          </div>
          <div className="flex gap-2">
            {hasChanges && (
              <Button onClick={saveConfig} size="sm" className="cyber-btn-primary h-8">
                <Save className="w-3 h-3 mr-2" /> 保存
              </Button>
            )}
            <Button onClick={resetConfig} variant="outline" size="sm" className="cyber-btn-ghost h-8">
              <RotateCcw className="w-3 h-3 mr-2" /> 重置
            </Button>
          </div>
        </div>
      </div>

      <Tabs defaultValue="llm" className="w-full">
        <TabsList className="grid w-full grid-cols-4 bg-muted border border-border p-1 h-auto gap-1 rounded-lg mb-6">
          <TabsTrigger value="llm" className="data-[state=active]:bg-primary data-[state=active]:text-foreground font-mono font-bold uppercase py-2.5 text-muted-foreground transition-all rounded text-xs flex items-center gap-2">
            <Zap className="w-3 h-3" /> LLM 配置
          </TabsTrigger>
          <TabsTrigger value="embedding" className="data-[state=active]:bg-primary data-[state=active]:text-foreground font-mono font-bold uppercase py-2.5 text-muted-foreground transition-all rounded text-xs flex items-center gap-2">
            <Brain className="w-3 h-3" /> 嵌入模型
          </TabsTrigger>
          <TabsTrigger value="analysis" className="data-[state=active]:bg-primary data-[state=active]:text-foreground font-mono font-bold uppercase py-2.5 text-muted-foreground transition-all rounded text-xs flex items-center gap-2">
            <Settings className="w-3 h-3" /> 分析参数
          </TabsTrigger>
          <TabsTrigger value="git" className="data-[state=active]:bg-primary data-[state=active]:text-foreground font-mono font-bold uppercase py-2.5 text-muted-foreground transition-all rounded text-xs flex items-center gap-2">
            <Globe className="w-3 h-3" /> Git 集成
          </TabsTrigger>
        </TabsList>

        {/* LLM Config */}
        <TabsContent value="llm" className="space-y-6">
          <div className="cyber-card p-6 space-y-6">
            {/* Provider Selection */}
            <div className="space-y-2">
              <Label className="text-xs font-bold text-muted-foreground uppercase">选择 LLM 提供商</Label>
              <Select value={config.llmProvider} onValueChange={(v) => updateConfig('llmProvider', v)}>
                <SelectTrigger className="h-12 cyber-input">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent className="cyber-dialog border-border">
                  <div className="px-2 py-1.5 text-xs font-bold text-muted-foreground uppercase">LiteLLM 统一适配 (推荐)</div>
                  {LLM_PROVIDERS.filter(p => p.category === 'litellm').map(p => (
                    <SelectItem key={p.value} value={p.value} className="font-mono">
                      <span className="flex items-center gap-2">
                        <span>{p.icon}</span>
                        <span>{p.label}</span>
                        <span className="text-xs text-muted-foreground">- {p.hint}</span>
                      </span>
                    </SelectItem>
                  ))}
                  <div className="px-2 py-1.5 text-xs font-bold text-muted-foreground uppercase mt-2">原生适配器</div>
                  {LLM_PROVIDERS.filter(p => p.category === 'native').map(p => (
                    <SelectItem key={p.value} value={p.value} className="font-mono">
                      <span className="flex items-center gap-2">
                        <span>{p.icon}</span>
                        <span>{p.label}</span>
                        <span className="text-xs text-muted-foreground">- {p.hint}</span>
                      </span>
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>

            {/* API Key */}
            {config.llmProvider !== 'ollama' && (
              <div className="space-y-2">
                <Label className="text-xs font-bold text-muted-foreground uppercase">API Key</Label>
                <div className="flex gap-2">
                  <Input
                    type={showApiKey ? 'text' : 'password'}
                    value={config.llmApiKey}
                    onChange={(e) => updateConfig('llmApiKey', e.target.value)}
                    placeholder={config.llmProvider === 'baidu' ? 'API_KEY:SECRET_KEY 格式' : '输入你的 API Key'}
                    className="h-12 cyber-input"
                  />
                  <Button
                    variant="outline"
                    size="icon"
                    onClick={() => setShowApiKey(!showApiKey)}
                    className="h-12 w-12 cyber-btn-ghost"
                  >
                    {showApiKey ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
                  </Button>
                </div>
              </div>
            )}

            {/* Model and Base URL */}
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              <div className="space-y-2">
                <Label className="text-xs font-bold text-muted-foreground uppercase">模型名称 (可选)</Label>
                <Input
                  value={config.llmModel}
                  onChange={(e) => updateConfig('llmModel', e.target.value)}
                  placeholder={`默认: ${DEFAULT_MODELS[config.llmProvider] || 'auto'}`}
                  className="h-10 cyber-input"
                />
              </div>
              <div className="space-y-2">
                <Label className="text-xs font-bold text-muted-foreground uppercase">API Base URL (可选)</Label>
                <Input
                  value={config.llmBaseUrl}
                  onChange={(e) => updateConfig('llmBaseUrl', e.target.value)}
                  placeholder="留空使用官方地址，或填入中转站地址"
                  className="h-10 cyber-input"
                />
              </div>
            </div>

            {/* Test Connection */}
            <div className="pt-4 border-t border-border border-dashed flex items-center justify-between flex-wrap gap-4">
              <div className="text-sm">
                <span className="font-bold text-foreground">测试连接</span>
                <span className="text-muted-foreground ml-2">验证配置是否正确</span>
              </div>
              <Button
                onClick={testLLMConnection}
                disabled={testingLLM || (!isConfigured && config.llmProvider !== 'ollama')}
                className="cyber-btn-primary h-10"
              >
                {testingLLM ? (
                  <>
                    <div className="loading-spinner w-4 h-4 mr-2" />
                    测试中...
                  </>
                ) : (
                  <>
                    <PlayCircle className="w-4 h-4 mr-2" />
                    测试
                  </>
                )}
              </Button>
            </div>
            {llmTestResult && (
              <div className={`p-3 rounded-lg ${llmTestResult.success ? 'bg-emerald-500/10 border border-emerald-500/30' : 'bg-rose-500/10 border border-rose-500/30'}`}>
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2 text-sm">
                    {llmTestResult.success ? (
                      <CheckCircle2 className="h-4 w-4 text-emerald-400" />
                    ) : (
                      <AlertCircle className="h-4 w-4 text-rose-400" />
                    )}
                    <span className={llmTestResult.success ? 'text-emerald-300/80' : 'text-rose-300/80'}>
                      {llmTestResult.message}
                    </span>
                  </div>
                  {llmTestResult.debug && (
                    <button
                      onClick={() => setShowDebugInfo(!showDebugInfo)}
                      className="text-xs text-muted-foreground hover:text-foreground underline"
                    >
                      {showDebugInfo ? '隐藏调试信息' : '显示调试信息'}
                    </button>
                  )}
                </div>
                {showDebugInfo && llmTestResult.debug && (
                  <div className="mt-3 pt-3 border-t border-border/50">
                    <div className="text-xs font-mono space-y-1 text-muted-foreground">
                      <div className="font-bold text-foreground mb-2">连接信息:</div>
                      <div>Provider: <span className="text-foreground">{String(llmTestResult.debug.provider)}</span></div>
                      <div>Model: <span className="text-foreground">{String(llmTestResult.debug.model_used || llmTestResult.debug.model_requested || 'N/A')}</span></div>
                      <div>Base URL: <span className="text-foreground">{String(llmTestResult.debug.base_url_used || llmTestResult.debug.base_url_requested || '(default)')}</span></div>
                      <div>Adapter: <span className="text-foreground">{String(llmTestResult.debug.adapter_type || 'N/A')}</span></div>
                      <div>API Key: <span className="text-foreground">{String(llmTestResult.debug.api_key_prefix)} (长度: {String(llmTestResult.debug.api_key_length)})</span></div>
                      <div>耗时: <span className="text-foreground">{String(llmTestResult.debug.elapsed_time_ms || 'N/A')} ms</span></div>

                      {/* 用户保存的配置参数 */}
                      {llmTestResult.debug.saved_config && (
                        <div className="mt-3 pt-2 border-t border-border/30">
                          <div className="font-bold text-cyan-400 mb-2">已保存的配置参数:</div>
                          <div className="grid grid-cols-2 gap-x-4 gap-y-1">
                            <div>温度: <span className="text-foreground">{String((llmTestResult.debug.saved_config as Record<string, unknown>).temperature ?? 'N/A')}</span></div>
                            <div>最大Tokens: <span className="text-foreground">{String((llmTestResult.debug.saved_config as Record<string, unknown>).max_tokens ?? 'N/A')}</span></div>
                            <div>超时: <span className="text-foreground">{String((llmTestResult.debug.saved_config as Record<string, unknown>).timeout_ms ?? 'N/A')} ms</span></div>
                            <div>请求间隔: <span className="text-foreground">{String((llmTestResult.debug.saved_config as Record<string, unknown>).gap_ms ?? 'N/A')} ms</span></div>
                            <div>并发数: <span className="text-foreground">{String((llmTestResult.debug.saved_config as Record<string, unknown>).concurrency ?? 'N/A')}</span></div>
                            <div>最大文件数: <span className="text-foreground">{String((llmTestResult.debug.saved_config as Record<string, unknown>).max_analyze_files ?? 'N/A')}</span></div>
                            <div>输出语言: <span className="text-foreground">{String((llmTestResult.debug.saved_config as Record<string, unknown>).output_language ?? 'N/A')}</span></div>
                          </div>
                        </div>
                      )}

                      {/* 测试时实际使用的参数 */}
                      {llmTestResult.debug.test_params && (
                        <div className="mt-2 pt-2 border-t border-border/30">
                          <div className="font-bold text-emerald-400 mb-2">测试时使用的参数:</div>
                          <div className="grid grid-cols-3 gap-x-4">
                            <div>温度: <span className="text-foreground">{String((llmTestResult.debug.test_params as Record<string, unknown>).temperature ?? 'N/A')}</span></div>
                            <div>超时: <span className="text-foreground">{String((llmTestResult.debug.test_params as Record<string, unknown>).timeout ?? 'N/A')}s</span></div>
                            <div>MaxTokens: <span className="text-foreground">{String((llmTestResult.debug.test_params as Record<string, unknown>).max_tokens ?? 'N/A')}</span></div>
                          </div>
                        </div>
                      )}

                      {llmTestResult.debug.error_category && (
                        <div className="mt-2">错误类型: <span className="text-rose-400">{String(llmTestResult.debug.error_category)}</span></div>
                      )}
                      {llmTestResult.debug.error_type && (
                        <div>异常类型: <span className="text-rose-400">{String(llmTestResult.debug.error_type)}</span></div>
                      )}
                      {llmTestResult.debug.status_code && (
                        <div>HTTP 状态码: <span className="text-rose-400">{String(llmTestResult.debug.status_code)}</span></div>
                      )}
                      {llmTestResult.debug.api_response && (
                        <div className="mt-2">
                          <div className="font-bold text-amber-400">API 服务器返回:</div>
                          <pre className="mt-1 p-2 bg-amber-500/10 border border-amber-500/30 rounded text-xs overflow-x-auto">
                            {String(llmTestResult.debug.api_response)}
                          </pre>
                        </div>
                      )}
                      {llmTestResult.debug.error_message && (
                        <div className="mt-2">
                          <div className="font-bold text-foreground">完整错误信息:</div>
                          <pre className="mt-1 p-2 bg-background/50 rounded text-xs overflow-x-auto max-h-32 overflow-y-auto">
                            {String(llmTestResult.debug.error_message)}
                          </pre>
                        </div>
                      )}
                      {llmTestResult.debug.traceback && (
                        <details className="mt-2">
                          <summary className="cursor-pointer text-muted-foreground hover:text-foreground">完整堆栈跟踪</summary>
                          <pre className="mt-1 p-2 bg-background/50 rounded text-xs overflow-x-auto max-h-48 overflow-y-auto whitespace-pre-wrap">
                            {String(llmTestResult.debug.traceback)}
                          </pre>
                        </details>
                      )}
                    </div>
                  </div>
                )}
              </div>
            )}

            {/* Advanced Parameters */}
            <details open className="pt-4 border-t border-border border-dashed">
              <summary className="font-bold uppercase cursor-pointer hover:text-primary text-muted-foreground text-sm">高级参数</summary>

              {/* LLM基础参数 */}
              <div className="mt-4 mb-2">
                <span className="text-xs text-muted-foreground uppercase font-semibold">LLM 基础参数</span>
              </div>
              <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
                <div className="space-y-2">
                  <Label className="text-xs text-muted-foreground uppercase">请求超时 (毫秒)</Label>
                  <Input
                    type="number"
                    value={config.llmTimeout}
                    onChange={(e) => updateConfig('llmTimeout', Number(e.target.value))}
                    className="h-10 cyber-input"
                  />
                  <p className="text-xs text-muted-foreground">单次LLM请求的超时时间</p>
                </div>
                <div className="space-y-2">
                  <Label className="text-xs text-muted-foreground uppercase">温度 (0-2)</Label>
                  <Input
                    type="number"
                    step="0.1"
                    min="0"
                    max="2"
                    value={config.llmTemperature}
                    onChange={(e) => updateConfig('llmTemperature', Number(e.target.value))}
                    className="h-10 cyber-input"
                  />
                  <p className="text-xs text-muted-foreground">控制输出随机性，越低越确定</p>
                </div>
                <div className="space-y-2">
                  <Label className="text-xs text-muted-foreground uppercase">最大 Tokens</Label>
                  <Input
                    type="number"
                    value={config.llmMaxTokens}
                    onChange={(e) => updateConfig('llmMaxTokens', Number(e.target.value))}
                    className="h-10 cyber-input"
                  />
                  <p className="text-xs text-muted-foreground">单次请求最大输出Token数</p>
                </div>
              </div>

              {/* Agent超时配置 */}
              <div className="mt-6 mb-2">
                <span className="text-xs text-muted-foreground uppercase font-semibold">Agent 超时配置</span>
              </div>
              <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
                <div className="space-y-2">
                  <Label className="text-xs text-muted-foreground uppercase">首Token超时 (秒)</Label>
                  <Input
                    type="number"
                    value={config.llmFirstTokenTimeout}
                    onChange={(e) => updateConfig('llmFirstTokenTimeout', Number(e.target.value))}
                    className="h-10 cyber-input"
                  />
                  <p className="text-xs text-muted-foreground">等待LLM首个Token的超时时间</p>
                </div>
                <div className="space-y-2">
                  <Label className="text-xs text-muted-foreground uppercase">流式超时 (秒)</Label>
                  <Input
                    type="number"
                    value={config.llmStreamTimeout}
                    onChange={(e) => updateConfig('llmStreamTimeout', Number(e.target.value))}
                    className="h-10 cyber-input"
                  />
                  <p className="text-xs text-muted-foreground">流式输出中两个Token间的超时</p>
                </div>
                <div className="space-y-2">
                  <Label className="text-xs text-muted-foreground uppercase">工具超时 (秒)</Label>
                  <Input
                    type="number"
                    value={config.toolTimeout}
                    onChange={(e) => updateConfig('toolTimeout', Number(e.target.value))}
                    className="h-10 cyber-input"
                  />
                  <p className="text-xs text-muted-foreground">单个工具执行的默认超时时间</p>
                </div>
                <div className="space-y-2">
                  <Label className="text-xs text-muted-foreground uppercase">子Agent超时 (秒)</Label>
                  <Input
                    type="number"
                    value={config.subAgentTimeout}
                    onChange={(e) => updateConfig('subAgentTimeout', Number(e.target.value))}
                    className="h-10 cyber-input"
                  />
                  <p className="text-xs text-muted-foreground">子Agent (Recon/Analysis/Verification) 超时</p>
                </div>
                <div className="space-y-2">
                  <Label className="text-xs text-muted-foreground uppercase">总超时 (秒)</Label>
                  <Input
                    type="number"
                    value={config.agentTimeout}
                    onChange={(e) => updateConfig('agentTimeout', Number(e.target.value))}
                    className="h-10 cyber-input"
                  />
                  <p className="text-xs text-muted-foreground">整个Agent审计任务的最大时间</p>
                </div>
              </div>
            </details>
          </div>

          {/* Usage Notes */}
          <div className="bg-muted border border-border p-4 rounded-lg text-xs space-y-2">
            <p className="font-bold uppercase text-muted-foreground flex items-center gap-2">
              <Info className="w-4 h-4 text-sky-400" />
              配置说明
            </p>
            <p className="text-muted-foreground">• <strong className="text-muted-foreground">LiteLLM 统一适配</strong>: 大多数提供商通过 LiteLLM 统一处理，支持自动重试和负载均衡</p>
            <p className="text-muted-foreground">• <strong className="text-muted-foreground">原生适配器</strong>: 百度、MiniMax、豆包因 API 格式特殊，使用专用适配器</p>
            <p className="text-muted-foreground">• <strong className="text-muted-foreground">API 中转站</strong>: 在 Base URL 填入中转站地址即可，API Key 填中转站提供的 Key</p>
          </div>
        </TabsContent>

        {/* Embedding Config */}
        <TabsContent value="embedding" className="space-y-6">
          <EmbeddingConfig />
        </TabsContent>

        {/* Analysis Parameters */}
        <TabsContent value="analysis" className="space-y-6">
          <div className="cyber-card p-6 space-y-6">
            <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
              <div className="space-y-2">
                <Label className="text-xs font-bold text-muted-foreground uppercase">最大分析文件数</Label>
                <Input
                  type="number"
                  value={config.maxAnalyzeFiles}
                  onChange={(e) => updateConfig('maxAnalyzeFiles', Number(e.target.value))}
                  className="h-10 cyber-input"
                />
                <p className="text-xs text-muted-foreground">单次任务最多处理的文件数量</p>
              </div>
              <div className="space-y-2">
                <Label className="text-xs font-bold text-muted-foreground uppercase">LLM 并发数</Label>
                <Input
                  type="number"
                  value={config.llmConcurrency}
                  onChange={(e) => updateConfig('llmConcurrency', Number(e.target.value))}
                  className="h-10 cyber-input"
                />
                <p className="text-xs text-muted-foreground">同时发送的 LLM 请求数量</p>
              </div>
              <div className="space-y-2">
                <Label className="text-xs font-bold text-muted-foreground uppercase">请求间隔 (毫秒)</Label>
                <Input
                  type="number"
                  value={config.llmGapMs}
                  onChange={(e) => updateConfig('llmGapMs', Number(e.target.value))}
                  className="h-10 cyber-input"
                />
                <p className="text-xs text-muted-foreground">每个请求之间的延迟时间</p>
              </div>
              <div className="space-y-2">
                <Label className="text-xs font-bold text-muted-foreground uppercase">输出语言</Label>
                <Select value={config.outputLanguage} onValueChange={(v) => updateConfig('outputLanguage', v)}>
                  <SelectTrigger className="h-10 cyber-input">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent className="cyber-dialog border-border">
                    <SelectItem value="zh-CN" className="font-mono">🇨🇳 中文</SelectItem>
                    <SelectItem value="en-US" className="font-mono">🇺🇸 English</SelectItem>
                  </SelectContent>
                </Select>
                <p className="text-xs text-muted-foreground">代码审查结果的输出语言</p>
              </div>
            </div>
          </div>
        </TabsContent>

        {/* Git Integration */}
        <TabsContent value="git" className="space-y-6">
          <div className="cyber-card p-6 space-y-6">
            <div className="space-y-2">
              <Label className="text-xs font-bold text-muted-foreground uppercase">GitHub Token (可选)</Label>
              <Input
                type="password"
                value={config.githubToken}
                onChange={(e) => updateConfig('githubToken', e.target.value)}
                placeholder="ghp_xxxxxxxxxxxx"
                className="h-10 cyber-input"
              />
              <p className="text-xs text-muted-foreground">
                用于访问私有仓库。获取:{' '}
                <a href="https://github.com/settings/tokens" target="_blank" rel="noopener noreferrer" className="text-primary hover:underline">
                  github.com/settings/tokens
                </a>
              </p>
            </div>
            <div className="space-y-2">
              <Label className="text-xs font-bold text-muted-foreground uppercase">GitLab Token (可选)</Label>
              <Input
                type="password"
                value={config.gitlabToken}
                onChange={(e) => updateConfig('gitlabToken', e.target.value)}
                placeholder="glpat-xxxxxxxxxxxx"
                className="h-10 cyber-input"
              />
              <p className="text-xs text-muted-foreground">
                用于访问私有仓库。获取:{' '}
                <a href="https://gitlab.com/-/profile/personal_access_tokens" target="_blank" rel="noopener noreferrer" className="text-primary hover:underline">
                  gitlab.com/-/profile/personal_access_tokens
                </a>
              </p>
            </div>
            <div className="space-y-2">
              <Label className="text-xs font-bold text-muted-foreground uppercase">Gitea Token (可选)</Label>
              <Input
                type="password"
                value={config.giteaToken}
                onChange={(e) => updateConfig('giteaToken', e.target.value)}
                placeholder="sha1_xxxxxxxxxxxx"
                className="h-10 cyber-input"
              />
              <p className="text-xs text-muted-foreground">
                用于访问 Gitea 私有仓库。获取:{' '}
                <span className="text-primary">
                  [your-gitea-instance]/user/settings/applications
                </span>
              </p>
            </div>
            <div className="bg-muted border border-border p-4 rounded-lg text-xs">
              <p className="font-bold text-muted-foreground flex items-center gap-2 mb-2">
                <Info className="w-4 h-4 text-sky-400" />
                提示
              </p>
              <p className="text-muted-foreground">• 公开仓库无需配置 Token</p>
              <p className="text-muted-foreground">• 私有仓库需要配置对应平台的 Token</p>
            </div>
          </div>

          {/* SSH Key Management */}
          <div className="cyber-card p-6 space-y-4">
            <div className="flex items-center gap-3 mb-2">
              <Key className="w-5 h-5 text-emerald-400" />
              <h3 className="text-lg font-bold uppercase tracking-wider text-foreground">SSH 密钥管理</h3>
            </div>

            <div className="flex items-start gap-3 p-4 bg-emerald-500/10 border border-emerald-500/20 rounded-lg">
              <div className="flex-shrink-0 mt-0.5">
                <div className="w-8 h-8 rounded-lg bg-emerald-500/20 flex items-center justify-center">
                  <Key className="w-4 h-4 text-emerald-400" />
                </div>
              </div>
              <div className="flex-1 min-w-0">
                <p className="text-sm text-foreground font-medium mb-1">
                  使用 SSH 密钥访问 Git 仓库
                </p>
                <p className="text-xs text-muted-foreground leading-relaxed">
                  生成 SSH 密钥对后，将公钥添加到 GitHub/GitLab，即可使用 SSH URL 访问私有仓库。私钥将被加密存储。
                </p>
              </div>
            </div>

            {!sshKey.has_key ? (
              <div className="text-center py-8">
                <div className="inline-flex items-center justify-center w-16 h-16 rounded-full bg-muted/50 mb-4">
                  <Key className="w-8 h-8 text-muted-foreground" />
                </div>
                <p className="text-sm text-muted-foreground mb-4">尚未生成 SSH 密钥</p>
                <Button
                  onClick={handleGenerateSSHKey}
                  disabled={generatingKey}
                  className="cyber-btn-primary h-10"
                >
                  {generatingKey ? (
                    <>
                      <div className="loading-spinner w-4 h-4 mr-2" />
                      生成中...
                    </>
                  ) : (
                    <>
                      <Key className="w-4 h-4 mr-2" />
                      生成 SSH 密钥
                    </>
                  )}
                </Button>
              </div>
            ) : (
              <div className="space-y-4">
                {/* Public Key Display */}
                <div className="space-y-2">
                  <div className="flex items-center justify-between">
                    <Label className="text-xs font-bold text-muted-foreground uppercase flex items-center gap-2">
                      <CheckCircle2 className="w-3 h-3 text-emerald-400" />
                      SSH 公钥
                    </Label>
                    <Button
                      size="sm"
                      variant="ghost"
                      onClick={handleCopyPublicKey}
                      className="h-8 text-xs"
                    >
                      <Copy className="w-3 h-3 mr-1" />
                      复制
                    </Button>
                  </div>
                  <Textarea
                    value={sshKey.public_key || ""}
                    readOnly
                    className="cyber-input font-mono text-xs h-24 resize-none"
                  />

                  {/* 显示指纹 */}
                  {sshKey.fingerprint && (
                    <div className="p-3 bg-muted/50 rounded border border-border">
                      <Label className="text-xs font-bold text-muted-foreground uppercase mb-1 block">
                        公钥指纹 (SHA256)
                      </Label>
                      <code className="text-xs text-emerald-400 font-mono break-all">
                        {sshKey.fingerprint}
                      </code>
                    </div>
                  )}

                  <p className="text-xs text-muted-foreground">
                    请将此公钥添加到 <a href="https://github.com/settings/keys" target="_blank" rel="noopener noreferrer" className="text-primary hover:underline">GitHub</a> 或 <a href="https://gitlab.com/-/profile/keys" target="_blank" rel="noopener noreferrer" className="text-primary hover:underline">GitLab</a> 账户
                  </p>
                </div>

                {/* Test SSH Connection */}
                <div className="space-y-2 pt-4 border-t border-border">
                  <Label className="text-xs font-bold text-muted-foreground uppercase">
                    测试 SSH 连接
                  </Label>
                  <div className="flex gap-2">
                    <Input
                      placeholder="git@github.com:username/repo.git"
                      value={testRepoUrl}
                      onChange={(e) => setTestRepoUrl(e.target.value)}
                      className="cyber-input font-mono text-xs"
                    />
                    <Button
                      onClick={handleTestSSHKey}
                      disabled={testingKey}
                      className="cyber-btn-outline whitespace-nowrap"
                    >
                      {testingKey ? (
                        <>
                          <div className="loading-spinner w-4 h-4 mr-2" />
                          测试中...
                        </>
                      ) : (
                        <>
                          <Terminal className="w-4 h-4 mr-2" />
                          测试连接
                        </>
                      )}
                    </Button>
                  </div>
                </div>

                {/* Delete Key and Clear Known Hosts */}
                <div className="flex justify-end gap-2 pt-4 border-t border-border">
                  <Button
                    variant="outline"
                    onClick={handleClearKnownHosts}
                    disabled={clearingKnownHosts}
                    className="cyber-btn-outline h-10"
                  >
                    {clearingKnownHosts ? (
                      <>
                        <div className="loading-spinner w-4 h-4 mr-2" />
                        清理中...
                      </>
                    ) : (
                      <>
                        <ServerCrash className="w-4 h-4 mr-2" />
                        清理 known_hosts
                      </>
                    )}
                  </Button>
                  <Button
                    variant="destructive"
                    onClick={() => setShowDeleteKeyDialog(true)}
                    className="bg-rose-500/20 hover:bg-rose-500/30 text-rose-400 border border-rose-500/30 h-10"
                  >
                    <Trash2 className="w-4 h-4 mr-2" />
                    删除密钥
                  </Button>
                </div>
              </div>
            )}
          </div>
        </TabsContent>
      </Tabs>

      {/* Floating Save Button */}
      {hasChanges && (
        <div className="fixed bottom-6 right-6 cyber-card p-4 z-50">
          <Button onClick={saveConfig} className="cyber-btn-primary h-12">
            <Save className="w-4 h-4 mr-2" /> 保存所有更改
          </Button>
        </div>
      )}

      {/* Delete SSH Key Confirmation Dialog */}
      <AlertDialog open={showDeleteKeyDialog} onOpenChange={setShowDeleteKeyDialog}>
        <AlertDialogContent className="cyber-card border-rose-500/30 cyber-dialog">
          <AlertDialogHeader>
            <AlertDialogTitle className="text-lg font-bold uppercase text-foreground flex items-center gap-2">
              <Trash2 className="w-5 h-5 text-rose-400" />
              确认删除 SSH 密钥？
            </AlertDialogTitle>
            <AlertDialogDescription className="text-muted-foreground">
              删除后将无法使用 SSH 方式访问 Git 仓库，需要重新生成密钥。此操作不可恢复。
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel className="cyber-btn-outline" disabled={deletingKey}>
              取消
            </AlertDialogCancel>
            <AlertDialogAction
              onClick={handleDeleteSSHKey}
              disabled={deletingKey}
              className="bg-rose-500/20 hover:bg-rose-500/30 text-rose-400 border border-rose-500/30"
            >
              {deletingKey ? (
                <>
                  <div className="loading-spinner w-4 h-4 mr-2" />
                  删除中...
                </>
              ) : (
                "确认删除"
              )}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  );
}

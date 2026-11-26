/**
 * Login Page
 * Cyberpunk Terminal Aesthetic
 */

import { useState, FormEvent, useEffect } from "react";
import { useNavigate, useLocation } from "react-router-dom";
import { useAuth } from "@/shared/context/AuthContext";
import { apiClient } from "@/shared/api/serverClient";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Checkbox } from "@/components/ui/checkbox";
import { toast } from "sonner";
import { Lock, Mail, Terminal, Shield, Fingerprint, Cpu } from "lucide-react";
import { version } from "../../package.json";

export default function Login() {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [rememberMe, setRememberMe] = useState(false);
  const [registrationEnabled, setRegistrationEnabled] = useState(false);
  const [loading, setLoading] = useState(false);
  const navigate = useNavigate();
  const location = useLocation();
  const { login, isAuthenticated } = useAuth();

  const from = location.state?.from?.pathname || "/";

  useEffect(() => {
    const controller = new AbortController();
    apiClient.get("/config/defaults", { signal: controller.signal })
      .then(({ data }) => setRegistrationEnabled(data.publicRegistrationEnabled !== false))
      .catch(() => {});
    const savedEmail = localStorage.getItem("remembered_email");
    if (savedEmail) {
      setEmail(savedEmail);
      setRememberMe(true);
    }
    return () => controller.abort();
  }, []);

  useEffect(() => {
    if (isAuthenticated && !loading) {
      navigate(from, { replace: true });
    }
  }, [isAuthenticated, navigate, from, loading]);

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    setLoading(true);
    try {
      const formData = new URLSearchParams();
      formData.append("username", email);
      formData.append("password", password);

      const response = await apiClient.post("/auth/login", formData, {
        headers: {
          "Content-Type": "application/x-www-form-urlencoded",
        },
      });

      if (rememberMe) {
        localStorage.setItem("remembered_email", email);
      } else {
        localStorage.removeItem("remembered_email");
      }

      await login(response.data.access_token, rememberMe);
      toast.success("登录成功");
    } catch (error: any) {
      const detail = error.response?.data?.detail;
      if (Array.isArray(detail)) {
        const messages = detail.map((err: any) => err.msg || err.message || JSON.stringify(err)).join('; ');
        toast.error(messages || "登录失败");
      } else if (typeof detail === 'object') {
        toast.error(detail.msg || detail.message || JSON.stringify(detail));
      } else {
        toast.error(detail || "登录失败，请检查邮箱和密码");
      }
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="min-h-screen flex items-center justify-center cyber-bg-elevated relative overflow-hidden">
      {/* Scanline overlay */}
      <div className="absolute inset-0 pointer-events-none z-20">
        <div
          className="absolute inset-0"
          style={{
            backgroundImage: "repeating-linear-gradient(0deg, transparent, transparent 2px, rgba(0,0,0,0.1) 2px, rgba(0,0,0,0.1) 4px)",
          }}
        />
      </div>

      {/* Vignette effect */}
      <div
        className="absolute inset-0 pointer-events-none z-10"
        style={{
          background: "radial-gradient(ellipse at center, transparent 0%, transparent 50%, rgba(0,0,0,0.5) 100%)",
        }}
      />

      {/* Grid background */}
      <div
        className="absolute inset-0 opacity-[0.03]"
        style={{
          backgroundImage: `
            linear-gradient(rgba(255,107,44,0.5) 1px, transparent 1px),
            linear-gradient(90deg, rgba(255,107,44,0.5) 1px, transparent 1px)
          `,
          backgroundSize: "32px 32px",
        }}
      />

      {/* Corner Decorations */}
      <div className="absolute top-4 left-4 text-sm font-mono text-muted-foreground z-30 space-y-1">
        <div className="flex items-center gap-2">
          <Terminal className="w-4 h-4" />
          <span>SYS_ID: 0x84F2</span>
        </div>
        <div className="flex items-center gap-2">
          <Shield className="w-4 h-4" />
          <span>ENCRYPT: AES-256</span>
        </div>
        <div className="flex items-center gap-2">
          <Fingerprint className="w-4 h-4" />
          <span>AUTH: READY</span>
        </div>
      </div>

      <div className="absolute top-4 right-4 text-sm font-mono text-muted-foreground text-right z-30 space-y-1">
        <div>SECURE_CONN: TRUE</div>
        <div>PORT: 443</div>
        <div>TLS: 1.3</div>
      </div>

      <div className="absolute bottom-4 left-4 text-sm font-mono text-muted-foreground z-30">
        DEEPAUDIT_AUTH_v3
      </div>

      <div className="absolute bottom-4 right-4 text-sm font-mono text-muted-foreground z-30">
        {new Date().toISOString().split("T")[0]}
      </div>

      {/* Main Card */}
      <div className="w-full max-w-md relative z-30 px-4">
        {/* Logo & Title */}
        <div className="text-center mb-8">
          <div className="inline-flex items-center justify-center p-3 cyber-dialog border border-border/60 rounded-lg mb-6"
               style={{ boxShadow: '0 0 30px rgba(255,107,44,0.1)' }}>
            <img
              src="/logo_deepaudit.png"
              alt="DeepAudit"
              className="w-14 h-14 object-contain"
            />
          </div>
          <div
            className="text-3xl font-bold tracking-wider mb-2 font-mono"
            style={{ textShadow: "0 0 30px rgba(255,107,44,0.5), 0 0 60px rgba(255,107,44,0.3)" }}
          >
            <span className="text-primary">DEEP</span>
            <span className="text-foreground">AUDIT</span>
          </div>
          <p className="text-base font-mono text-muted-foreground">
            // Autonomous Security Agent
          </p>
        </div>

        {/* Login Form Card */}
        <div className="cyber-dialog border border-border/60 rounded-lg overflow-hidden"
             style={{ boxShadow: '0 4px 30px rgba(0,0,0,0.5)' }}>
          {/* Card Header */}
          <div className="flex items-center gap-2 px-4 py-3 cyber-bg-elevated border-b border-border">
            <div className="flex items-center gap-1.5">
              <div className="w-3 h-3 rounded-full bg-red-500/80" />
              <div className="w-3 h-3 rounded-full bg-yellow-500/80" />
              <div className="w-3 h-3 rounded-full bg-green-500/80" />
            </div>
            <span className="ml-2 font-mono text-sm text-muted-foreground tracking-wider">
              authentication@deepaudit
            </span>
          </div>

          <div className="p-6">
            <form onSubmit={handleSubmit} className="flex flex-col gap-5">
              <div className="space-y-2">
                <Label
                  htmlFor="email"
                  className="font-mono text-sm text-muted-foreground uppercase tracking-wider"
                >
                  邮箱地址
                </Label>
                <div className="relative">
                  <Input
                    id="email"
                    type="email"
                    placeholder="your@email.com"
                    value={email}
                    onChange={(e) => setEmail(e.target.value)}
                    required
                    className="h-12 pl-11 font-mono cyber-bg-elevated border-border/50 text-foreground placeholder:text-muted-foreground focus:border-primary/50 focus:ring-0"
                  />
                  <Mail className="absolute left-4 top-1/2 -translate-y-1/2 w-4 h-4 text-muted-foreground" />
                </div>
              </div>

              <div className="space-y-2">
                <Label
                  htmlFor="password"
                  className="font-mono text-sm text-muted-foreground uppercase tracking-wider"
                >
                  密码
                </Label>
                <div className="relative">
                  <Input
                    id="password"
                    type="password"
                    placeholder="••••••••"
                    value={password}
                    onChange={(e) => setPassword(e.target.value)}
                    required
                    className="h-12 pl-11 font-mono cyber-bg-elevated border-border/50 text-foreground placeholder:text-muted-foreground focus:border-primary/50 focus:ring-0"
                  />
                  <Lock className="absolute left-4 top-1/2 -translate-y-1/2 w-4 h-4 text-muted-foreground" />
                </div>
              </div>

              <div className="flex items-center justify-between">
                <div className="flex items-center space-x-2">
                  <Checkbox
                    id="remember"
                    checked={rememberMe}
                    onCheckedChange={(checked) =>
                      setRememberMe(checked as boolean)
                    }
                    className="border-border data-[state=checked]:bg-primary data-[state=checked]:border-primary"
                  />
                  <Label
                    htmlFor="remember"
                    className="text-base font-mono text-muted-foreground cursor-pointer"
                  >
                    记住我
                  </Label>
                </div>
              </div>

              <Button
                type="submit"
                className="w-full h-12 text-base font-bold uppercase tracking-wider bg-primary hover:bg-primary/90 text-foreground border border-primary/50 transition-all"
                style={{ boxShadow: '0 0 20px rgba(255,107,44,0.3)' }}
                disabled={loading}
              >
                {loading ? (
                  <span className="flex items-center gap-2">
                    <span className="w-4 h-4 border-2 border-white/30 border-t-white rounded-full animate-spin" />
                    验证中...
                  </span>
                ) : (
                  "登 录"
                )}
              </Button>
            </form>

            {registrationEnabled && <div className="mt-6 pt-5 border-t border-border text-center">
              <p className="text-base font-mono text-muted-foreground">
                还没有账号？{" "}
                <span
                  className="text-primary font-bold cursor-pointer hover:underline"
                  onClick={() => navigate("/register")}
                >
                  立即注册
                </span>
              </p>
            </div>}
          </div>
        </div>

        {/* Version Info */}
        <div className="mt-6 text-center">
          <p className="font-mono text-sm text-muted-foreground uppercase">
            Version {version}
          </p>
        </div>
      </div>
    </div>
  );
}

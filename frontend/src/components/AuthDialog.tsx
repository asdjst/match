/** 登录 / 注册弹窗：一个账号一套餐食、血糖与问答历史。 */
import { useEffect, useRef, useState } from "react";
import { Banner, Button, Card, Stack, Text } from "@astryxdesign/core";
import { useAuth } from "../store/auth";

type Mode = "login" | "register";

export interface AuthDialogProps {
  open: boolean;
  initialMode?: Mode;
  onClose: () => void;
}

export function AuthDialog({ open, initialMode = "login", onClose }: AuthDialogProps) {
  const { login, register } = useAuth();
  const [mode, setMode] = useState<Mode>(initialMode);
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [reveal, setReveal] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const firstRef = useRef<HTMLInputElement | null>(null);

  useEffect(() => {
    if (!open) return;
    setMode(initialMode);
    setUsername("");
    setPassword("");
    setReveal(false);
    setError(null);
    const timer = setTimeout(() => firstRef.current?.focus(), 60);
    return () => clearTimeout(timer);
  }, [open, initialMode]);

  if (!open) return null;

  const submit = async () => {
    const name = username.trim();
    if (!name || !password) {
      setError("用户名和密码都要填");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      if (mode === "login") await login(name, password);
      else await register(name, password);
      onClose();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div
      className="meal-dialog-backdrop"
      role="presentation"
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <Card
        padding={5}
        className="meal-dialog auth-dialog"
        role="dialog"
        aria-modal="true"
        aria-label={mode === "login" ? "登录账号" : "注册账号"}
        onKeyDown={(e) => {
          if (e.key === "Escape") {
            e.preventDefault();
            onClose();
          }
        }}
      >
        <form
          onSubmit={(e) => {
            e.preventDefault();
            void submit();
          }}
        >
          <Stack gap={4}>
            <div className="meal-dialog-head">
              <div>
                <div className="food-title">{mode === "login" ? "登录账号" : "注册账号"}</div>
                <Text size="2xs" color="secondary">
                  餐食记录、血糖与问答历史按账号隔离，换人登录看不到彼此的记录。
                </Text>
              </div>
              <Button label="取消" variant="ghost" size="sm" onClick={onClose} />
            </div>

            <div className="auth-tabs" role="tablist" aria-label="登录或注册">
              {(["login", "register"] as Mode[]).map((key) => (
                <button
                  key={key}
                  type="button"
                  role="tab"
                  aria-selected={mode === key}
                  className={`auth-tab${mode === key ? " is-active" : ""}`}
                  onClick={() => {
                    setMode(key);
                    setError(null);
                  }}
                >
                  {key === "login" ? "登录" : "注册新账号"}
                </button>
              ))}
            </div>

            <label className="field">
              <span>用户名</span>
              <input
                ref={firstRef}
                className="field-input"
                autoComplete="username"
                placeholder={mode === "login" ? "你的用户名" : "3–24 位中英文、数字、_ 或 -"}
                value={username}
                onChange={(e) => setUsername(e.target.value)}
              />
            </label>

            <label className="field">
              <span>密码</span>
              <div className="auth-secret">
                <input
                  className="field-input"
                  type={reveal ? "text" : "password"}
                  autoComplete={mode === "login" ? "current-password" : "new-password"}
                  placeholder={mode === "login" ? "登录密码" : "至少 8 位，只存哈希不存明文"}
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                />
                <button
                  type="button"
                  className="auth-reveal"
                  aria-pressed={reveal}
                  onClick={() => setReveal((v) => !v)}
                >
                  {reveal ? "隐藏" : "显示"}
                </button>
              </div>
            </label>

            {error ? <Banner status="error" title={mode === "login" ? "登录失败" : "注册失败"} description={error} /> : null}

            <Stack direction="horizontal" gap={2} justify="end">
              <Button
                label={mode === "login" ? "登录" : "注册并登录"}
                variant="primary"
                type="submit"
                isLoading={busy}
                isDisabled={busy}
              />
            </Stack>

            <Text size="2xs" color="secondary">
              {mode === "login"
                ? "没有账号就切到「注册新账号」；不登录也能继续用单机演示记录。"
                : "注册后立刻登录，之前未登录时记的演示数据不会并进新账号。"}
            </Text>
          </Stack>
        </form>
      </Card>
    </div>
  );
}
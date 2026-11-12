/** 侧栏底部账号入口：一个图标，点开登录；登录后点开可退出。 */
import { useState } from "react";
import { Button, Card, Stack, Text } from "@astryxdesign/core";
import { AuthDialog } from "./AuthDialog";
import { useAuth } from "../store/auth";

const USER_ICON = (
  <svg viewBox="0 0 20 20" width="15" height="15" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" aria-hidden="true">
    <circle cx="10" cy="7" r="3" />
    <path d="M4.5 16.5c1.2-2.6 3.1-3.9 5.5-3.9s4.3 1.3 5.5 3.9" />
  </svg>
);

export function AccountEntry() {
  const { account, ready, notice, dismissNotice, logout } = useAuth();
  const [authOpen, setAuthOpen] = useState(false);
  const [sessionOpen, setSessionOpen] = useState(false);
  const [busy, setBusy] = useState(false);

  const open = () => {
    dismissNotice();
    if (account) setSessionOpen(true);
    else setAuthOpen(true);
  };

  const tip = !ready
    ? "正在核对登录状态"
    : notice
      ? "登录已过期，点此重新登录"
      : account
        ? `${account.username} · 点此退出`
        : "登录 / 注册";

  return (
    <div className="side-account">
      <Button
        label={tip}
        tooltip={tip}
        variant="ghost"
        size="sm"
        isIconOnly
        icon={USER_ICON}
        isDisabled={!ready}
        onClick={open}
      />
      {notice ? <span className="side-account-dot" aria-hidden="true" /> : null}

      <AuthDialog open={authOpen} onClose={() => setAuthOpen(false)} />

      {sessionOpen ? (
        <div
          className="meal-dialog-backdrop"
          role="presentation"
          onClick={(e) => {
            if (e.target === e.currentTarget) setSessionOpen(false);
          }}
        >
          <Card
            padding={4}
            className="meal-dialog account-dialog"
            role="dialog"
            aria-modal="true"
            aria-label="账号"
            onKeyDown={(e) => {
              if (e.key === "Escape") {
                e.preventDefault();
                setSessionOpen(false);
              }
            }}
          >
            <Stack gap={3}>
              <div className="meal-dialog-head">
                <div>
                  <div className="food-title">{account?.username ?? "已登录"}</div>
                  <Text size="2xs" color="secondary">
                    餐食记录、血糖与问答历史只属于这个账号。
                  </Text>
                </div>
                <Button label="关闭" variant="ghost" size="sm" onClick={() => setSessionOpen(false)} />
              </div>
              <Stack direction="horizontal" gap={2} justify="end">
                <Button
                  label="退出登录"
                  variant="secondary"
                  size="sm"
                  isLoading={busy}
                  isDisabled={busy}
                  onClick={() => {
                    setBusy(true);
                    void logout().finally(() => {
                      setBusy(false);
                      setSessionOpen(false);
                    });
                  }}
                />
              </Stack>
            </Stack>
          </Card>
        </div>
      ) : null}
    </div>
  );
}

/**
 * 账号状态：登录令牌存本机浏览器，身份由后端解析。
 * 未登录也能用（单机演示身份 local），登录后餐食、血糖与问答历史只属于这个账号。
 */
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import {
  currentAccount,
  loginAccount,
  logoutAccount,
  onUnauthorized,
  readToken,
  registerAccount,
  saveToken,
  type Account,
  type Session,
} from "../api/client";
import { useRuns } from "./runs";

interface AuthContextValue {
  account: Account | null;
  /** 首次身份校验完成前不显示账号入口，免得闪一下「未登录」 */
  ready: boolean;
  /** 会话过期等被动登出的提示，显示一次后清掉 */
  notice: string | null;
  dismissNotice: () => void;
  login: (username: string, password: string) => Promise<void>;
  register: (username: string, password: string) => Promise<void>;
  logout: () => Promise<void>;
}

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const { switchIdentity } = useRuns();
  const [account, setAccount] = useState<Account | null>(null);
  const [ready, setReady] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);

  // 本地留着令牌就先认下来，再向后端核对；失效则静默清掉
  useEffect(() => {
    if (!readToken()) {
      setReady(true);
      return;
    }
    let alive = true;
    void currentAccount()
      .then(({ user, expired }) => {
        if (!alive) return;
        if (user) setAccount(user);
        else if (expired) {
          saveToken("");
          setNotice("登录已过期，重新登录后就能继续用自己的记录");
        }
      })
      .catch(() => undefined)
      .finally(() => {
        if (alive) setReady(true);
      });
    return () => {
      alive = false;
    };
  }, []);

  // 个人接口回 401：清令牌并回到未登录态，同时清空上一个人的问答
  useEffect(
    () =>
      onUnauthorized(() => {
        if (!readToken()) return;
        saveToken("");
        setAccount(null);
        setNotice("登录已过期，重新登录后就能继续用自己的记录");
        void switchIdentity();
      }),
    [switchIdentity],
  );

  const adopt = useCallback(
    async (session: Session) => {
      saveToken(session.token);
      setAccount(session.user);
      setNotice(null);
      await switchIdentity();
    },
    [switchIdentity],
  );

  const login = useCallback(
    async (username: string, password: string) => {
      await adopt(await loginAccount(username, password));
    },
    [adopt],
  );

  const register = useCallback(
    async (username: string, password: string) => {
      await adopt(await registerAccount(username, password));
    },
    [adopt],
  );

  const logout = useCallback(async () => {
    await logoutAccount();
    saveToken("");
    setAccount(null);
    setNotice(null);
    await switchIdentity();
  }, [switchIdentity]);

  const value = useMemo<AuthContextValue>(
    () => ({
      account,
      ready,
      notice,
      dismissNotice: () => setNotice(null),
      login,
      register,
      logout,
    }),
    [account, ready, notice, login, register, logout],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth 必须在 AuthProvider 内使用");
  return ctx;
}
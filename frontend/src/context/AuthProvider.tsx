
import {
  useEffect,
  useState,
  type ReactNode,
} from "react";

import {
  ApiError,
  authApi,
  setCsrfToken,
} from "../services/api";

import {
  AuthContext,
  type AuthContextValue,
} from "./auth-context";

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<AuthContextValue["user"]>(null);
  const [loading, setLoading] = useState(true);
  const [authError, setAuthError] = useState<string | null>(null);

  useEffect(() => {
    let mounted = true;

    async function restoreSession() {
      try {
        const response = await authApi.me();

        if (!mounted) return;

        setUser(response.user);
        setCsrfToken(response.csrf_token);
      } catch (error) {
        if (!mounted) return;

        if (error instanceof ApiError && error.status === 401) {
          setUser(null);
          setCsrfToken(null);
        } else {
          setAuthError(
            error instanceof Error
              ? error.message
              : "Unable to restore your session.",
          );
        }
      } finally {
        if (mounted) {
          setLoading(false);
        }
      }
    }

    void restoreSession();

    return () => {
      mounted = false;
    };
  }, []);

  async function login(email: string, password: string) {
    setAuthError(null);

    const response = await authApi.login(email, password);

    setUser(response.user);
    setCsrfToken(response.csrf_token);
  }

  async function register(email: string, password: string) {
    setAuthError(null);

    const response = await authApi.register(email, password);

    setUser(response.user);
    setCsrfToken(response.csrf_token);
  }

  async function logout() {
    await authApi.logout();

    setUser(null);
    setCsrfToken(null);
    setAuthError(null);
  }

  return (
    <AuthContext.Provider
      value={{
        user,
        loading,
        authError,
        login,
        register,
        logout,
      }}
    >
      {children}
    </AuthContext.Provider>
  );
}

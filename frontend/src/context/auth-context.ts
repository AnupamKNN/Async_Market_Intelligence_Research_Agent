import { createContext } from "react";
import type { AuthUser } from "../services/api";

export interface AuthContextValue {
  user: AuthUser | null;
  loading: boolean;
  authError: string | null;
  login: (email: string, password: string) => Promise<void>;
  register: (email: string, password: string) => Promise<void>;
  logout: () => Promise<void>;
}

export const AuthContext = createContext<AuthContextValue | undefined>(
  undefined,
);
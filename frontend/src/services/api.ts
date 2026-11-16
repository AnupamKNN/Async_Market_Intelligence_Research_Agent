export const API_BASE_URL = (
  import.meta.env.VITE_API_BASE_URL ||
  "http://127.0.0.1:8000/api/v1"
).replace(/\/+$/, "");

let csrfToken: string | null = null;

export function setCsrfToken(token: string | null): void {
  csrfToken = token;
}

export class ApiError extends Error {
  readonly status: number;

  constructor(message: string, status: number) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

type ApiRequestOptions = Omit<RequestInit, "body"> & {
  body?: unknown;
};

function extractErrorMessage(data: unknown): string {
  if (data && typeof data === "object" && "detail" in data) {
    const detail = (data as { detail: unknown }).detail;

    if (typeof detail === "string") {
      return detail;
    }

    if (Array.isArray(detail)) {
      return detail
        .map((item) => {
          if (item && typeof item === "object" && "msg" in item) {
            return String(item.msg);
          }

          return String(item);
        })
        .join("; ");
    }
  }

  return "An unexpected API error occurred.";
}

export async function apiRequest<T>(
  path: string,
  options: ApiRequestOptions = {},
): Promise<T> {
  const { body, headers, ...requestOptions } = options;

  const method = requestOptions.method ?? "GET";
  const requestHeaders = new Headers(headers);

  if (body !== undefined) {
    requestHeaders.set("Content-Type", "application/json");
  }

  const safeMethods = ["GET", "HEAD", "OPTIONS"];

  if (!safeMethods.includes(method.toUpperCase()) && csrfToken) {
    requestHeaders.set("X-CSRF-Token", csrfToken);
  }

  const response = await fetch(`${API_BASE_URL}${path}`, {
    ...requestOptions,
    method,
    headers: requestHeaders,
    body: body === undefined ? undefined : JSON.stringify(body),
    credentials: "include",
  });

  const responseText = await response.text();

  let data: unknown = null;

  if (responseText) {
    try {
      data = JSON.parse(responseText);
    } catch {
      throw new ApiError("Invalid response from the server.", response.status);
    }
  }

  if (!response.ok) {
    throw new ApiError(
      extractErrorMessage(data),
      response.status,
    );
  }

  return data as T;
}

export interface AuthUser {
  id: string;
  email: string;
  display_name: string;
  email_verified: boolean;
  created_at: string;
}

export interface AuthResponse {
  user: AuthUser;
  csrf_token: string;
}

export const authApi = {
  me: () => apiRequest<AuthResponse>("/auth/me"),

  login: (email: string, password: string) =>
    apiRequest<AuthResponse>("/auth/login", {
      method: "POST",
      body: { email, password },
    }),

  register: (email: string, password: string) =>
    apiRequest<AuthResponse>("/auth/register", {
      method: "POST",
      body: { email, password },
    }),

  logout: () =>
    apiRequest<{ message: string }>("/auth/logout", {
      method: "POST",
    }),
};
const tg = () => (typeof window === "undefined" ? undefined : window.Telegram?.WebApp);

export function initData(): string {
  return tg()?.initData ?? "";
}

export function inTelegram(): boolean {
  return Boolean(initData());
}

/** GET a JSON endpoint with Telegram initData authentication. */
export async function apiGet<T>(path: string): Promise<T | null> {
  const data = initData();
  if (!data) return null;
  try {
    const response = await fetch(path, { headers: { "X-Init-Data": data } });
    if (!response.ok) return null;
    return (await response.json()) as T;
  } catch {
    return null;
  }
}

/** POST JSON with Telegram initData authentication. */
export async function apiPost<T>(path: string, body: unknown): Promise<T | null> {
  const data = initData();
  if (!data) return null;
  try {
    const response = await fetch(path, {
      method: "POST",
      headers: { "X-Init-Data": data, "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    if (!response.ok) return null;
    return (await response.json()) as T;
  } catch {
    return null;
  }
}

export type Me = {
  id: number;
  name: string;
  username: string;
  access: "admin" | "active" | "expired" | "none";
  remaining: string;
  admin: boolean;
};

export type Account = {
  label: string;
  status: string;
  owner: number | null;
  active: boolean;
};

export type HistoryItem = {
  ts: string;
  sources: string[];
  matched: number;
  valid: number;
};

export type Source = { id: number; title: string; kind: string };

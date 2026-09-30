/**
 * Single place where the backend base URL is resolved.
 *
 * `??` is deliberately avoided: a var declared but left blank in `.env` (as
 * `.env.example` used to ship it) reaches the bundle as `""`, which `??` happily
 * accepts and which then makes `new URL(path, "")` throw. Blank is treated as
 * "not configured" instead.
 */
export const DEFAULT_API_BASE_URL = "http://localhost:8000";

export function envOrDefault(value: string | undefined, fallback: string): string {
  const trimmed = value?.trim();
  return trimmed ? trimmed : fallback;
}

export function apiBaseUrl(): string {
  return envOrDefault(process.env.NEXT_PUBLIC_API_BASE_URL, DEFAULT_API_BASE_URL);
}

export type ApiQueryParams = Record<string, string | number | undefined>;

/** Builds an absolute backend URL, skipping any parameter that is `undefined`. */
export function apiUrl(path: string, params: ApiQueryParams = {}): URL {
  const url = new URL(path, apiBaseUrl());

  Object.entries(params).forEach(([key, value]) => {
    if (value !== undefined) {
      url.searchParams.set(key, String(value));
    }
  });

  return url;
}

/** Fetches JSON from the backend, turning any non-2xx into `errorMessage`. */
export async function fetchJson<T>(url: URL, errorMessage: string): Promise<T> {
  const response = await fetch(url.toString(), { cache: "no-store" });
  if (!response.ok) {
    throw new Error(errorMessage);
  }

  return (await response.json()) as T;
}

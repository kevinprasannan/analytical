/** Thin typed fetch wrapper. Base URL + optional bearer + RFC-7807 errors. */
import type { Problem } from "./generated/schema";

const BASE = (import.meta.env.VITE_API_BASE_URL ?? "").replace(/\/$/, "");
const TOKEN = import.meta.env.VITE_LOCAL_API_TOKEN as string | undefined;

export class ApiError extends Error {
  problem: Problem;
  status: number;
  constructor(problem: Problem) {
    super(problem.detail || problem.title);
    this.name = "ApiError";
    this.problem = problem;
    this.status = problem.status;
  }
}

export interface Query {
  [k: string]: string | number | boolean | null | undefined;
}

function url(path: string, query?: Query): string {
  const u = new URL(`${BASE}/api/v1${path}`, window.location.origin);
  if (query) {
    for (const [k, v] of Object.entries(query)) {
      if (v !== undefined && v !== null && v !== "") u.searchParams.set(k, String(v));
    }
  }
  return u.toString();
}

async function parse<T>(res: Response): Promise<T> {
  const text = await res.text();
  const body = text ? JSON.parse(text) : null;
  if (!res.ok) {
    const problem: Problem =
      body && typeof body === "object" && "title" in body
        ? (body as Problem)
        : { type: "about:blank", title: "Request failed", status: res.status, detail: text || res.statusText };
    throw new ApiError(problem);
  }
  return body as T;
}

function headers(json = false): HeadersInit {
  const h: Record<string, string> = { Accept: "application/json" };
  if (json) h["Content-Type"] = "application/json";
  if (TOKEN) h.Authorization = `Bearer ${TOKEN}`;
  return h;
}

export const api = {
  get: <T>(path: string, query?: Query) =>
    fetch(url(path, query), { headers: headers() }).then((r) => parse<T>(r)),
  patch: <T>(path: string, body: unknown) =>
    fetch(url(path), { method: "PATCH", headers: headers(true), body: JSON.stringify(body) }).then(
      (r) => parse<T>(r),
    ),
  post: <T>(path: string, body: unknown, extraHeaders?: Record<string, string>) =>
    fetch(url(path), {
      method: "POST",
      headers: { ...headers(true), ...extraHeaders },
      body: JSON.stringify(body),
    }).then((r) => parse<T>(r)),
  del: <T>(path: string, query?: Query) =>
    fetch(url(path, query), { method: "DELETE", headers: headers() }).then((r) => parse<T>(r)),
};

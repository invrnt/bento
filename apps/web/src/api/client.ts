export type ApiClientOptions = {
  baseUrl?: string;
  fetcher?: typeof fetch;
};

export type RequestOptions = Omit<RequestInit, "body"> & {
  body?: BodyInit | Record<string, unknown>;
  query?: QueryParams;
};

export type QueryParams = Record<string, boolean | number | string | null | undefined>;

export class ApiError extends Error {
  readonly details: unknown;
  readonly status: number;

  constructor(message: string, status: number, details: unknown) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.details = details;
  }
}

export function resolveApiBaseUrl(explicitBaseUrl?: string): string {
  const configuredBaseUrl = explicitBaseUrl ?? import.meta.env.VITE_API_BASE_URL ?? "/api";
  const normalizedBaseUrl = configuredBaseUrl.trim() || "/api";

  return normalizedBaseUrl.replace(/\/+$/, "");
}

export function createApiClient(options: ApiClientOptions = {}) {
  const baseUrl = resolveApiBaseUrl(options.baseUrl);
  const fetcher = options.fetcher ?? fetch;

  async function request<TResponse>(path: string, requestOptions: RequestOptions = {}): Promise<TResponse> {
    const { body, headers, query, ...init } = requestOptions;
    const normalizedPath = path.startsWith("/") ? path : `/${path}`;
    const resolvedPath = appendQuery(normalizedPath, query);
    const requestHeaders = new Headers(headers);
    let requestBody: BodyInit | undefined;

    if (body === undefined) {
      requestBody = undefined;
    } else if (isBodyInit(body)) {
      requestBody = body;
    } else {
      requestHeaders.set("content-type", "application/json");
      requestBody = JSON.stringify(body);
    }

    const response = await fetcher(`${baseUrl}${resolvedPath}`, {
      ...init,
      body: requestBody,
      headers: requestHeaders,
    });

    if (!response.ok) {
      const details = await readResponseBody(response);
      throw new ApiError(response.statusText || "API request failed", response.status, details);
    }

    if (response.status === 204) {
      return undefined as TResponse;
    }

    return (await readResponseBody(response)) as TResponse;
  }

  return {
    baseUrl,
    request,
  };
}

export const apiClient = createApiClient();

export type ApiClient = ReturnType<typeof createApiClient>;

function isBodyInit(body: BodyInit | Record<string, unknown>): body is BodyInit {
  return (
    typeof body === "string" ||
    body instanceof Blob ||
    body instanceof FormData ||
    body instanceof URLSearchParams ||
    body instanceof ArrayBuffer ||
    ArrayBuffer.isView(body) ||
    body instanceof ReadableStream
  );
}

async function readResponseBody(response: Response): Promise<unknown> {
  const contentType = response.headers.get("content-type") ?? "";

  if (contentType.includes("application/json")) {
    return response.json();
  }

  return response.text();
}

function appendQuery(path: string, query?: QueryParams): string {
  if (!query) {
    return path;
  }

  const search = new URLSearchParams();

  for (const [key, value] of Object.entries(query)) {
    if (value === null || value === undefined || value === "") {
      continue;
    }

    search.set(key, String(value));
  }

  const serialized = search.toString();

  return serialized ? `${path}?${serialized}` : path;
}

/** Resolves API-relative asset URLs (`/api/...`) against the configured API origin. */
export function absoluteApiPath(path: string, client: Pick<ApiClient, "baseUrl"> = apiClient): string {
  if (/^https?:\/\//.test(path)) {
    return path;
  }
  if (path.startsWith("/api/") && client.baseUrl.endsWith("/api")) {
    return `${client.baseUrl.slice(0, -4)}${path}`;
  }
  return `${client.baseUrl}${path}`;
}

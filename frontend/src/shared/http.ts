export interface ApiErrorDetails {
  message: string;
  [field: string]: unknown;
}

const firstHttpServerError = 500;

export class ApiError extends Error {
  /** Сохраняет статус HTTP и полученные от сервера сведения об ошибке. */
  constructor(
    readonly status: number,
    readonly detail: ApiErrorDetails | null,
  ) {
    super(detail?.message ?? "Приложение временно недоступно.");
  }

  /** Определяет, относится ли статус ответа к серверным ошибкам HTTP. */
  get isServerError(): boolean {
    return this.status >= firstHttpServerError;
  }
}

/** Проверяет, есть ли в ответе текст ошибки для оператора. */
function hasErrorMessage(detail: unknown): detail is ApiErrorDetails {
  return typeof detail === "object" && detail !== null &&
    "message" in detail && typeof detail.message === "string";
}

/** Выполняет запрос к API приложения с cookie и защитным заголовком. */
export async function request(path: string, options: RequestInit = {}): Promise<Response> {
  const headers = new Headers(options.headers);
  if (options.method && options.method !== "GET") {
    headers.set("X-Requested-With", "KeitaroWrapper");
  }
  if (options.body !== undefined) {
    headers.set("Content-Type", "application/json");
  }

  const response = await fetch(`/api${path}`, { ...options, headers, credentials: "same-origin" });
  if (!response.ok) {
    const payload: unknown = await response.json().catch(() => null);
    const detail = typeof payload === "object" && payload !== null && "detail" in payload
      ? payload.detail : null;
    throw new ApiError(
      response.status,
      typeof detail === "string" ? { message: detail } :
        hasErrorMessage(detail) ? detail : null,
    );
  }
  return response;
}

/** Читает обязательное тело успешного ответа в формате JSON. */
export async function requestJson<T>(path: string, options: RequestInit = {}): Promise<T> {
  const response = await request(path, options);
  return await response.json() as T;
}

/** Возвращает сообщение, которое можно показать оператору. */
export function errorMessage(error: unknown, fallback: string): string {
  return error instanceof ApiError ? error.message : fallback;
}

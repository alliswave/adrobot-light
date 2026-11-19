import { request, requestJson } from "../../shared/http";

export interface Operator {
  username: string;
}

const noContentStatus = 204;

export const authApi = {
  /** Проверяет текущий сеанс браузера. */
  session(): Promise<Operator> {
    return requestJson("/session");
  },
  /** Начинает сеанс с указанными учётными данными. */
  signIn(username: string, password: string): Promise<Operator> {
    return requestJson("/session", { method: "POST", body: JSON.stringify({ username, password }) });
  },
  /** Завершает сеанс. Если сервер прислал тело ответа, проверяет его формат JSON. */
  async signOut(): Promise<void> {
    const response = await request("/session", { method: "DELETE" });
    if (response.status !== noContentStatus) await response.json();
  },
};

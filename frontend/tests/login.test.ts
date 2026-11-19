import { flushPromises, mount } from "@vue/test-utils";
import { expect, test, vi } from "vitest";
import LoginForm from "../src/features/auth/LoginForm.vue";

/** Проверяет, что браузер не ограничивает длину логина и пароля в единицах UTF-16. */
test("передаёт логин и пароль с дополнительными символами Юникода целиком", async () => {
  const username = "🦉".repeat(100);
  const password = "🦉".repeat(1024);
  const fetch = vi.fn((_url: string, _options?: RequestInit) =>
    Promise.resolve(new Response(JSON.stringify({ username }))),
  );
  vi.stubGlobal("fetch", fetch);
  const form = mount(LoginForm);
  const usernameInput = form.get("#username");
  const passwordInput = form.get("#password");
  expect(usernameInput.attributes("maxlength")).toBeUndefined();
  expect(passwordInput.attributes("maxlength")).toBeUndefined();
  await usernameInput.setValue(username);
  await passwordInput.setValue(password);
  await form.get("form").trigger("submit");
  await flushPromises();
  expect(fetch).toHaveBeenCalledWith("/api/session", expect.objectContaining({
    body: JSON.stringify({ username, password }),
  }));
  expect(form.emitted("signedIn")).toEqual([[{ username }]]);
});

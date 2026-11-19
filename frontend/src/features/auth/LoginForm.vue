<script setup lang="ts">
import { ref } from "vue";
import { errorMessage } from "../../shared/http";
import { authApi, type Operator } from "./api";

const emit = defineEmits<{ signedIn: [Operator] }>();
const username = ref("");
const password = ref("");
const pending = ref(false);
const failure = ref("");

/** Проверяет учётные данные и передаёт текущего оператора приложению. */
async function submit(): Promise<void> {
  if (pending.value) return;
  pending.value = true;
  failure.value = "";
  try {
    emit("signedIn", await authApi.signIn(username.value, password.value));
  } catch (error) {
    failure.value = errorMessage(error, "Не удалось войти. Повторите попытку.");
  } finally {
    pending.value = false;
    password.value = "";
  }
}
</script>

<template>
  <main class="login-layout">
    <section class="card login-card">
      <div class="brand">
        <span class="brand-mark" aria-hidden="true">A</span>
        <strong>Adrobot Light</strong>
      </div>
      <h1>Вход в приложение</h1>
      <form @submit.prevent="submit">
        <fieldset :disabled="pending">
          <div class="field">
            <label for="username">Логин</label>
            <input id="username" v-model="username" autocomplete="username" required />
          </div>
          <div class="field">
            <label for="password">Пароль</label>
            <input
              id="password"
              v-model="password"
              autocomplete="current-password"
              required
              type="password"
            />
          </div>
        </fieldset>
        <button class="primary-button icon-text" type="submit" :disabled="pending">
          <span v-if="pending" class="spinner" aria-hidden="true"></span>
          {{ pending ? "Входим…" : "Войти" }}
        </button>
        <p v-if="failure" class="notice notice-error" role="alert">{{ failure }}</p>
      </form>
    </section>
  </main>
</template>

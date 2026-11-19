<script setup lang="ts">
import { onMounted, ref } from "vue";
import { authApi, type Operator } from "./features/auth/api";
import { ApiError, errorMessage } from "./shared/http";
import CampaignForm from "./features/campaign-creation/CampaignForm.vue";
import StreamEditor from "./features/stream-editor/StreamEditor.vue";
import LoginForm from "./features/auth/LoginForm.vue";

const loading = ref(true);
const operator = ref<Operator | null>(null);
const sessionError = ref("");
const signingOut = ref(false);
const page = ref<"create" | "edit">("create");
const editorOpened = ref(false);

onMounted(async () => {
  try {
    operator.value = await authApi.session();
  } catch (error) {
    if (!(error instanceof ApiError && error.status === 401)) {
      sessionError.value = "Не удалось проверить сеанс. Можно попробовать войти снова.";
    }
  } finally {
    loading.value = false;
  }
});

/** Показывает рабочую область после успешного входа. */
function signedIn(user: Operator): void {
  operator.value = user;
  sessionError.value = "";
}

/** Открывает редактор и сохраняет его состояние при переходе к созданию. */
function openEditor(): void {
  editorOpened.value = true;
  page.value = "edit";
}

/** Закрывает сеанс и возвращает оператора к форме входа. */
async function signOut(): Promise<void> {
  if (signingOut.value) return;
  signingOut.value = true;
  sessionError.value = "";
  try {
    await authApi.signOut();
    operator.value = null;
    editorOpened.value = false;
    page.value = "create";
  } catch (error) {
    sessionError.value = errorMessage(error, "Не удалось выйти. Повторите попытку.");
  } finally {
    signingOut.value = false;
  }
}
</script>

<template>
  <p v-if="loading" class="startup-status icon-text" role="status">
    <span class="spinner" aria-hidden="true"></span>
    Проверяем сеанс…
  </p>
  <template v-else-if="!operator">
    <p v-if="sessionError" class="startup-status" role="alert">{{ sessionError }}</p>
    <LoginForm @signed-in="signedIn" />
  </template>
  <div v-else class="app-layout">
    <header class="app-header">
      <div class="brand">
        <span class="brand-mark" aria-hidden="true">A</span>
        <strong>Adrobot Light</strong>
      </div>
      <div class="operator">
        <span>{{ operator.username }}</span>
        <button class="secondary-button icon-text" type="button" :disabled="signingOut" @click="signOut">
          <span v-if="signingOut" class="spinner" aria-hidden="true"></span>
          {{ signingOut ? "Выходим…" : "Выйти" }}
        </button>
      </div>
    </header>
    <main>
      <p v-if="sessionError" class="notice notice-error" role="alert">{{ sessionError }}</p>
      <nav class="workspace-nav" aria-label="Управление кампаниями">
        <button type="button" :aria-pressed="page === 'create'" @click="page = 'create'">
          Создание кампании
        </button>
        <button type="button" :aria-pressed="page === 'edit'" @click="openEditor">
          Редактор офферов
        </button>
      </nav>
      <CampaignForm v-show="page === 'create'" />
      <StreamEditor v-if="editorOpened" v-show="page === 'edit'" />
    </main>
  </div>
</template>

<style scoped>
.workspace-nav {
  max-width: 70rem;
  margin: 0 auto;
  padding: 1.4rem 1rem 0;
  display: flex;
  flex-wrap: wrap;
  gap: 0.55rem;
}
.workspace-nav button {
  border: 1px solid var(--border);
  border-radius: 0.45rem;
  color: var(--ink);
  background: white;
  padding: 0.45rem 0.75rem;
}
.workspace-nav button[aria-pressed="true"] {
  color: var(--accent);
  background: #e9f3f0;
  border-color: #8ab6a9;
  font-weight: 650;
}
</style>

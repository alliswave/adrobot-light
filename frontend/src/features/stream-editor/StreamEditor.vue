<script setup lang="ts">
import { computed, onMounted, ref, watch } from "vue";
import { errorMessage } from "../../shared/http";
import type { OfferOption } from "../../shared/offers/api";
import OfferPicker from "../../shared/offers/OfferPicker.vue";
import type { NamedTrackerEntry } from "../../shared/trackerCatalog";
import { editorApi, type CampaignStream } from "./api";
import OfferTable from "./OfferTable.vue";
import { useStreamEditor } from "./useStreamEditor";

const campaigns = ref<NamedTrackerEntry[]>([]);
const campaignChoice = ref<number | null>(null);
const selectedOffer = ref<OfferOption | null>(null);
const loadingCatalog = ref(false);
const catalogError = ref("");
const {
  streams, loadedCampaignId, stream, draft, unavailableIds, changed,
  pending, loadingStreams, publishing, failure, notice,
  loadCampaign, selectStream, cancel, publish, addOffer, removeOffer, togglePin,
} = useStreamEditor();

const showStreams = computed(() =>
  loadedCampaignId.value !== null && loadedCampaignId.value === campaignChoice.value,
);
const campaignAvailable = computed(() =>
  campaigns.value.some(({ id }) => id === campaignChoice.value),
);
const draftCampaignAvailable = computed(() =>
  showStreams.value && campaignAvailable.value && !loadingCatalog.value,
);
const streamKinds: Record<CampaignStream["kind"], string> = {
  offers: "Поток с офферами",
  redirect: "Перенаправление",
  other: "Поток без редактора офферов",
};

onMounted(loadCatalog);
watch([campaignChoice, () => stream.value?.id], () => { selectedOffer.value = null; });

/** Загружает список кампаний для выбора. */
async function loadCatalog(): Promise<void> {
  if (loadingCatalog.value || loadingStreams.value || publishing.value) return;
  loadingCatalog.value = true;
  catalogError.value = "";
  try {
    campaigns.value = await editorApi.listCampaigns();
  } catch (error) {
    catalogError.value = errorMessage(error, "Не удалось загрузить список кампаний.");
  } finally {
    loadingCatalog.value = false;
  }
}

/** Загружает потоки выбранной кампании. */
async function loadSelectedCampaign(): Promise<void> {
  if (campaignChoice.value === null || !campaignAvailable.value || loadingCatalog.value) return;
  selectedOffer.value = null;
  await loadCampaign(campaignChoice.value);
}

/** Публикует черновик открытой кампании, если она доступна в свежем списке. */
async function publishChanges(): Promise<void> {
  if (!draftCampaignAvailable.value) return;
  await publish();
}

/** Добавляет выбранный оффер и очищает поле поиска. */
function addSelectedOffer(): void {
  if (!selectedOffer.value) return;
  addOffer(selectedOffer.value);
  selectedOffer.value = null;
}

/** Возвращает опубликованные строки и очищает выбранный оффер в форме. */
function cancelChanges(): void {
  cancel();
  selectedOffer.value = null;
}
</script>

<template>
  <section class="workspace" aria-labelledby="editor-heading">
    <header class="page-heading">
      <h1 id="editor-heading">Редактор офферов</h1>
    </header>

    <form class="card campaign-picker" @submit.prevent="loadSelectedCampaign">
      <div>
        <label for="editor-campaign">Кампания</label>
        <select
          id="editor-campaign"
          v-model="campaignChoice"
          :disabled="loadingCatalog || loadingStreams || publishing"
        >
          <option :value="null" disabled>Выберите кампанию</option>
          <option v-if="campaignChoice !== null && !campaignAvailable" :value="campaignChoice" disabled>
            Кампания #{{ campaignChoice }} больше недоступна
          </option>
          <option v-for="campaign in campaigns" :key="campaign.id" :value="campaign.id">
            {{ campaign.name }} (#{{ campaign.id }})
          </option>
        </select>
      </div>
      <button
        class="primary-button icon-text"
        type="submit"
        :disabled="!campaignAvailable || loadingCatalog || loadingStreams || publishing"
      >
        <span v-if="loadingStreams" class="spinner" aria-hidden="true"></span>
        {{ loadingStreams ? "Загружаем…" : "Загрузить" }}
      </button>
      <p v-if="loadingCatalog" class="field-help picker-message icon-text" role="status">
        <span class="spinner" aria-hidden="true"></span>
        Загружаем кампании…
      </p>
      <p v-else-if="catalogError" class="notice notice-error picker-message" role="alert">{{ catalogError }}</p>
      <p v-else-if="!campaigns.length" class="field-help picker-message" role="status">
        В Keitaro нет доступных кампаний.
      </p>
      <button
        type="button"
        class="text-button catalog-refresh icon-text"
        :disabled="loadingCatalog || loadingStreams || publishing"
        @click="loadCatalog"
      >
        <span class="refresh-icon" aria-hidden="true">↻</span>
        Обновить список кампаний
      </button>
    </form>

    <p v-if="failure" class="notice notice-error" role="alert">{{ failure }}</p>
    <p v-if="notice" class="notice notice-success" role="status">{{ notice }}</p>
    <template v-if="showStreams">
      <p v-if="!streams.length" class="notice" role="status">В кампании нет потоков.</p>
      <div v-else class="editor-layout">
        <aside class="card" aria-labelledby="stream-list-heading">
          <h2 id="stream-list-heading">Потоки кампании</h2>
          <ul class="stream-list">
            <li v-for="item in streams" :key="item.id">
              <button
                type="button"
                :aria-current="item.id === stream?.id ? 'true' : undefined"
                :disabled="loadingStreams || publishing"
                @click="item.id !== stream?.id && selectStream(item.id)"
              >
                {{ item.name }}
                <small>{{ streamKinds[item.kind] }}</small>
              </button>
            </li>
          </ul>
        </aside>

        <section v-if="stream" class="card stream-detail" aria-labelledby="stream-detail-heading">
          <div class="detail-header">
            <div>
              <h2 id="stream-detail-heading">{{ stream.name }}</h2>
              <p class="field-help">{{ streamKinds[stream.kind] }}</p>
            </div>
            <p v-if="pending" class="draft-status icon-text" role="status">
              <span class="spinner" aria-hidden="true"></span>
              Рассчитываем доли…
            </p>
            <p v-else-if="changed" class="draft-status" role="status">Неопубликованные изменения</p>
          </div>
          <template v-if="stream.kind === 'offers'">
            <OfferTable
              :rows="draft.rows"
              :pins="draft.pins"
              :locked="loadingStreams || publishing"
              :pending="pending !== null"
              @remove="removeOffer"
              @restore="addOffer"
              @toggle-pin="togglePin"
            />

            <div class="editor-add">
              <OfferPicker
                :key="stream.id"
                v-model="selectedOffer"
                input-id="editor-offer"
                :disabled="loadingStreams || publishing"
                :unavailable-ids="unavailableIds"
              />
              <button
                type="button"
                class="outline-button"
                :disabled="!selectedOffer || unavailableIds.includes(selectedOffer.id) || loadingStreams || publishing"
                @click="addSelectedOffer"
              >
                Добавить
              </button>
            </div>

            <div class="editor-actions">
              <button
                type="button"
                class="outline-button"
                :disabled="(!changed && pending === null) || loadingStreams || publishing"
                @click="cancelChanges"
              >
                Отменить
              </button>
              <button
                type="button"
                class="primary-button icon-text"
                :disabled="!draftCampaignAvailable || !changed || pending !== null || loadingStreams || publishing"
                @click="publishChanges"
              >
                <span v-if="publishing" class="spinner" aria-hidden="true"></span>
                {{ publishing ? "Публикуем…" : "Опубликовать" }}
              </button>
            </div>
          </template>
        </section>
      </div>
    </template>
  </section>
</template>

<style scoped>
.campaign-picker {
  display: grid;
  grid-template-columns: 1fr auto;
  align-items: end;
  gap: 0.65rem;
}
.picker-message { grid-column: 1 / -1; }
.catalog-refresh { grid-column: 1 / -1; justify-self: start; }
.editor-layout {
  display: grid;
  grid-template-columns: minmax(13rem, 1fr) minmax(0, 3fr);
  align-items: start;
  gap: 1rem;
  margin-top: 1rem;
}
.stream-list { list-style: none; margin: 0.8rem 0 0; padding: 0; }
.stream-list li + li { margin-top: 0.35rem; }
.stream-list button {
  width: 100%;
  padding: 0.55rem 0.7rem;
  border-radius: 0.45rem;
  border: 1px solid var(--border);
  text-align: left;
  overflow-wrap: anywhere;
  color: var(--ink);
  background: white;
}
.stream-list button[aria-current="true"] { background: #e9f3f0; border-color: #8ab6a9; }
.stream-list small { display: block; color: var(--muted); }
.detail-header { display: flex; justify-content: space-between; gap: 0.75rem; flex-wrap: wrap; }
.draft-status { font-size: 0.88rem; color: #875410; }
.outline-button {
  background: white;
  color: var(--ink);
  border: 1px solid var(--border);
  border-radius: 0.45rem;
  padding: 0.35rem 0.65rem;
}
.editor-add { display: grid; grid-template-columns: 1fr auto; align-items: start; gap: 0.7rem; }
.editor-add > button { margin-top: 1.75rem; min-height: 2.75rem; }
.editor-actions { display: flex; flex-wrap: wrap; gap: 0.6rem; margin-top: 1rem; }
@media (max-width: 650px) {
  .editor-layout { grid-template-columns: minmax(0, 1fr); }
  .campaign-picker, .editor-add { grid-template-columns: minmax(0, 1fr); }
  .editor-add > button { margin-top: 0; }
}
</style>

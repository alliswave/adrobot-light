<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { errorMessage } from "../../shared/http";
import type { OfferOption } from "../../shared/offers/api";
import OfferPicker from "../../shared/offers/OfferPicker.vue";
import type { NamedTrackerEntry } from "../../shared/trackerCatalog";
import {
  CampaignCreationError,
  createCampaign,
  listCampaignOptions,
  type CampaignInput,
  type CampaignOptions,
  type CreatedCampaign,
} from "./api";
import { countries } from "./countries";

const name = ref("");
const country = ref("");
const offer = ref<OfferOption | null>(null);

interface CatalogSelection {
  id: number | "";
  needsChoice: boolean;
}

const groupSelection = ref<CatalogSelection>({ id: "", needsChoice: false });
const sourceSelection = ref<CatalogSelection>({ id: "", needsChoice: false });
const options = ref<CampaignOptions | null>(null);
const loadingOptions = ref(false);
const optionsError = ref("");
const refreshRequired = ref(false);
const pending = ref(false);
const failure = ref("");
const created = ref<CreatedCampaign | null>(null);

const emptyOptions = computed(() => options.value !== null &&
  (!options.value.groups.length || !options.value.traffic_sources.length));
const campaignInput = computed<CampaignInput | null>(() => {
  const title = name.value.trim();
  const groupId = groupSelection.value.id;
  const sourceId = sourceSelection.value.id;
  if (!title || !country.value || !offer.value || groupId === "" ||
      sourceId === "" || !options.value || loadingOptions.value ||
      optionsError.value || emptyOptions.value || refreshRequired.value) return null;
  return {
    name: title,
    country: country.value,
    offer_id: offer.value.id,
    group_id: groupId,
    traffic_source_id: sourceId,
  };
});

onMounted(refreshOptions);

/** Сохраняет выбор или требует выбрать заново, если прежний вариант исчез. */
function reconcileSelection(selection: CatalogSelection, entries: NamedTrackerEntry[]): CatalogSelection {
  if (selection.id !== "") {
    return entries.some(({ id }) => id === selection.id) ? selection : { id: "", needsChoice: true };
  }
  if (!selection.needsChoice && entries.length === 1) {
    return { id: entries[0].id, needsChoice: false };
  }
  return selection;
}

/** Перечитывает оба справочника и сверяет выбранные значения с новым списком. */
async function refreshOptions(): Promise<void> {
  if (loadingOptions.value || pending.value) return;
  loadingOptions.value = true;
  optionsError.value = "";
  try {
    const fresh = await listCampaignOptions();
    groupSelection.value = reconcileSelection(groupSelection.value, fresh.groups);
    sourceSelection.value = reconcileSelection(sourceSelection.value, fresh.traffic_sources);
    options.value = fresh;
    refreshRequired.value = false;
  } catch (error) {
    optionsError.value = errorMessage(error, "Не удалось загрузить справочники.");
  } finally {
    loadingOptions.value = false;
  }
}

/** Отправляет выбранные данные, пока форма не выполняет другую запись. */
async function submit(): Promise<void> {
  const input = campaignInput.value;
  if (pending.value || !input) return;
  pending.value = true;
  failure.value = "";
  created.value = null;

  try {
    created.value = await createCampaign(input);
  } catch (error) {
    const campaignError = error instanceof CampaignCreationError ? error : null;
    const campaignId = campaignError?.campaignId;
    failure.value = campaignError?.message ?? "Не удалось создать кампанию.";
    if (campaignId != null) failure.value += ` ID кампании: ${campaignId}.`;
    refreshRequired.value = campaignError?.refreshOptions === true;
  } finally {
    pending.value = false;
  }
}
</script>

<template>
  <section class="workspace" aria-labelledby="create-heading">
    <header class="page-heading">
      <h1 id="create-heading">Создание кампании</h1>
      <p>Выберите страну для перенаправления на Google и оффер для остальных посетителей.</p>
    </header>

    <div class="campaign-layout">
      <form class="card form-card" @submit.prevent="submit">
        <fieldset :disabled="pending">
          <div class="field">
            <label for="campaign-name">Название кампании</label>
            <input
              id="campaign-name"
              v-model="name"
              required
              placeholder="Например, Весенняя кампания"
            />
          </div>

          <div class="field">
            <label for="campaign-country">Страна для перенаправления</label>
            <select id="campaign-country" v-model="country" required>
              <option value="" disabled>Выберите страну</option>
              <option v-for="option in countries" :key="option.code" :value="option.code">
                {{ option.name }} ({{ option.code }})
              </option>
            </select>
          </div>

          <div class="field">
            <label for="campaign-group">Группа кампаний</label>
            <select
              id="campaign-group"
              v-model="groupSelection.id"
              :disabled="loadingOptions || !!optionsError || !options?.groups.length"
              required
              @change="groupSelection.needsChoice = false"
            >
              <option value="" disabled>Выберите группу</option>
              <option v-for="group in options?.groups" :key="group.id" :value="group.id">
                {{ group.name }}
              </option>
            </select>
            <p v-if="groupSelection.needsChoice" class="field-help" role="status">
              Выбранная группа больше недоступна.
            </p>
          </div>

          <div class="field">
            <label for="campaign-source">Источник трафика</label>
            <select
              id="campaign-source"
              v-model="sourceSelection.id"
              :disabled="loadingOptions || !!optionsError || !options?.traffic_sources.length"
              required
              @change="sourceSelection.needsChoice = false"
            >
              <option value="" disabled>Выберите источник</option>
              <option v-for="source in options?.traffic_sources" :key="source.id" :value="source.id">
                {{ source.name }}
              </option>
            </select>
            <p v-if="sourceSelection.needsChoice" class="field-help" role="status">
              Выбранный источник трафика больше недоступен.
            </p>
          </div>

          <button
            type="button"
            class="text-button icon-text"
            :disabled="loadingOptions"
            @click="refreshOptions"
          >
            <span class="refresh-icon" aria-hidden="true">↻</span>
            Обновить справочники
          </button>
          <p v-if="loadingOptions" class="field-help icon-text" role="status">
            <span class="spinner" aria-hidden="true"></span>
            Загружаем справочники…
          </p>
          <p v-else-if="optionsError" class="notice notice-error" role="alert">{{ optionsError }}</p>
          <p v-else-if="emptyOptions" class="notice" role="status">
            {{ !options?.groups.length ? "В Keitaro нет доступных групп кампаний." : "" }}
            {{ !options?.traffic_sources.length ? "В Keitaro нет доступных источников трафика." : "" }}
          </p>

          <OfferPicker v-model="offer" input-id="campaign-offer" />
        </fieldset>

        <div class="form-actions">
          <button class="primary-button icon-text" type="submit" :disabled="pending || !campaignInput">
            <span v-if="pending" class="spinner" aria-hidden="true"></span>
            {{ pending ? "Создаём кампанию…" : "Создать кампанию" }}
          </button>
        </div>

        <p v-if="failure" class="notice notice-error" role="alert">
          {{ failure }}
          <template v-if="refreshRequired">Обновите справочники и проверьте выбранные значения.</template>
        </p>
        <p v-if="created" class="notice notice-success" role="status">
          Кампания «{{ created.name }}» создана. ID: {{ created.id }}.
        </p>
      </form>

      <aside class="card flow-preview" aria-labelledby="flow-heading">
        <h2 id="flow-heading">Маршрут посетителей</h2>
        <dl>
          <div>
            <dt>{{ countries.find(({ code }) => code === country)?.name ?? "Выбранная страна" }}</dt>
            <dd><span aria-hidden="true">→</span> Google</dd>
          </div>
          <div>
            <dt>Остальные страны</dt>
            <dd><span aria-hidden="true">→</span> {{ offer?.name ?? "Выбранный оффер" }}</dd>
          </div>
        </dl>
      </aside>
    </div>
  </section>
</template>

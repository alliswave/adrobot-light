<script setup lang="ts">
import { ref, watch } from "vue";
import { errorMessage } from "../http";
import { searchOffers, type OfferOption } from "./api";

defineProps<{ inputId: string; disabled?: boolean; unavailableIds?: readonly number[] }>();

const selected = defineModel<OfferOption | null>({ required: true });
const query = ref("");
const offers = ref<OfferOption[]>([]);
const loading = ref(false);
const searchError = ref("");

watch(query, async (value, _previous, onCleanup) => {
  const controller = new AbortController();
  onCleanup(() => controller.abort());
  offers.value = [];
  searchError.value = "";
  const search = value.trim();
  loading.value = Boolean(search);
  if (!search) return;

  try {
    const matches = await searchOffers(search, controller.signal);
    if (!controller.signal.aborted) offers.value = matches;
  } catch (error) {
    if (!controller.signal.aborted) {
      searchError.value = errorMessage(error, "Не удалось выполнить поиск офферов.");
    }
  } finally {
    if (!controller.signal.aborted) loading.value = false;
  }
});

/** Запоминает оффер и закрывает список подсказок. */
function chooseOffer(offer: OfferOption): void {
  selected.value = offer;
  query.value = "";
}
</script>

<template>
  <div class="offer-picker">
    <label :for="inputId">Оффер</label>
    <div v-if="selected" class="selected-offer">
      <span>{{ selected.name }} <small>#{{ selected.id }}</small></span>
      <button
        :id="inputId"
        :disabled="disabled"
        class="text-button"
        type="button"
        @click="selected = null"
      >
        Изменить
      </button>
    </div>
    <template v-else>
      <input
        :id="inputId"
        v-model="query"
        :disabled="disabled"
        type="search"
        placeholder="Название или ID"
        autocomplete="off"
      />
      <p v-if="loading" class="field-help icon-text" role="status">
        <span class="spinner" aria-hidden="true"></span>
        Ищем офферы…
      </p>
      <p v-else-if="searchError" class="field-help" role="alert">{{ searchError }}</p>
      <p v-else-if="query.trim() && !offers.length" class="field-help" role="status">
        Офферы не найдены.
      </p>
      <ul v-else-if="offers.length" class="offer-options" aria-label="Найденные офферы">
        <li v-for="offer in offers" :key="offer.id">
          <button
            type="button"
            :disabled="disabled || unavailableIds?.includes(offer.id)"
            @click="chooseOffer(offer)"
          >
            <span>{{ offer.name }}</span>
            <small>
              #{{ offer.id }}<template v-if="unavailableIds?.includes(offer.id)"> · Уже в потоке</template>
            </small>
          </button>
        </li>
      </ul>
    </template>
  </div>
</template>

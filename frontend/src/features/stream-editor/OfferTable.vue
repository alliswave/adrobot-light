<script setup lang="ts">
import type { OfferOption } from "../../shared/offers/api";
import type { DraftRow } from "./useStreamEditor";

defineProps<{
  rows: DraftRow[];
  pins: Record<number, number>;
  locked: boolean;
  pending: boolean;
}>();
defineEmits<{
  restore: [offer: OfferOption];
  remove: [offerId: number];
  togglePin: [offerId: number];
}>();
</script>

<template>
  <div class="stream-table" :aria-busy="pending">
    <table v-if="rows.length">
      <thead>
        <tr><th scope="col">Оффер</th><th scope="col">Доля</th><th scope="col">Действия</th></tr>
      </thead>
      <tbody>
        <tr
          v-for="offer in rows"
          :id="`stream-offer-${offer.id}`"
          :key="offer.id"
          :class="{ 'inactive-offer': offer.state !== 'active' }"
        >
          <th scope="row">
            {{ offer.name }} <small>#{{ offer.id }}</small>
            <small v-if="offer.state === 'archived'" class="offer-status">Удалён</small>
            <small v-else-if="offer.state === 'disabled'" class="offer-status">Отключён</small>
          </th>
          <td>{{ offer.share === null ? "…" : `${offer.share}%` }}</td>
          <td>
            <div v-if="offer.state === 'active'" class="row-actions">
              <button
                type="button"
                class="pin-button"
                :aria-pressed="offer.id in pins"
                :aria-label="`Закрепить долю оффера #${offer.id}`"
                :title="offer.id in pins ? 'Снять закрепление' : 'Закрепить долю'"
                :disabled="pending || locked || offer.share === null || offer.share < 0"
                @click="$emit('togglePin', offer.id)"
              >
                <span aria-hidden="true">📌</span>
              </button>
              <button
                type="button"
                class="text-button"
                :disabled="locked"
                @click="$emit('remove', offer.id)"
              >
                Удалить
              </button>
            </div>
            <button
              v-else-if="offer.state === 'archived'"
              type="button"
              class="text-button"
              :disabled="locked"
              @click="$emit('restore', offer)"
            >
              Восстановить
            </button>
          </td>
        </tr>
      </tbody>
    </table>
    <p v-else class="field-help">В потоке пока нет офферов.</p>
  </div>
</template>

<style scoped>
.stream-table { margin: 1rem 0; overflow-x: auto; }
table { width: 100%; border-collapse: collapse; text-align: left; }
thead { color: var(--muted); font-size: 0.87rem; }
th, td { padding: 0.45rem 0.5rem; border-bottom: 1px solid var(--border); }
tbody th { font-weight: 600; overflow-wrap: anywhere; }
th small { font-weight: 400; white-space: nowrap; }
.offer-status { display: block; color: var(--muted); }
.inactive-offer { color: var(--muted); background: #f1f3f6; }
.row-actions { display: flex; align-items: center; gap: 0.4rem; }
.pin-button {
  background: white;
  color: var(--ink);
  border: 1px solid var(--border);
  border-radius: 0.45rem;
  padding: 0.35rem 0.65rem;
}
.pin-button[aria-pressed="false"] span { filter: grayscale(1); }
.pin-button[aria-pressed="true"] { background: #dcefe8; border-color: #8ab6a9; }
</style>

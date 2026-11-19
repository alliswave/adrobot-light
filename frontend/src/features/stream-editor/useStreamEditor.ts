import { computed, onScopeDispose, ref, shallowRef } from "vue";
import { errorMessage } from "../../shared/http";
import type { OfferOption } from "../../shared/offers/api";
import {
  editorApi,
  type CampaignStream,
  type OfferDraftRequest,
  type StreamOffer,
} from "./api";

export type DraftRow = Omit<StreamOffer, "share"> & { share: number | null };

interface Draft {
  rows: DraftRow[];
  pins: Record<number, number>;
}

/** Оставляет в запросе действующие офферы в порядке добавления. */
function toRequest(draft: Draft): OfferDraftRequest {
  return {
    offer_ids: draft.rows.filter(({ state }) => state === "active").map(({ id }) => id),
    pinned_shares: draft.pins,
  };
}

/** Хранит опубликованный состав, черновик и закрепления открытого потока. */
export function useStreamEditor() {
  const streams = ref<CampaignStream[]>([]);
  const loadedCampaignId = ref<number | null>(null);
  const selectedStreamId = ref<number | null>(null);
  const stream = computed(() => streams.value.find(({ id }) => id === selectedStreamId.value));
  const accepted = shallowRef<Draft>({ rows: [], pins: {} });
  const pending = shallowRef<Draft | null>(null);
  const draft = computed(() => pending.value ?? accepted.value);
  const unavailableIds = computed(() => draft.value.rows
    .filter(({ state }) => state !== "archived")
    .map(({ id }) => id));
  const previewedRequest = shallowRef<OfferDraftRequest | null>(null);
  const changed = computed(() => previewedRequest.value !== null);
  const loadingStreams = ref(false);
  const publishing = ref(false);
  const failure = ref("");
  const notice = ref("");
  let previewVersion = 0;

  /** Делает все отправленные запросы предпросмотра неактуальными. */
  function invalidatePreview(): void {
    previewVersion += 1;
    pending.value = null;
  }

  onScopeDispose(invalidatePreview);

  /** Выбирает поток и восстанавливает его опубликованный состав. */
  function selectStream(streamId: number | null): void {
    if (publishing.value) return;
    selectedStreamId.value = streamId;
    cancel();
  }

  /** Загружает потоки кампании и выбирает первый поток с офферами. */
  async function loadCampaign(campaignId: number): Promise<void> {
    if (loadingStreams.value || publishing.value) return;
    invalidatePreview();
    loadingStreams.value = true;
    failure.value = "";
    notice.value = "";
    try {
      streams.value = await editorApi.loadStreams(campaignId);
      loadedCampaignId.value = campaignId;
      const initial = streams.value.find(({ kind }) => kind === "offers") ?? streams.value[0];
      selectStream(initial?.id ?? null);
    } catch (error) {
      failure.value = errorMessage(error, "Не удалось загрузить потоки кампании.");
    } finally {
      loadingStreams.value = false;
    }
  }

  /** Возвращает исходные строки и доли, отменяя ожидаемый предпросмотр. */
  function cancel(): void {
    if (publishing.value) return;
    invalidatePreview();
    accepted.value = { rows: stream.value?.offers ?? [], pins: {} };
    previewedRequest.value = null;
    failure.value = "";
    notice.value = "";
  }

  /** Показывает новый состав сразу и применяет доли только к актуальной правке. */
  async function preview(candidate: Draft): Promise<void> {
    const version = ++previewVersion;
    pending.value = candidate;
    failure.value = "";
    notice.value = "";
    try {
      const request = toRequest(candidate);
      const shares = await editorApi.previewShares(request);
      if (version !== previewVersion) return;
      const rows = candidate.rows.map((row) => {
        if (row.state !== "active") return row;
        const share = shares[row.id];
        if (share === undefined || !Number.isInteger(share)) {
          throw new Error("Предпросмотр не содержит долю действующего оффера.");
        }
        return { ...row, share };
      });
      accepted.value = { rows, pins: candidate.pins };
      previewedRequest.value = request;
    } catch (error) {
      if (version === previewVersion) {
        failure.value = errorMessage(error, "Не удалось рассчитать доли черновика.");
      }
    } finally {
      if (version === previewVersion) pending.value = null;
    }
  }

  /** Добавляет каталоговый или архивный оффер в конец действующих привязок. */
  function addOffer(offer: OfferOption): void {
    if (publishing.value || stream.value?.kind !== "offers") return;
    if (unavailableIds.value.includes(offer.id)) return;
    const rows = draft.value.rows.filter(({ id }) => id !== offer.id);
    rows.push({ id: offer.id, name: offer.name, share: null, state: "active" });
    void preview({ rows, pins: draft.value.pins });
  }

  /** Переносит действующий оффер в архив черновика и освобождает его долю. */
  function removeOffer(offerId: number): void {
    if (publishing.value || stream.value?.kind !== "offers") return;
    const active = draft.value.rows.filter(({ state }) => state === "active");
    if (!active.some(({ id }) => id === offerId)) return;
    if (active.length === 1) {
      failure.value = "В потоке должен остаться хотя бы один действующий оффер.";
      return;
    }
    const pins = { ...draft.value.pins };
    delete pins[offerId];
    const rows = draft.value.rows.map((row): DraftRow => row.id === offerId
      ? { ...row, share: 0, state: "archived" }
      : row);
    void preview({ rows, pins });
  }

  /** Закрепляет показанную долю в памяти вкладки без пересчёта и записи. */
  function togglePin(offerId: number): void {
    if (pending.value || publishing.value) return;
    const row = accepted.value.rows.find(({ id }) => id === offerId);
    if (!row || row.state !== "active" || row.share === null || row.share < 0) return;
    const pins = { ...accepted.value.pins };
    if (offerId in pins) delete pins[offerId];
    else pins[offerId] = row.share;
    accepted.value = { ...accepted.value, pins };
  }

  /** Публикует проверенный состав и использует ответ как новую исходную версию. */
  async function publish(): Promise<void> {
    const campaignId = loadedCampaignId.value;
    const streamId = selectedStreamId.value;
    const request = previewedRequest.value;
    if (campaignId === null || streamId === null || request === null ||
        pending.value || publishing.value || loadingStreams.value) return;
    publishing.value = true;
    failure.value = "";
    notice.value = "";
    try {
      // Переключение закрепления после предпросмотра влияет на следующую правку состава.
      const published = await editorApi.publishOffers(campaignId, streamId, request);
      streams.value = streams.value.map((item) => item.id === streamId ? published : item);
      accepted.value = { rows: published.offers, pins: accepted.value.pins };
      previewedRequest.value = null;
      notice.value = "Доли опубликованы.";
    } catch (error) {
      failure.value = error instanceof Error ? error.message : "Не удалось опубликовать доли.";
    } finally {
      publishing.value = false;
    }
  }

  return {
    streams, loadedCampaignId, stream, draft, unavailableIds, changed,
    pending, loadingStreams, publishing, failure, notice,
    loadCampaign, selectStream, cancel, publish, addOffer, removeOffer, togglePin,
  };
}

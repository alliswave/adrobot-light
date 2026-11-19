import { ApiError, requestJson } from "../../shared/http";
import type { OfferOption } from "../../shared/offers/api";
import { isNamedTrackerEntry, isTrackerId, type NamedTrackerEntry } from "../../shared/trackerCatalog";

export interface StreamOffer extends OfferOption {
  share: number;
  state: "active" | "disabled" | "archived";
}

export interface CampaignStream {
  id: number;
  name: string;
  kind: "offers" | "redirect" | "other";
  offers: StreamOffer[];
}

export interface OfferDraftRequest {
  offer_ids: number[];
  pinned_shares: Record<number, number>;
}

const unconfirmedPublish = "Не удалось подтвердить публикацию. Сверьте результат с Keitaro.";

/** Проверяет обязательные поля строки в подтверждении публикации. */
function isStreamOffer(value: unknown): value is StreamOffer {
  return typeof value === "object" && value !== null &&
    "id" in value && isTrackerId(value.id) && "name" in value && typeof value.name === "string" &&
    "share" in value && typeof value.share === "number" && Number.isInteger(value.share) &&
    "state" in value &&
    (value.state === "active" || value.state === "disabled" || value.state === "archived");
}

/** Проверяет, что ответ содержит строки опубликованного потока. */
function isPublishedStream(value: unknown, streamId: number): value is CampaignStream {
  return typeof value === "object" && value !== null &&
    "id" in value && value.id === streamId &&
    "name" in value && typeof value.name === "string" &&
    "kind" in value && value.kind === "offers" &&
    "offers" in value && Array.isArray(value.offers) && value.offers.every(isStreamOffer) &&
    value.offers.some(({ state }) => state === "active");
}

export const editorApi = {
  /** Загружает кампании, доступные для редактирования. */
  async listCampaigns(): Promise<NamedTrackerEntry[]> {
    const reply = await requestJson<unknown>("/campaigns", { cache: "no-store" });
    if (Array.isArray(reply) && reply.every(isNamedTrackerEntry)) return reply;
    throw new Error("В ответе сервера нет списка кампаний.");
  },
  /** Загружает потоки с опубликованными долями и архивом офферов. */
  loadStreams(campaignId: number): Promise<CampaignStream[]> {
    return requestJson(`/campaigns/${campaignId}/streams`);
  },
  /** Рассчитывает доли без изменения привязок. */
  previewShares(draft: OfferDraftRequest): Promise<Record<number, number>> {
    return requestJson("/offer-shares/preview", {
      method: "POST",
      body: JSON.stringify(draft),
    });
  },
  /** Записывает состав потока и учитывает потерю подтверждения даже вне API. */
  async publishOffers(
    campaignId: number, streamId: number, draft: OfferDraftRequest,
  ): Promise<CampaignStream> {
    try {
      const response = await requestJson<unknown>(`/campaigns/${campaignId}/streams/${streamId}/offers`, {
        method: "PUT",
        body: JSON.stringify(draft),
      });
      if (isPublishedStream(response, streamId)) return response;
    } catch (error) {
      if (error instanceof ApiError &&
          (!error.isServerError || typeof error.detail?.outcome_unknown === "boolean")) {
        throw error;
      }
    }
    throw new Error(unconfirmedPublish);
  },
};

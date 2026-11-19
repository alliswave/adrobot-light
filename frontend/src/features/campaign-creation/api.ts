import { ApiError, requestJson, type ApiErrorDetails } from "../../shared/http";
import { isNamedTrackerEntry, isTrackerId, type NamedTrackerEntry } from "../../shared/trackerCatalog";

export interface CampaignInput {
  name: string;
  country: string;
  offer_id: number;
  group_id: number;
  traffic_source_id: number;
}

export interface CampaignOptions {
  groups: NamedTrackerEntry[];
  traffic_sources: NamedTrackerEntry[];
}

export interface CreatedCampaign {
  id: number;
  name: string;
}

interface CampaignFailure extends ApiErrorDetails {
  step: string;
  outcome_unknown: boolean;
  campaign_id?: number | null;
  refresh_options?: boolean;
}

export class CampaignCreationError extends Error {
  /** Сохраняет известный ID кампании и необходимость обновить справочники. */
  constructor(
    message: string,
    readonly campaignId: number | null = null,
    readonly refreshOptions = false,
  ) {
    super(message);
  }
}

const campaignSteps = ["campaign", "redirect", "offer_stream", "enable"];
const unconfirmedCampaign =
  "Не удалось подтвердить создание кампании. Проверьте результат в Keitaro перед повтором.";

/** Распознаёт подтверждённое сервером сообщение о сбое на конкретном шаге. */
function isCampaignFailure(detail: ApiErrorDetails | null): detail is CampaignFailure {
  return detail !== null && detail.message.trim().length > 0 &&
    typeof detail.step === "string" && campaignSteps.includes(detail.step) &&
    typeof detail.outcome_unknown === "boolean" &&
    (detail.campaign_id == null || isTrackerId(detail.campaign_id)) &&
    (detail.refresh_options === undefined || typeof detail.refresh_options === "boolean");
}

/** Запрашивает актуальные группы кампаний и источники трафика. */
export async function listCampaignOptions(): Promise<CampaignOptions> {
  const reply = await requestJson<unknown>("/campaign-options", { cache: "no-store" });
  if (typeof reply === "object" && reply !== null &&
      "groups" in reply && Array.isArray(reply.groups) && reply.groups.every(isNamedTrackerEntry) &&
      "traffic_sources" in reply && Array.isArray(reply.traffic_sources) &&
      reply.traffic_sources.every(isNamedTrackerEntry)) {
    return { groups: reply.groups, traffic_sources: reply.traffic_sources };
  }
  throw new Error("В ответе сервера нет справочников кампании.");
}

/** Создаёт кампанию с выбранными группой, источником, страной и оффером. */
export async function createCampaign(campaign: CampaignInput): Promise<CreatedCampaign> {
  try {
    const reply = await requestJson<unknown>("/campaigns", {
      method: "POST",
      body: JSON.stringify(campaign),
    });
    if (isNamedTrackerEntry(reply)) return reply;
  } catch (error) {
    if (error instanceof ApiError) {
      if (isCampaignFailure(error.detail)) {
        throw new CampaignCreationError(
          error.message,
          error.detail.campaign_id ?? null,
          error.detail.refresh_options,
        );
      }
      if (!error.isServerError) throw new CampaignCreationError(error.message);
    }
  }
  throw new CampaignCreationError(unconfirmedCampaign);
}

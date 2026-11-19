import { requestJson } from "../http";

export interface OfferOption {
  id: number;
  name: string;
}

/** Ищет офферы по названию или идентификатору. */
export function searchOffers(query: string, signal?: AbortSignal): Promise<OfferOption[]> {
  return requestJson(`/offers?${new URLSearchParams({ q: query })}`, { signal });
}

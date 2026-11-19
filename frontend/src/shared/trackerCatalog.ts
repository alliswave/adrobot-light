export interface NamedTrackerEntry {
  id: number;
  name: string;
}

/** Проверяет, что идентификатор Keitaro можно точно представить в браузере. */
export function isTrackerId(value: unknown): value is number {
  return typeof value === "number" && Number.isSafeInteger(value) && value > 0;
}

/** Проверяет идентификатор и название записи из Keitaro. */
export function isNamedTrackerEntry(value: unknown): value is NamedTrackerEntry {
  return typeof value === "object" && value !== null &&
    "id" in value && isTrackerId(value.id) &&
    "name" in value && typeof value.name === "string" && value.name.trim().length > 0;
}

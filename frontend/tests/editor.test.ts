import { enableAutoUnmount, flushPromises, mount, type VueWrapper } from "@vue/test-utils";
import { afterEach, expect, test, vi } from "vitest";
import App from "../src/App.vue";
import type { CampaignStream, OfferDraftRequest, StreamOffer } from "../src/features/stream-editor/api";

const streamsPath = "/api/campaigns/42/streams";
const previewPath = "/api/offer-shares/preview";
const publishPath = streamsPath + "/89/offers";
const names: Record<number, string> = {
  3717: "Первый", 3749: "Второй", 11111: "Третий", 11112: "Четвёртый", 11113: "Пятый",
};

enableAutoUnmount(afterEach);
afterEach(() => vi.unstubAllGlobals());

/** Возвращает ответ FastAPI с указанным телом. */
function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

/** Задаёт имя и фактическую долю строки потока. */
function offer(id: number, share: number, state: StreamOffer["state"] = "active"): StreamOffer {
  return { id, share, state, name: names[id] };
}

/** Формирует состояние редактируемого потока в API. */
function stream(offers: StreamOffer[]): CampaignStream {
  return { id: 89, name: "Остальные страны", kind: "offers", offers };
}

/** Возвращает ответ, момент доставки которого определяет проверка. */
function deferredResponse() {
  let resolve!: (response: Response) => void;
  const promise = new Promise<Response>((finish) => { resolve = finish; });
  return { promise, resolve };
}

/** Находит кнопку по подписи, которую видит оператор. */
function button(form: VueWrapper, label: string) {
  const found = form.findAll<HTMLButtonElement>("button").find((item) => item.text() === label);
  if (!found) throw new Error(`Не найдена кнопка «${label}»`);
  return found;
}

/** Проверяет выбор кампании и загрузку потоков из рабочей области приложения. */
async function openEditor(
  offers: StreamOffer[],
  replies: {
    catalog?: () => Response | Promise<Response>;
    preview?: (request: OfferDraftRequest) => Response | Promise<Response>;
    publish?: (request: OfferDraftRequest) => Response | Promise<Response>;
  } = {},
) {
  const fetch = vi.fn(async (url: string, options?: RequestInit) => {
    if (url === "/api/session") return json({ username: "operator" });
    if (url === "/api/campaign-options") return json({ groups: [], traffic_sources: [] });
    if (url === "/api/campaigns" && replies.catalog) return replies.catalog();
    if (url === "/api/campaigns") return json([{ id: 42, name: "Внешняя кампания" }]);
    if (url === streamsPath) return json([
      { id: 88, name: "AU → Google", kind: "redirect", offers: [] },
      stream(offers),
    ]);
    if (url.startsWith("/api/offers?q=")) {
      const id = Number(url.split("=")[1]);
      return json([{ id, name: names[id] }]);
    }
    if (url === previewPath || url === publishPath) {
      expect(new Headers(options?.headers).get("X-Requested-With")).toBe("KeitaroWrapper");
      const draft: OfferDraftRequest = JSON.parse(String(options?.body));
      if (url === previewPath && replies.preview) return replies.preview(draft);
      if (url === publishPath && replies.publish) return replies.publish(draft);
    }
    throw new Error(`Неожиданный маршрут ${url}`);
  });
  vi.stubGlobal("fetch", fetch);
  const form = mount(App);
  await flushPromises();
  await button(form, "Редактор офферов").trigger("click");
  await flushPromises();
  await form.get("#editor-campaign").setValue("42");
  await button(form, "Загрузить").trigger("submit");
  await flushPromises();
  return { form, fetch };
}

/** Выбирает результат поиска и меняет состав потока через форму. */
async function add(form: VueWrapper, offerId: number): Promise<void> {
  await form.get("#editor-offer").setValue(String(offerId));
  await flushPromises();
  await form.get(".offer-options button").trigger("click");
  await button(form, "Добавить").trigger("click");
}

/** Возвращает долю в видимой строке таблицы. */
function share(form: VueWrapper, offerId: number): string {
  return form.get(`#stream-offer-${offerId} td:first-of-type`).text();
}

/** При обновлении списка кампаний сохраняет открытый поток, его доли и черновик. */
test("сохраняет черновик и ждёт появления кампании в списке перед публикацией", async () => {
  const delayed = deferredResponse();
  const catalog = vi.fn()
    .mockReturnValueOnce(json([{ id: 42, name: "Внешняя кампания" }]))
    .mockReturnValueOnce(delayed.promise)
    .mockReturnValueOnce(json([{ id: 42, name: "Внешняя кампания" }]));
  const { form, fetch } = await openEditor([offer(3717, 100)], {
    catalog,
    preview: () => json({ 3717: 50, 3749: 50 }),
    publish: () => json(stream([offer(3717, 50), offer(3749, 50)])),
  });
  await add(form, 3749);
  await flushPromises();
  expect(share(form, 3749)).toBe("50%");
  const refresh = form.get<HTMLButtonElement>(".catalog-refresh");
  expect(refresh.text()).toContain("Обновить список кампаний");
  expect(refresh.get(".refresh-icon").attributes("aria-hidden")).toBe("true");

  await refresh.trigger("click");
  expect(refresh.element.disabled).toBe(true);
  expect(form.findAll('[role="status"]').some((status) => status.text() === "Загружаем кампании…"))
    .toBe(true);
  await refresh.trigger("click");
  expect(catalog).toHaveBeenCalledTimes(2);
  delayed.resolve(json([{ id: 43, name: "Новая кампания" }]));
  await flushPromises();

  expect(form.get("#editor-campaign").text()).toContain("Новая кампания");
  expect(form.get("#editor-campaign").text()).toContain("Кампания #42 больше недоступна");
  expect(share(form, 3749)).toBe("50%");
  expect(form.get(".draft-status").text()).toBe("Неопубликованные изменения");
  const publish = button(form, "Опубликовать");
  expect(publish.element.disabled).toBe(true);
  publish.element.dispatchEvent(new MouseEvent("click", { bubbles: true }));
  await flushPromises();
  expect(fetch.mock.calls.filter(([path]) => path === publishPath)).toHaveLength(0);

  await refresh.trigger("click");
  await flushPromises();
  expect(form.get("#editor-campaign").text()).not.toContain("больше недоступна");
  expect(share(form, 3749)).toBe("50%");
  expect(publish.element.disabled).toBe(false);
  await publish.trigger("click");
  await flushPromises();
  expect(form.get(".notice-success").text()).toBe("Доли опубликованы.");
  expect(fetch.mock.calls.filter(([path]) => path === streamsPath)).toHaveLength(1);
  expect(fetch.mock.calls.filter(([path, options]) => path === publishPath && options?.method === "PUT"))
    .toHaveLength(1);
});

/** Показывает ошибку ответа и сохраняет предыдущую выдачу и открытый черновик. */
test.each([null, [{ id: 42, name: null }]])("сохраняет список при некорректном ответе (%j)", async (bad) => {
  const catalog = vi.fn()
    .mockReturnValueOnce(json([{ id: 42, name: "Внешняя кампания" }]))
    .mockReturnValueOnce(json(bad));
  const { form, fetch } = await openEditor([offer(3717, 100)], {
    catalog,
    preview: () => json({ 3717: 50, 3749: 50 }),
  });
  await add(form, 3749);
  await flushPromises();
  await form.get(".catalog-refresh").trigger("click");
  await flushPromises();

  expect(form.get('[role="alert"]').text()).toBe("Не удалось загрузить список кампаний.");
  expect(form.get("#editor-campaign").text()).toContain("Внешняя кампания");
  expect(share(form, 3749)).toBe("50%");
  expect(form.get(".draft-status").text()).toBe("Неопубликованные изменения");
  expect(button(form, "Опубликовать").element.disabled).toBe(false);
  expect(fetch.mock.calls.filter(([path]) => path === streamsPath)).toHaveLength(1);
});

/** Проверяет отмену пятой привязки, пока сервер рассчитывает её доли. */
test("отмена убирает временный оффер и игнорирует ожидаемый ответ", async () => {
  const delayed = deferredResponse();
  const initial = [3717, 3749, 11111, 11112].map((id) => offer(id, 25));
  const { form, fetch } = await openEditor(initial, { preview: () => delayed.promise });
  expect(form.get(".stream-list").text()).toContain("AU → Google Перенаправление");
  await add(form, 11113);
  expect(form.get("#stream-offer-11113").text()).toContain("Пятый");
  expect(button(form, "Опубликовать").element.disabled).toBe(true);
  await button(form, "Отменить").trigger("click");
  delayed.resolve(json({ 3717: 20, 3749: 20, 11111: 20, 11112: 20, 11113: 20 }));
  await flushPromises();

  expect(form.find("#stream-offer-11113").exists()).toBe(false);
  for (const { id } of initial) expect(share(form, id)).toBe("25%");
  expect(form.find(".draft-status").exists()).toBe(false);
  expect(fetch.mock.calls.filter(([url]) => url === publishPath)).toHaveLength(0);
});

/** Проверяет мгновенный архив, восстановление и приоритет последней правки. */
test("поздний ответ удаления не меняет восстановленный оффер", async () => {
  const removed = deferredResponse();
  const restored = deferredResponse();
  const initial = [3717, 3749, 11111, 11112].map((id) => offer(id, 25));
  const { form, fetch } = await openEditor(initial, {
    preview: ({ offer_ids }) => offer_ids.length === 3 ? removed.promise : restored.promise,
  });
  const row = form.get("#stream-offer-3717");
  await row.get("button.text-button").trigger("click");
  expect(row.classes()).toContain("inactive-offer");
  expect(row.text()).toContain("Удалён");
  expect(share(form, 3717)).toBe("0%");
  expect(row.get("button.text-button").text()).toBe("Восстановить");
  await row.get("button.text-button").trigger("click");
  expect(row.text()).not.toContain("Удалён");
  expect(form.findAll("tbody tr").at(-1)?.attributes("id")).toBe("stream-offer-3717");

  restored.resolve(json({ 3749: 25, 11111: 25, 11112: 25, 3717: 25 }));
  await flushPromises();
  removed.resolve(json({ 3749: 33, 11111: 33, 11112: 34 }));
  await flushPromises();

  expect(share(form, 11112)).toBe("25%");
  expect(share(form, 3717)).toBe("25%");
  expect(form.findAll("#stream-offer-3717")).toHaveLength(1);
  const bodies = fetch.mock.calls.filter(([url]) => url === previewPath)
    .map(([, options]) => JSON.parse(String(options?.body)));
  expect(bodies).toEqual([
    { offer_ids: [3749, 11111, 11112], pinned_shares: {} },
    { offer_ids: [3749, 11111, 11112, 3717], pinned_shares: {} },
  ]);
});

/** Проверяет, что удаление освобождает закреплённую долю до восстановления. */
test("восстанавливает ранее закреплённый оффер без закрепления", async () => {
  const requests: OfferDraftRequest[] = [];
  const initial = [3717, 3749, 11111, 11112].map((id) => offer(id, 25));
  const { form } = await openEditor(initial, {
    preview: (draft) => {
      requests.push(draft);
      return draft.offer_ids.length === 3
        ? json({ 3749: 33, 11111: 33, 11112: 34 })
        : json({ 3749: 25, 11111: 25, 11112: 25, 3717: 25 });
    },
  });
  const row = form.get("#stream-offer-3717");
  await row.get("button[aria-pressed]").trigger("click");
  await row.get("button.text-button").trigger("click");
  await flushPromises();
  expect(share(form, 3717)).toBe("0%");
  expect(share(form, 3749)).toBe("33%");
  expect(share(form, 11111)).toBe("33%");
  expect(share(form, 11112)).toBe("34%");
  await row.get("button.text-button").trigger("click");
  await flushPromises();

  expect(row.get("button[aria-pressed]").attributes("aria-pressed")).toBe("false");
  expect(share(form, 3717)).toBe("25%");
  expect(requests).toEqual([
    { offer_ids: [3749, 11111, 11112], pinned_shares: {} },
    { offer_ids: [3749, 11111, 11112, 3717], pinned_shares: {} },
  ]);
});

/** Проверяет, что при переходе к другому потоку старый ответ не восстанавливает черновик. */
test("смена потока делает ожидаемый предпросмотр неактуальным", async () => {
  const delayed = deferredResponse();
  const { form } = await openEditor([offer(3717, 50), offer(11112, 50)], {
    preview: () => delayed.promise,
  });
  await form.get("#stream-offer-3717 button.text-button").trigger("click");
  await button(form, "AU → Google Перенаправление").trigger("click");
  expect(form.get("#stream-detail-heading").text()).toBe("AU → Google");
  expect(form.find(".stream-table").exists()).toBe(false);
  delayed.resolve(json({ 11112: 100 }));
  await flushPromises();
  expect(form.get("#stream-detail-heading").text()).toBe("AU → Google");
  expect(form.find(".stream-table").exists()).toBe(false);
  expect(form.find(".draft-status").exists()).toBe(false);
  await button(form, "Остальные страны Поток с офферами").trigger("click");
  expect(share(form, 3717)).toBe("50%");
  expect(share(form, 11112)).toBe("50%");
  expect(form.find(".draft-status").exists()).toBe(false);
});

/** Проверяет закрепление фактических 0% при добавлении и публикации оффера. */
test("закрепляет 0% у действующего оффера и сохраняет долю при публикации", async () => {
  const actualDraft = { offer_ids: [3717, 3749, 11112], pinned_shares: { 3717: 0 } };
  const preview = vi.fn(() => json({ 3717: 0, 3749: 50, 11112: 50 }));
  const publish = vi.fn(() => json(stream([offer(3717, 0), offer(3749, 50), offer(11112, 50)])));
  const { form } = await openEditor([offer(3717, 0), offer(3749, 100)], { preview, publish });
  const pin = form.get<HTMLButtonElement>("#stream-offer-3717 button[aria-pressed]");
  expect(share(form, 3717)).toBe("0%");
  expect(pin.element.disabled).toBe(false);
  await pin.trigger("click");
  expect(pin.attributes("aria-pressed")).toBe("true");
  expect(preview).not.toHaveBeenCalled();
  expect(publish).not.toHaveBeenCalled();

  await add(form, 11112);
  await flushPromises();
  expect(preview).toHaveBeenCalledExactlyOnceWith(actualDraft);
  expect(share(form, 3717)).toBe("0%");
  expect(share(form, 11112)).toBe("50%");
  await button(form, "Опубликовать").trigger("click");
  await flushPromises();
  expect(publish).toHaveBeenCalledExactlyOnceWith(actualDraft);
  expect(share(form, 3717)).toBe("0%");
  expect(form.get(".notice-success").text()).toBe("Доли опубликованы.");
});

/** Проверяет исходные доли, закрепление и публикацию показанного распределения. */
test("публикует доли предпросмотра при снятии закрепления после расчёта", async () => {
  const initial = [offer(3717, 25), offer(11112, 25), offer(3749, 0, "archived")];
  const published = [offer(3717, 25), offer(11112, 37), offer(3749, 38)];
  const requests: OfferDraftRequest[] = [];
  const { form, fetch } = await openEditor(initial, {
    preview: (draft) => {
      requests.push(draft);
      return json({ 3717: 25, 11112: 37, 3749: 38 });
    },
    publish: (draft) => {
      requests.push(draft);
      return json(stream(published));
    },
  });
  const pin = form.get("#stream-offer-3717 button[aria-pressed]");
  await pin.trigger("click");
  expect(pin.attributes("aria-pressed")).toBe("true");
  expect(share(form, 11112)).toBe("25%");
  expect(requests).toEqual([]);
  await form.get("#stream-offer-3749 button.text-button").trigger("click");
  await flushPromises();
  expect(share(form, 3749)).toBe("38%");
  expect(share(form, 11112)).toBe("37%");
  await pin.trigger("click");
  expect(pin.attributes("aria-pressed")).toBe("false");
  expect(share(form, 3717)).toBe("25%");
  await button(form, "Опубликовать").trigger("click");
  await flushPromises();

  const draft = { offer_ids: [3717, 11112, 3749], pinned_shares: { 3717: 25 } };
  expect(requests).toEqual([draft, draft]);
  expect(fetch.mock.calls.find(([url]) => url === publishPath)?.[1]?.method).toBe("PUT");
  expect(form.get(".notice-success").text()).toBe("Доли опубликованы.");
  expect(form.find(".draft-status").exists()).toBe(false);
  await form.get("#stream-offer-3749 button.text-button").trigger("click");
  await button(form, "Отменить").trigger("click");
  await flushPromises();
  expect(share(form, 3749)).toBe("38%");
});

/** Проверяет сохранение черновика при явном отказе и неподтверждённой записи. */
test.each([
  ["Keitaro вернул ошибку HTTP 406", () => json({
    detail: { message: "Keitaro вернул ошибку HTTP 406.", outcome_unknown: false },
  }, 502)],
  ["Сверьте результат с Keitaro", () => new Response("<html>Bad Gateway</html>", { status: 502 })],
  ["Сверьте результат с Keitaro", () => json(stream([]))],
  ["Загрузите поток заново", () => json({
    detail: {
      message: "Keitaro принял публикацию, но сохранить историю не удалось. Загрузите поток заново.",
      outcome_unknown: false,
    },
  }, 503)],
] as const)("при ошибке публикации оставляет доли и показывает сообщение (%s)", async (message, reply) => {
  const { form, fetch } = await openEditor(
    [offer(3717, 33), offer(3749, 33), offer(11112, 34)],
    {
      preview: () => json({ 3717: 25, 3749: 25, 11112: 25, 11111: 25 }),
      publish: reply,
    },
  );
  await add(form, 11111);
  await flushPromises();
  expect(share(form, 11111)).toBe("25%");
  await button(form, "Опубликовать").trigger("click");
  await flushPromises();

  expect(form.get('[role="alert"]').text()).toContain(message);
  expect(form.get(".draft-status").text()).toContain("Неопубликованные изменения");
  for (const id of [3717, 3749, 11112, 11111]) expect(share(form, id)).toBe("25%");
  expect(fetch.mock.calls.filter(([url]) => url === publishPath)).toHaveLength(1);
  expect(form.find(".notice-success").exists()).toBe(false);
});

/** Проверяет запреты до расчёта и сохранение состояния при неверных закреплениях. */
test("блокирует отключённый и последний действующий офферы, не принимает невозможные доли", async () => {
  const { form, fetch } = await openEditor([offer(3717, 100), offer(3749, 40, "disabled")], {
    preview: () => json({ detail: "Оставьте хотя бы 1% для каждого незакреплённого оффера." }, 422),
  });
  await form.get("#editor-offer").setValue("3749");
  await flushPromises();
  const disabledOffer = form.get<HTMLButtonElement>(".offer-options button");
  expect(disabledOffer.element.disabled).toBe(true);
  await disabledOffer.trigger("click");
  expect(form.findAll("#stream-offer-3749")).toHaveLength(1);
  expect(form.get("#stream-offer-3749").text()).toContain("Отключён");
  expect(share(form, 3749)).toBe("40%");
  await form.get("#stream-offer-3717 button.text-button").trigger("click");
  expect(form.get('[role="alert"]').text()).toContain("хотя бы один действующий оффер");
  expect(share(form, 3717)).toBe("100%");
  expect(fetch.mock.calls.filter(([url]) => url === previewPath)).toHaveLength(0);

  await form.get("#stream-offer-3717 button[aria-pressed]").trigger("click");
  await add(form, 11113);
  await flushPromises();
  expect(form.get('[role="alert"]').text()).toContain("хотя бы 1%");
  expect(form.find("#stream-offer-11113").exists()).toBe(false);
  expect(share(form, 3717)).toBe("100%");
  expect(form.get("#stream-offer-3717 button[aria-pressed]").attributes("aria-pressed")).toBe("true");
  expect(fetch.mock.calls.filter(([url]) => url === publishPath)).toHaveLength(0);
});

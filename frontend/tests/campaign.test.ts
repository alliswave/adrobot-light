import { enableAutoUnmount, flushPromises, mount, type VueWrapper } from "@vue/test-utils";
import { afterEach, expect, test, vi } from "vitest";
import CampaignForm from "../src/features/campaign-creation/CampaignForm.vue";

const catalogPath = "/api/campaign-options";
const campaignPath = "/api/campaigns";
const searchGroup = { id: 181, name: "Поиск" };
const newGroup = { id: 182, name: "Новая группа" };
const adsSource = { id: 207, name: "Поисковая реклама" };
const networkSource = { id: 211, name: "Партнёрская сеть" };
const singleOptions = { groups: [searchGroup], traffic_sources: [adsSource] };
const australiaOffer = { id: 3717, name: "Оффер Австралия" };

enableAutoUnmount(afterEach);
afterEach(() => vi.unstubAllGlobals());

/** Возвращает ответ API с указанным содержимым. */
function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

/** Заполняет поля формы и выбирает оффер из результатов поиска. */
async function selectCampaignOffer(form: VueWrapper, query: string): Promise<void> {
  await form.get("#campaign-name").setValue("Кампания AU");
  await form.get("#campaign-country").setValue("AU");
  await form.get("#campaign-offer").setValue(query);
  await flushPromises();
  await form.get(".offer-options button").trigger("click");
}

/** Возвращает кнопку с доступной подписью обновления справочников. */
function refreshButton(form: VueWrapper) {
  const refresh = form.get<HTMLButtonElement>("button.icon-text[type=button]");
  expect(refresh.text()).toContain("Обновить справочники");
  expect(refresh.get(".refresh-icon").attributes("aria-hidden")).toBe("true");
  return refresh;
}

/** Проверяет, что выбор подсказки и двойное нажатие дают одну запись с её ID. */
test("отправляет выбранный оффер и блокирует повтор до ответа", async () => {
  let finish!: (response: Response) => void;
  const pending = new Promise<Response>((resolve) => { finish = resolve; });
  const fetch = vi.fn<(url: string, options?: RequestInit) => Promise<Response>>((url) => {
    if (url === catalogPath) return Promise.resolve(json(singleOptions));
    if (url === "/api/offers?q=3717") {
      return Promise.resolve(json([{ id: 3717, name: "Оффер Австралия" }]));
    }
    if (url === "/api/campaigns") return pending;
    throw new Error(`Неожиданный маршрут ${url}`);
  });
  vi.stubGlobal("fetch", fetch);
  const form = mount(CampaignForm);

  await selectCampaignOffer(form, "3717");
  await form.get("form").trigger("submit");
  await form.get("form").trigger("submit");

  expect(form.get<HTMLButtonElement>('button[type="submit"]').element.disabled).toBe(true);
  const writes = fetch.mock.calls.filter(([url]) => url === "/api/campaigns");
  expect(writes).toEqual([[
    "/api/campaigns",
    expect.objectContaining({
      method: "POST",
      body: JSON.stringify({
        name: "Кампания AU", country: "AU", offer_id: 3717,
        group_id: 181, traffic_source_id: 207,
      }),
    }),
  ]]);

  finish(json({ id: 42, name: "Кампания AU" }, 201));
  await flushPromises();
  expect(form.get('[role="status"]').text()).toBe("Кампания «Кампания AU» создана. ID: 42.");
});

/** Проверяет сообщение API, известный ID и различие между отказом и потерей ответа. */
test.each([false, true])("показывает ошибку записи и сохраняет данные формы (%s)", async (unknown) => {
  const verify = "Проверьте результат в Keitaro перед повтором.";
  const reason = "Не удалось подтвердить создание потока с оффером.";
  const fetch = vi.fn((url: string) => {
    if (url === catalogPath) return Promise.resolve(json(singleOptions));
    if (url === "/api/offers?q=offer") {
      return Promise.resolve(json([{ id: 3717, name: "Offer" }]));
    }
    if (url === "/api/campaigns") {
      return Promise.resolve(json({
        detail: {
          message: unknown ? `${reason} ${verify}` : reason,
          campaign_id: 42,
          outcome_unknown: unknown,
          step: "offer_stream",
        },
      }, 502));
    }
    throw new Error(`Неожиданный маршрут ${url}`);
  });
  vi.stubGlobal("fetch", fetch);
  const form = mount(CampaignForm);
  await selectCampaignOffer(form, "offer");
  await form.get("form").trigger("submit");
  await flushPromises();

  const alert = form.get('[role="alert"]').text();
  expect(alert).toContain("создание потока с оффером");
  expect(alert.includes(verify)).toBe(unknown);
  expect(alert).toContain("ID кампании: 42");
  expect(form.get<HTMLInputElement>("#campaign-name").element.value).toBe("Кампания AU");
  expect(form.get(".selected-offer").text()).toContain("#3717");
  expect(fetch.mock.calls.filter(([url]) => url === "/api/campaigns")).toHaveLength(1);
  await refreshButton(form).trigger("click");
  await flushPromises();
  expect(form.get('[role="alert"]').text()).toBe(alert);
});

/** Проверяет подсказку о сверке при ответах, которые не подтверждают исход записи. */
test.each([
  ["HTML от шлюза", () => new Response("<h1>Bad Gateway</h1>", {
    status: 502,
    headers: { "Content-Type": "text/html" },
  })],
  ["строка от шлюза", () => json({ detail: "Bad gateway" }, 502)],
  ["неизвестный шаг", () => json({
    detail: { message: "Bad gateway", campaign_id: 42, outcome_unknown: false, step: "gateway" },
  }, 502)],
  ["без признака известного исхода", () => json({
    detail: { message: "Bad gateway", campaign_id: 42, step: "campaign" },
  }, 502)],
  ["пустой успешный ответ", () => json({}, 201)],
  ["некорректный ID", () => json({ id: 0, name: "Кампания AU" }, 201)],
  ["пустое название", () => json({ id: 42, name: " " }, 201)],
] as const)("предлагает проверить результат без подтверждения (%s)", async (_name, reply) => {
  const fetch = vi.fn((url: string) => {
    if (url === catalogPath) return Promise.resolve(json(singleOptions));
    if (url === "/api/offers?q=3717") {
      return Promise.resolve(json([{ id: 3717, name: "Оффер Австралия" }]));
    }
    if (url === "/api/campaigns") {
      return Promise.resolve(reply());
    }
    throw new Error(`Неожиданный маршрут ${url}`);
  });
  vi.stubGlobal("fetch", fetch);
  const form = mount(CampaignForm);
  await selectCampaignOffer(form, "3717");
  await form.get("form").trigger("submit");
  await flushPromises();

  expect(form.get('[role="alert"]').text()).toContain("Проверьте результат в Keitaro");
  expect(form.find(".notice-success").exists()).toBe(false);
  expect(form.get(".selected-offer").text()).toContain("#3717");
  expect(fetch.mock.calls.filter(([url]) => url === "/api/campaigns")).toHaveLength(1);
});

/** Проверяет сообщение о пустом результате и игнорирование давнего ответа. */
test("сохраняет актуальные результаты поиска при ответах в обратном порядке", async () => {
  let finishOld!: (response: Response) => void;
  const old = new Promise<Response>((resolve) => { finishOld = resolve; });
  vi.stubGlobal("fetch", vi.fn((url: string) => {
    if (url === catalogPath) return Promise.resolve(json(singleOptions));
    if (url === "/api/offers?q=old") return old;
    if (url === "/api/offers?q=new") return Promise.resolve(json([]));
    throw new Error(`Неожиданный маршрут ${url}`);
  }));
  const form = mount(CampaignForm);
  await form.get("#campaign-offer").setValue("old");
  await form.get("#campaign-offer").setValue("new");
  await flushPromises();
  expect(form.get('[role="status"]').text()).toBe("Офферы не найдены.");

  finishOld(json([{ id: 3717, name: "Устаревший оффер" }]));
  await flushPromises();
  expect(form.get('[role="status"]').text()).toBe("Офферы не найдены.");
  expect(form.find(".offer-options").exists()).toBe(false);
});

/** Проверяет, что после ответа без данных оператор может повторить поиск. */
test("показывает ошибку поиска при ответе без тела и принимает следующий запрос", async () => {
  vi.stubGlobal("fetch", vi.fn()
    .mockResolvedValueOnce(json(singleOptions))
    .mockResolvedValueOnce(new Response(null, { status: 204 }))
    .mockResolvedValueOnce(json([{ id: 3717, name: "Оффер Австралия" }])));
  const form = mount(CampaignForm);
  await form.get("#campaign-offer").setValue("нет данных");
  await flushPromises();
  expect(form.get('[role="alert"]').text()).toBe("Не удалось выполнить поиск офферов.");

  await form.get("#campaign-offer").setValue("3717");
  await flushPromises();
  await form.get(".offer-options button").trigger("click");
  expect(form.get(".selected-offer").text()).toContain("#3717");
  expect(form.find('[role="alert"]').exists()).toBe(false);
});

/** Сохраняет выбранные значения при обновлении и отправляет группу из свежей выдачи. */
test("показывает новую группу после обновления без сброса черновика", async () => {
  let finish!: (response: Response) => void;
  const delayed = new Promise<Response>((resolve) => { finish = resolve; });
  const catalogs = vi.fn().mockResolvedValueOnce(json(singleOptions)).mockReturnValueOnce(delayed);
  const fetch = vi.fn<(url: string, options?: RequestInit) => Promise<Response>>((url) => {
    if (url === catalogPath) return catalogs();
    if (url.startsWith("/api/offers")) return Promise.resolve(json([australiaOffer]));
    if (url === campaignPath) return Promise.resolve(json({ id: 42, name: "Кампания AU" }, 201));
    throw new Error(`Неожиданный маршрут ${url}`);
  });
  vi.stubGlobal("fetch", fetch);
  const form = mount(CampaignForm);
  await selectCampaignOffer(form, "3717");
  const submit = form.get<HTMLButtonElement>("button[type=submit]");
  const group = form.get<HTMLSelectElement>("#campaign-group");
  const source = form.get<HTMLSelectElement>("#campaign-source");
  expect(group.element.selectedOptions[0].text).toBe("Поиск");
  expect(source.element.selectedOptions[0].text).toBe("Поисковая реклама");
  expect(submit.element.disabled).toBe(false);

  const refresh = refreshButton(form);
  await refresh.trigger("click");
  expect(refresh.element.disabled).toBe(true);
  expect(form.get('[role="status"]').text()).toBe("Загружаем справочники…");
  await refresh.trigger("click");
  await form.get("form").trigger("submit");
  expect(submit.element.disabled).toBe(true);
  expect(fetch.mock.calls.filter(([path]) => path === catalogPath)).toHaveLength(2);
  expect(fetch.mock.calls.filter(([path]) => path === campaignPath)).toHaveLength(0);

  finish(json({ groups: [searchGroup, newGroup], traffic_sources: [adsSource] }));
  await flushPromises();
  expect(group.element.selectedOptions[0].text).toBe("Поиск");
  expect(source.element.selectedOptions[0].text).toBe("Поисковая реклама");
  expect(form.get<HTMLInputElement>("#campaign-name").element.value).toBe("Кампания AU");
  expect(form.get<HTMLSelectElement>("#campaign-country").element.value).toBe("AU");
  expect(form.get(".selected-offer").text()).toContain("#3717");
  await group.setValue("182");
  await form.get("form").trigger("submit");
  expect(fetch.mock.calls.filter(([path]) => path === campaignPath)).toEqual([[
    campaignPath,
    expect.objectContaining({
      method: "POST",
      body: JSON.stringify({
        name: "Кампания AU", country: "AU", offer_id: 3717,
        group_id: 182, traffic_source_id: 207,
      }),
    }),
  ]]);
});

/** Помнит пропавший выбор после повторных обновлений до действия оператора. */
test.each(["group", "source"] as const)("требует заново выбрать исчезнувший вариант (%s)", async (field) => {
  const initial = { groups: [searchGroup, newGroup], traffic_sources: [adsSource, networkSource] };
  const next = {
    groups: field === "group" ? [newGroup] : initial.groups,
    traffic_sources: field === "source" ? [networkSource] : initial.traffic_sources,
  };
  const catalogs = vi.fn()
    .mockResolvedValueOnce(json(initial))
    .mockResolvedValueOnce(json(next))
    .mockResolvedValueOnce(json(next));
  const fetch = vi.fn((url: string) => {
    if (url === catalogPath) return catalogs();
    if (url.startsWith("/api/offers")) return Promise.resolve(json([australiaOffer]));
    throw new Error(`Неожиданный маршрут ${url}`);
  });
  vi.stubGlobal("fetch", fetch);
  const form = mount(CampaignForm);
  await selectCampaignOffer(form, "3717");
  const group = form.get<HTMLSelectElement>("#campaign-group");
  const source = form.get<HTMLSelectElement>("#campaign-source");
  const submit = form.get<HTMLButtonElement>("button[type=submit]");

  expect(group.element.selectedOptions[0].text).toBe("Выберите группу");
  expect(source.element.selectedOptions[0].text).toBe("Выберите источник");
  expect(submit.element.disabled).toBe(true);
  await group.setValue("181");
  await source.setValue("207");
  expect(submit.element.disabled).toBe(false);
  await refreshButton(form).trigger("click");
  await flushPromises();

  const cleared = field === "group" ? group : source;
  const retained = field === "group" ? source : group;
  const message = field === "group" ? "Выбранная группа больше недоступна."
    : "Выбранный источник трафика больше недоступен.";
  expect(form.get('[role="status"]').text()).toBe(message);
  expect(cleared.element.value).toBe("");
  expect(retained.element.value).toBe(field === "group" ? "207" : "181");
  await refreshButton(form).trigger("click");
  await flushPromises();
  expect(form.get('[role="status"]').text()).toBe(message);
  expect(cleared.element.value).toBe("");
  await form.get("form").trigger("submit");
  expect(fetch.mock.calls.filter(([path]) => path === campaignPath)).toHaveLength(0);
  expect(submit.element.disabled).toBe(true);
  await cleared.setValue(field === "group" ? "182" : "211");
  expect(form.find('[role="status"]').exists()).toBe(false);
  expect(submit.element.disabled).toBe(false);
});

/** Требует успешного обновления после ошибки чтения и при пустом каталоге. */
test("блокирует запись при ошибке и пустом справочнике до успешного обновления", async () => {
  const catalogs = vi.fn()
    .mockResolvedValueOnce(json(singleOptions))
    .mockResolvedValueOnce(json({ detail: "Не удалось загрузить справочники из Keitaro." }, 502))
    .mockResolvedValueOnce(json({ groups: [searchGroup], traffic_sources: [] }))
    .mockResolvedValueOnce(json(singleOptions));
  const fetch = vi.fn((url: string) => {
    if (url === catalogPath) return catalogs();
    if (url.startsWith("/api/offers")) return Promise.resolve(json([australiaOffer]));
    throw new Error(`Неожиданный маршрут ${url}`);
  });
  vi.stubGlobal("fetch", fetch);
  const form = mount(CampaignForm);
  await selectCampaignOffer(form, "3717");
  const submit = form.get<HTMLButtonElement>("button[type=submit]");
  expect(submit.element.disabled).toBe(false);

  await refreshButton(form).trigger("click");
  await flushPromises();
  expect(form.get('[role="alert"]').text()).toBe("Не удалось загрузить справочники из Keitaro.");
  expect(submit.element.disabled).toBe(true);
  await form.get("form").trigger("submit");

  await refreshButton(form).trigger("click");
  await flushPromises();
  expect(form.text()).toContain("В Keitaro нет доступных источников трафика.");
  expect(submit.element.disabled).toBe(true);
  await form.get("form").trigger("submit");

  await refreshButton(form).trigger("click");
  await flushPromises();
  expect(form.find('[role="alert"]').exists()).toBe(false);
  expect(submit.element.disabled).toBe(true);
  await form.get("#campaign-source").setValue("207");
  expect(submit.element.disabled).toBe(false);
  expect(form.get(".selected-offer").text()).toContain("#3717");
  expect(fetch.mock.calls.filter(([path]) => path === campaignPath)).toHaveLength(0);
});

/** После явного отказа сохраняет его причину и ждёт обновления без повторной записи. */
test("после отказа Keitaro предлагает обновить справочники", async () => {
  const fetch = vi.fn((url: string) => {
    if (url === catalogPath) return Promise.resolve(json(singleOptions));
    if (url.startsWith("/api/offers")) return Promise.resolve(json([australiaOffer]));
    if (url === campaignPath) return Promise.resolve(json({
      detail: {
        message: "Keitaro отклонил параметры кампании (HTTP 406).",
        step: "campaign", campaign_id: null, outcome_unknown: false, refresh_options: true,
      },
    }, 502));
    throw new Error(`Неожиданный маршрут ${url}`);
  });
  vi.stubGlobal("fetch", fetch);
  const form = mount(CampaignForm);
  await selectCampaignOffer(form, "3717");
  await form.get("form").trigger("submit");
  await flushPromises();

  expect(form.get('[role="alert"]').text()).toContain("HTTP 406). Обновите справочники");
  const submit = form.get<HTMLButtonElement>("button[type=submit]");
  expect(submit.element.disabled).toBe(true);
  expect(fetch.mock.calls.filter(([path]) => path === catalogPath)).toHaveLength(1);
  await form.get("form").trigger("submit");

  await refreshButton(form).trigger("click");
  await flushPromises();
  expect(submit.element.disabled).toBe(false);
  expect(form.get('[role="alert"]').text()).toBe("Keitaro отклонил параметры кампании (HTTP 406).");
  expect(fetch.mock.calls.filter(([path]) => path === campaignPath)).toHaveLength(1);
});

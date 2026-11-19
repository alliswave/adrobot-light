"""Примеры распределения трафика из записи и недопустимые черновики."""

import pytest

from app.services.offer_shares import InvalidOfferShares, distribute_offer_shares


@pytest.mark.parametrize(
    ("offer_ids", "pinned", "expected"),
    [
        ([3717, 3749, 11111, 11112], {}, {3717: 25, 3749: 25, 11111: 25, 11112: 25}),
        ([3749, 11111, 11112], {}, {3749: 33, 11111: 33, 11112: 34}),
        ([3717, 11112, 3749], {3717: 25}, {3717: 25, 11112: 37, 3749: 38}),
        ([3717, 3749], {3717: 25, 3749: 75}, {3717: 25, 3749: 75}),
        ([3717, 3749, 11112], {3717: 0}, {3717: 0, 3749: 50, 11112: 50}),
        ([3717, 3749, 11111, 11112], {3717: 26}, {3717: 26, 3749: 24, 11111: 25, 11112: 25}),
    ],
)
def test_distributes_shares_by_offer_order(
    offer_ids: list[int], pinned: dict[int, int], expected: dict[int, int]
) -> None:
    """Проверяет получателей лишних пунктов и сохранение закреплённых долей."""
    shares = distribute_offer_shares(offer_ids, pinned)
    assert shares == expected
    assert list(shares) == offer_ids


@pytest.mark.parametrize(
    ("offer_ids", "pinned"),
    [
        ([], {}),
        ([3717, 3717], {}),
        ([3717, 3749], {11111: 25}),
        ([3717, 3749], {3717: -1}),
        ([3717, 3749], {3717: True}),
        ([3717, 3749], {3717: 101}),
        ([3717, 3749], {3717: 100}),
        ([3717, 3749], {3717: 25, 3749: 25}),
    ],
)
def test_rejects_invalid_distribution(offer_ids: list[int], pinned: dict[int, int]) -> None:
    """Отклоняет состав и закрепления, которые не дают распределить трафик."""
    with pytest.raises(InvalidOfferShares):
        distribute_offer_shares(offer_ids, pinned)

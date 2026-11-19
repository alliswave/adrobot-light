"""Распределение целых процентов между действующими офферами."""

from collections.abc import Mapping, Sequence

FULL_OFFER_SHARE = 100


class InvalidOfferShares(ValueError):
    """Из состава и закреплений нельзя получить допустимые доли."""


def distribute_offer_shares(
    offer_ids: Sequence[int], pinned_shares: Mapping[int, int]
) -> dict[int, int]:
    """Делит остаток поровну, отдавая лишние пункты последним свободным офферам."""
    if not offer_ids:
        raise InvalidOfferShares("В потоке должен остаться хотя бы один действующий оффер.")
    if len(set(offer_ids)) != len(offer_ids):
        raise InvalidOfferShares("Один оффер нельзя добавить в поток дважды.")
    if not set(pinned_shares).issubset(offer_ids) or any(
        type(share) is not int or not 0 <= share <= FULL_OFFER_SHARE
        for share in pinned_shares.values()
    ):
        raise InvalidOfferShares("Закрепите целую долю от 0% до 100% у действующего оффера.")

    remaining = FULL_OFFER_SHARE - sum(pinned_shares.values())
    free_ids = [offer_id for offer_id in offer_ids if offer_id not in pinned_shares]
    if not free_ids:
        if remaining:
            raise InvalidOfferShares("Если все доли закреплены, их сумма должна быть 100%.")
        return {offer_id: pinned_shares[offer_id] for offer_id in offer_ids}
    if remaining < len(free_ids):
        raise InvalidOfferShares("Оставьте хотя бы 1% для каждого незакреплённого оффера.")

    share, extra = divmod(remaining, len(free_ids))
    free_shares = dict.fromkeys(free_ids, share)
    for offer_id in reversed(free_ids[len(free_ids) - extra :]):
        free_shares[offer_id] += 1
    free_shares.update(pinned_shares)
    return {offer_id: free_shares[offer_id] for offer_id in offer_ids}

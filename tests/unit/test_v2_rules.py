"""Regras da v2 em isolamento: faixas da R2 (C3), família R2/R6, janela noturna e hash canônico (C4)."""

from datetime import datetime
from types import SimpleNamespace

import pytest

from antifraud import config
from antifraud.context import night_window
from antifraud.engine import combine_rules
from antifraud.result import Action, RuleResult
from antifraud.rules import r1_unregistered_device, r2_night_pattern, r3_account_owner
from dtos.pix_transaction_input import PixTransactionInput


def night_ctx(amount, night_amount=0, average=20000, nights=5, hour=23):
    local_time = datetime(2026, 10, 17, hour, 0, tzinfo=config.BRASILIA)
    return SimpleNamespace(
        data=SimpleNamespace(amount=amount), is_night=hour >= 20 or hour < 6, local_time=local_time,
        night_amount=night_amount, night_average=average, nights_with_pix=nights,
    )


class TestR2Bands:
    @pytest.mark.parametrize(
        "amount, expected",
        [
            (60000, None),     # 3x exato: passa
            (60001, 0.20),     # acima de 3x
            (100000, 0.20),    # 5x exato: ainda faixa moderada
            (100001, 0.40),    # acima de 5x
            (200000, 0.40),    # T6: média R$ 200, R$ 2.000
        ],
    )
    def test_bands(self, amount, expected):
        hits = r2_night_pattern.evaluate(night_ctx(amount), [])
        if expected is None:
            assert hits == []
        else:
            assert [(h.reason, h.weight, h.action) for h in hits] == [("desvio_noturno", expected, Action.NONE)]

    def test_night_sum_counts(self):
        # já fez R$ 400 hoje à noite; +R$ 300 = 3.5x a média
        assert r2_night_pattern.evaluate(night_ctx(30000, night_amount=40000), [])[0].weight == 0.20

    def test_needs_three_nights(self):
        assert r2_night_pattern.evaluate(night_ctx(200000, nights=2), []) == []  # T7

    def test_day_has_no_hit(self):
        assert r2_night_pattern.evaluate(night_ctx(200000, hour=15), []) == []


class TestNightWindow:
    def test_anchored_at_night_start(self):
        start, end = night_window(datetime(2026, 10, 18, 2, 0, tzinfo=config.BRASILIA))
        assert start == datetime(2026, 10, 17, 20, 0, tzinfo=config.BRASILIA)
        assert end == datetime(2026, 10, 18, 6, 0, tzinfo=config.BRASILIA)

    def test_evening(self):
        start, _ = night_window(datetime(2026, 10, 17, 23, 30, tzinfo=config.BRASILIA))
        assert start == datetime(2026, 10, 17, 20, 0, tzinfo=config.BRASILIA)


class TestAmountFamily:
    def test_r2_and_r6_take_the_max(self):
        family = config.AMOUNT_DEVIATION_FAMILY
        hits = [
            RuleResult("R2", "desvio_noturno", weight=0.40, family=family),
            RuleResult("R6", "valor_atipico", weight=0.30, family=family),
            RuleResult("EXTRA", "destino_desconhecido", weight=0.10),
        ]
        assert combine_rules(hits) == pytest.approx(1 - 0.60 * 0.90)


class TestR1DeviceApi:
    def test_unavailable_asks_2fa(self):
        ctx = SimpleNamespace(device_api_available=False, device_registered=False, data=SimpleNamespace(amount=999999))
        [hit] = r1_unregistered_device.evaluate(ctx, [])
        assert (hit.reason, hit.action, hit.weight) == ("device_api_indisponivel", Action.TWO_FACTOR, 0.30)


class TestR3:
    def test_source_has_floor_destination_does_not(self):
        ctx = SimpleNamespace(source_owner_conflict=True, destination_owner_conflict=True)
        source_hit, destination_hit = r3_account_owner.evaluate(ctx, [])
        assert source_hit.floor == config.OWNER_MISMATCH_FLOOR
        assert destination_hit.floor is None
        assert {source_hit.action, destination_hit.action} == {Action.REJECT}


class TestCanonicalHash:
    def payload(self, **source_account):
        account = {
            "branch": "0001", "account_number": "10442", "opening_date": "2025-03-02T10:00:00-03:00",
            "owner": {"document_number": "123.456.789-09"},
        }
        account.update(source_account)
        return {
            "id": "pix-1", "amount": 150000, "transaction_date": "2026-10-17T22:15:00-03:00",
            "source_account": account,
            "destination_account": {
                "participant": "60701190", "branch": "3675", "account_number": "1", "opening_date": "2024-01-01T09:00:00-03:00",
                "owner": {"document_number": "987.654.321-00"},
            },
            "source": {"device_id": "dvc-1", "channel": "app", "ip": "198.51.100.23"},
        }

    def test_equivalent_payloads_share_the_hash(self):
        original = PixTransactionInput.from_payload(self.payload())
        retry = PixTransactionInput.from_payload(
            self.payload(branch="1", account_number="010442", owner={"document_number": "12345678909"})
        )
        assert original.canonical_sha256() == retry.canonical_sha256()

    def test_other_amount_changes_the_hash(self):
        original = PixTransactionInput.from_payload(self.payload())
        changed = PixTransactionInput.from_payload({**self.payload(), "amount": 150001})
        assert original.canonical_sha256() != changed.canonical_sha256()

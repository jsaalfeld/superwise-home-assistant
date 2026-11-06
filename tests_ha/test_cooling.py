"""Forecast accuracy and invalidation with synthetic kiln telemetry."""

import math

import pytest

from custom_components.superwise.cooling import CoolingEstimate

NOW = 1_800_000_000.0


def controller(stamp, value, **overrides):
    return {
        "lastActive": stamp * 1000,
        "value": value,
        "processStatus": "PS_FINISHED",
        "setpoint": 0,
        "lpValue": None,
        "error": 0,
        **overrides,
    }


def curve():
    model = CoolingEstimate()
    for minute in range(121):
        stamp = NOW - (120 - minute) * 60
        value = 15 + 600 * math.exp(-0.15 * (stamp - NOW) / 3600)
        model.update(controller(stamp, value), stamp)
    return model


def test_exponential_forecast_accounts_for_slowing_cooling():
    model = curve()
    for target in (200, 100):
        expected = NOW + math.log(600 / (target - 15)) / 0.15 * 3600
        assert 0 <= model.estimates[target].timestamp() - expected < 300
    assert model.estimates[100] > model.estimates[200]
    assert model.details["fit_r_squared"] == 1


@pytest.mark.parametrize(
    "overrides",
    [
        {"processStatus": "PS_RUNNING"},
        {"processStatus": "PS_HOLDED"},
        {"error": 3},
        {"lpValue": 1},
        {"setpoint": 200},
        {"value": float("nan")},
        {"lastActive": (NOW - 61) * 1000},
        {"lastActive": (NOW + 1) * 1000},
    ],
)
def test_forecast_is_cleared_for_unsafe_or_invalid_telemetry(overrides):
    model = curve()
    model.update(controller(NOW, 615) | overrides, NOW)
    assert not model.estimates
    assert not model.samples


def test_short_flat_reheating_and_interrupted_curves_have_no_forecast():
    for values in (
        [600 - minute for minute in range(20)],
        [600] * 121,
        [600 + minute for minute in range(121)],
    ):
        model = CoolingEstimate()
        for minute, value in enumerate(values):
            stamp = NOW + minute * 60
            model.update(controller(stamp, value), stamp)
        assert not model.estimates
    model = curve()
    model.update(controller(NOW + 600, 580), NOW + 600)
    assert not model.estimates


def test_reached_target_does_not_get_a_future_time():
    model = CoolingEstimate()
    for minute in range(121):
        stamp = NOW - (120 - minute) * 60
        value = 15 + 135 * math.exp(-0.15 * (stamp - NOW) / 3600)
        model.update(controller(stamp, value), stamp)
    assert 200 not in model.estimates
    assert 100 in model.estimates


def test_duplicate_and_out_of_order_samples_do_not_skew_fit():
    model = curve()
    original = model.estimates.copy()
    model.update(controller(NOW, 615), NOW)
    assert model.estimates == original
    before = model.samples.copy()
    model.add(NOW - 30, 1000)
    assert model.samples == before

"""Extract page JSON and normalize public measurements without controller secrets."""

import datetime as dt
import json
import math
import re
import time


def embedded(html, variable):
    match = re.search(
        r"\b(?:let|const|var)\s+" + re.escape(variable) + r"\s*=\s*", html
    )
    if not match:
        raise ValueError(f"Expected page variable missing: {variable}")
    return json.JSONDecoder().raw_decode(html[match.end() :])[0]


def pick(obj, keys):
    return {key: obj[key] for key in keys if key in obj}


def number(value):
    try:
        value = float(value)
        return value if math.isfinite(value) and abs(value) < 1e38 else None
    except (ValueError, TypeError):
        return None


def controller_summary(controller, rated_power_kw=None):
    result = pick(
        controller,
        (
            "serialNumber",
            "name",
            "type",
            "lastActive",
            "processStatus",
            "processInfo",
            "progNumber",
            "segNumber",
            "remainingSegmentSeconds",
            "segmentMode",
            "error",
            "doValue",
            "diValue",
            "sequenceNumber",
        ),
    )
    for key in ("value", "setpoint", "lpValue"):
        result[key] = number(controller.get(key))
    stamp = controller.get("lastActive")
    result["age_seconds"] = round(time.time() - stamp / 1000, 1) if stamp else None
    result["fresh"] = (
        result["age_seconds"] is not None and 0 <= result["age_seconds"] < 60
    )
    percent = result["lpValue"]
    result["rated_power_kw"] = rated_power_kw
    result["estimated_power_kw"] = (
        round(rated_power_kw * percent / 100, 4)
        if rated_power_kw is not None
        and result["fresh"]
        and percent is not None
        and 0 <= percent <= 100
        else None
    )
    return result


def sensor_summary(sensor):
    return pick(sensor, ("identifier", "name", "unit", "min", "max", "error"))


def live_summary(payload, rated_power_kw=None):
    return {
        "received_at": dt.datetime.now(dt.UTC).isoformat(),
        "controller": controller_summary(payload["controlUnit"], rated_power_kw),
        "sensors": [
            dict(sensor_summary(sensor["descr"]), value=number(sensor.get("val")))
            for sensor in payload.get("sensors", [])
        ],
        "new_alarm_count": len(payload.get("newAlarms", [])),
        "new_process_event_count": len(payload.get("newPrcsInfo", [])),
    }

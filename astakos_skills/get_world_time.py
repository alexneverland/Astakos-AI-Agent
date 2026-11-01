"""World-time lookup skill backed by the standard-library IANA timezone data."""

from datetime import datetime
from zoneinfo import ZoneInfo, available_timezones

from langchain_core.tools import tool

from core.i18n import t

ASTAKOS_LOCAL_TIMEZONE = ZoneInfo("Europe/Athens")

_COMMON_CITIES: dict[str, str] = {
    "london": "Europe/London",
    "athens": "Europe/Athens",
    "new york": "America/New_York",
    "tokyo": "Asia/Tokyo",
    "san francisco": "America/Los_Angeles",
    "mumbai": "Asia/Kolkata",
    "beijing": "Asia/Shanghai",
    "delhi": "Asia/Kolkata",
    "barcelona": "Europe/Madrid",
    "cape town": "Africa/Johannesburg",
}

@tool
def get_world_time(city: str) -> str:
    """Returns the local time for supported English city names or a valid IANA timezone."""
    city_key = city.lower().strip()
    matched_zone = _COMMON_CITIES.get(city_key)

    if matched_zone is None and city in available_timezones():
        matched_zone = city

    if matched_zone is None:
        city_key_suffix = city_key.replace(" ", "_")
        matched_zone = next(
            (zone for zone in available_timezones() if zone.casefold().endswith(f"/{city_key_suffix}")),
            None,
        )
    if matched_zone is None:
        matched_zone = next(
            (zone for zone in available_timezones() if city_key_suffix in zone.casefold()),
            None,
        )
    if matched_zone is None:
        return t("world_time_not_found", city=city)

    city_time = datetime.now(ZoneInfo(matched_zone))
    local_time = datetime.now(ASTAKOS_LOCAL_TIMEZONE)
    offset_hours = (city_time.utcoffset() - local_time.utcoffset()).total_seconds() / 3600
    formatted_offset = f"{offset_hours:+g}" if offset_hours else "0"

    return t(
        "world_time_result",
        city=city.title(),
        timezone=matched_zone,
        time=city_time.strftime("%Y-%m-%d %H:%M:%S"),
        diff=formatted_offset,
    )

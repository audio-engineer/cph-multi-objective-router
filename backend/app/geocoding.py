"""External geocoding helpers."""

from typing import TYPE_CHECKING, cast

import osmnx as ox
import requests

from app.models import ReverseGeocodeResponse

if TYPE_CHECKING:
    from collections.abc import Callable

type JsonObject = dict[str, object]


def reverse_geocode_address(
    longitude: float,
    latitude: float,
    *,
    zoom_level: int = 18,
) -> ReverseGeocodeResponse:
    """Reverse geocode coordinates to a single-line road + house number string."""
    reverse_url = ox.settings.nominatim_url.rstrip("/") + "/reverse"
    request_get = cast("Callable[..., requests.Response]", requests.get)

    params: dict[str, str | int | float] = {
        "format": "jsonv2",
        "lat": latitude,
        "lon": longitude,
        "zoom": zoom_level,
    }
    headers: dict[str, str] = {
        "User-Agent": ox.settings.http_user_agent,
        "Referer": ox.settings.http_referer,
        "Accept-Language": ox.settings.http_accept_language,
    }

    response = request_get(
        reverse_url,
        params=params,
        headers=headers,
        timeout=ox.settings.requests_timeout,
        **dict(ox.settings.requests_kwargs),
    )
    response.raise_for_status()

    payload = cast("object", response.json())

    if not isinstance(payload, dict):
        return ReverseGeocodeResponse(address="")

    payload_object = cast("JsonObject", payload)
    raw_address = payload_object.get("address")

    if not isinstance(raw_address, dict):
        return ReverseGeocodeResponse(address="")

    address_object = cast("JsonObject", raw_address)
    road = str(address_object.get("road") or "").strip()
    house_number = str(address_object.get("house_number") or "").strip()
    formatted_address = " ".join(part for part in (road, house_number) if part)

    return ReverseGeocodeResponse(address=formatted_address)

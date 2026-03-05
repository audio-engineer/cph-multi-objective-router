"""External geocoding helpers."""

import osmnx as ox
import requests

from app.models import ReverseGeocodeResponse


def reverse_geocode_address(
    longitude: float,
    latitude: float,
    *,
    zoom_level: int = 18,
) -> ReverseGeocodeResponse:
    """Reverse geocode coordinates to a single-line road + house number string."""
    reverse_url = ox.settings.nominatim_url.rstrip("/") + "/reverse"

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

    response = requests.get(
        reverse_url,
        params=params,
        headers=headers,
        timeout=ox.settings.requests_timeout,
        **ox.settings.requests_kwargs,
    )
    response.raise_for_status()

    payload = response.json()

    if not isinstance(payload, dict):
        return ReverseGeocodeResponse(address="")

    raw_address = payload.get("address")

    if not isinstance(raw_address, dict):
        return ReverseGeocodeResponse(address="")

    road = str(raw_address.get("road") or "").strip()
    house_number = str(raw_address.get("house_number") or "").strip()
    formatted_address = " ".join(part for part in (road, house_number) if part)

    return ReverseGeocodeResponse(address=formatted_address)

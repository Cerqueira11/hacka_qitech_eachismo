"""R5 — Localização fora do habitual: viagem impossível ou longe do centróide."""

from typing import List

from antifraud import config
from antifraud.context import AntifraudContext
from antifraud.result import Action, RuleResult
from antifraud.stats import haversine_km

RULE = "R5"


def evaluate(ctx: AntifraudContext, previous: List[RuleResult]) -> List[RuleResult]:
    geolocation = ctx.data.geolocation
    if geolocation is None:
        return [RuleResult(RULE, "sem_geolocalizacao", weight=config.NO_GEOLOCATION_WEIGHT)]

    history = ctx.source_geolocations  # mais recente primeiro
    if history:
        last_date, last_lat, last_lon = history[0]
        distance = haversine_km(last_lat, last_lon, geolocation.latitude, geolocation.longitude)
        # Piso de 1 minuto: dois Pix no mesmo instante não dão velocidade infinita.
        hours = max(abs((ctx.as_of - last_date).total_seconds()) / 3600, 1 / 60)
        if distance > config.IMPOSSIBLE_TRAVEL_MIN_KM and distance / hours > config.IMPOSSIBLE_TRAVEL_KMH:
            return [
                RuleResult(RULE, "viagem_impossivel", action=Action.TWO_FACTOR, weight=config.LOCATION_WEIGHT)
            ]

    if len(history) >= config.LOCATION_MIN_HISTORY:
        # Média simples de lat/lon: boa aproximação para distâncias de cidade/estado.
        centroid_lat = sum(lat for _, lat, _ in history) / len(history)
        centroid_lon = sum(lon for _, _, lon in history) / len(history)
        distance = haversine_km(centroid_lat, centroid_lon, geolocation.latitude, geolocation.longitude)
        if distance > config.LOCATION_MAX_KM_FROM_CENTROID:
            return [
                RuleResult(RULE, "localizacao_atipica", action=Action.TWO_FACTOR, weight=config.LOCATION_WEIGHT)
            ]

    return []

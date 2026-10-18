import math
from statistics import mean, median, pstdev
from typing import Iterable, Optional


def log_zscore(amount: int, history: Iterable[int], std_floor: float) -> Optional[float]:
    """Quantos desvios o ln(valor) está acima do padrão. None sem histórico.

    Valores de Pix têm cauda longa (muito Pix pequeno, poucos grandes); em
    escala log a média e o desvio deixam de ser puxados pelos poucos grandes.
    """
    logs = [math.log(value) for value in history if value > 0]
    if not logs:
        return None
    deviation = max(pstdev(logs), std_floor)
    return (math.log(amount) - mean(logs)) / deviation


def median_of(values: Iterable[float]) -> float:
    return median(list(values))


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    radius_km = 6371.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    d_phi = math.radians(lat2 - lat1)
    d_lambda = math.radians(lon2 - lon1)
    a = math.sin(d_phi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2) ** 2
    return 2 * radius_km * math.asin(math.sqrt(a))

from typing import Optional
from uuid import UUID

from database import Context
from models import Geolocation


class GeolocationRepository:
    """A camada que fala com a tabela geolocation no banco de dados."""

    def __init__(self, context: Context) -> None:
        self.session = context.db_session

    def create(self, latitude: float, longitude: float) -> Geolocation:
        geo = Geolocation()
        geo.latitude = latitude
        geo.longitude = longitude

        self.session.add(geo)
        return geo

    def get_by_id(self, id_geolocation: UUID) -> Optional[Geolocation]:
        return (
            self.session.query(Geolocation)
            .filter(Geolocation.id_geolocation == id_geolocation)
            .first()
        )

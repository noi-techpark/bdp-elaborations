# SPDX-FileCopyrightText: NOI Techpark <digital@noi.bz.it>
#
# SPDX-License-Identifier: AGPL-3.0-or-later

from __future__ import absolute_import, annotations

import ast
from dataclasses import dataclass

import logging
from typing import Optional, ClassVar, TypeVar

logger = logging.getLogger("pollution_v2.common.data_model.station")


@dataclass
class Station:

    code: str
    active: bool
    available: bool
    coordinates: dict
    metadata: dict
    name: str
    station_type: str
    origin: Optional[str]

    @property
    def km(self) -> float:
        """
        Returns station mileage.
        """
        if self.metadata.get("a22_metadata"):
            metadata = ast.literal_eval(self.metadata["a22_metadata"])
            if metadata.get("metro"):
                return (int(metadata["metro"])) / 1000
        logger.debug(f"Mileage not defined for station [{self.code}]")
        return -1000

    @property
    def sensor_type(self) -> float:
        """
        Returns sensor type.
        """
        return self.metadata.get("sensor_type")

    __version__: ClassVar[int] = 1

    @classmethod
    def from_odh_repr(cls, raw_data: dict):
        return cls(
            code=raw_data["scode"],
            active=raw_data["sactive"],
            available=raw_data["savailable"],
            coordinates=raw_data["scoordinate"],
            metadata=raw_data["smetadata"],
            name=raw_data["sname"],
            station_type=raw_data["stype"],
            origin=raw_data.get("sorigin")
        )

    def to_json(self) -> dict:
        return {
            "code": self.code,
            "active": self.active,
            "available": self.available,
            "coordinates": self.coordinates,
            "metadata": self.metadata,
            "name": self.name,
            "station_type": self.station_type,
            "origin": self.origin
        }

    @classmethod
    def from_json(cls, dict_data) -> Station:
        return Station(
            code=dict_data["code"],
            active=dict_data["active"],
            available=dict_data["available"],
            coordinates=dict_data["coordinates"],
            metadata=dict_data["metadata"],
            name=dict_data["name"],
            station_type=dict_data["station_type"],
            origin=dict_data["origin"]
        )


StationType = TypeVar("StationType", bound=Station)


@dataclass
class TrafficSensorStation(Station):
    """
    Class representing a traffic station.
    """

    def split_station_code(self) -> (str, int, int):
        """
        splits the station code using the pattern ID_strada:ID_stazione:ID_corsia and returns a tuple
        with the following structure (ID_strada, ID_stazione, ID_corsia)
        :return:
        """
        splits = self.code.split(":")
        if len(splits) != 3:
            raise ValueError(f"Unable to split [{self.code}] in ID_strada:ID_stazione:ID_corsia")
        return splits[0], int(splits[1]), int(splits[2])

    @property
    def id_strada(self) -> str:
        id_strada, id_stazione, id_corsia = self.split_station_code()
        return id_strada

    @property
    def id_stazione(self) -> int:
        id_strada, id_stazione, id_corsia = self.split_station_code()
        return id_stazione

    @property
    def id_corsia(self) -> int:
        id_strada, id_stazione, id_corsia = self.split_station_code()
        return id_corsia

    @classmethod
    def from_json(cls, dict_data) -> TrafficSensorStation:
        return TrafficSensorStation(
            code=dict_data["code"],
            active=dict_data["active"],
            available=dict_data["available"],
            coordinates=dict_data["coordinates"],
            metadata=dict_data["metadata"],
            name=dict_data["name"],
            station_type=dict_data["station_type"],
            origin=dict_data["origin"]
        )

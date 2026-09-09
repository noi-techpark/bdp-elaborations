# SPDX-FileCopyrightText: 2026 NOI Techpark <digital@noi.bz.it>
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""A small client for what the parking forecast jobs need to read from Open
Data Hub's time series API ("ninja"): station metadata and occupancy
history. No write path — publishing forecasts back to ODH isn't wired up
yet.
"""

import re
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone

import requests

REQUEST_TIME_FORMAT = "%Y-%m-%dT%H:%M:%S.{ms:03d}%z"
RESPONSE_TIME_FORMAT = "%Y-%m-%d %H:%M:%S.%f%z"

_ESCAPE_RE = re.compile(r"[\\,'\"]")


def _escape(value: str) -> str:
    return '"' + _ESCAPE_RE.sub(lambda m: "\\" + m.group(0), value) + '"'


def _escape_list(values: list[str]) -> list[str]:
    return [_escape(v) for v in values]


def _where_eq(field_name: str, value: str) -> str:
    return f"{field_name}.eq.{value}"


def _where_in(field_name: str, values: list[str]) -> str:
    return f"{field_name}.in.({','.join(values)})"


def _where_and(exprs: list[str]) -> str:
    return f"and({','.join(exprs)})"


def _format_request_time(dt: datetime) -> str:
    dt = dt.astimezone(timezone.utc)
    ms = dt.microsecond // 1000
    return dt.strftime(REQUEST_TIME_FORMAT.format(ms=ms))


def _parse_response_time(s: str) -> datetime | None:
    try:
        return datetime.strptime(s, RESPONSE_TIME_FORMAT)
    except ValueError:
        return None


@dataclass
class StationInfo:
    """The subset of ODH station metadata the forecast needs."""

    scode: str
    name: str
    station_type: str
    lat: float
    lon: float
    capacity: float  # parking spaces; a ParkingSensor covers exactly one, so its capacity is always 1
    last_occupancy_ts: datetime | None = None

    @property
    def has_occupancy_ts(self) -> bool:
        return self.last_occupancy_ts is not None


@dataclass
class Measurement:
    station_code: str
    timestamp: datetime
    value: float


@dataclass
class _Auth:
    token_url: str
    client_id: str
    client_secret: str
    _access_token: str = field(default="", init=False)
    _expiry: float = field(default=0.0, init=False)

    def get_token(self) -> str:
        if not self._access_token or time.time() > self._expiry:
            self._new_token()
        return self._access_token

    def _new_token(self) -> None:
        resp = requests.post(
            self.token_url,
            data={
                "client_id": self.client_id,
                "client_secret": self.client_secret,
                "grant_type": "client_credentials",
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        resp.raise_for_status()
        token = resp.json()
        self._access_token = token["access_token"]
        self._expiry = time.time() + token["expires_in"] - 600  # 600s margin


class Client:
    def __init__(
        self,
        base_url: str,
        token_url: str,
        referer: str,
        client_id: str,
        client_secret: str,
        station_types: list[str],
        occupancy_type: str,
        occupancy_period: int,
    ):
        self._base_url = base_url.rstrip("/")
        self._referer = referer
        self._auth = _Auth(token_url, client_id, client_secret) if client_id else None
        self._station_types = station_types
        self._occupancy_type = occupancy_type
        self._occupancy_period = occupancy_period

    def _headers(self) -> dict[str, str]:
        headers = {"Accept": "application/json"}
        if self._auth is not None:
            headers["Authorization"] = f"Bearer {self._auth.get_token()}"
        if self._referer:
            headers["Referer"] = self._referer
        return headers

    def _get(self, path: str, params: dict[str, str]) -> dict:
        resp = requests.get(f"{self._base_url}{path}", params=params, headers=self._headers())
        resp.raise_for_status()
        return resp.json()

    def fetch_stations(self) -> list[StationInfo]:
        """Every active station of the configured types, plus the latest
        occupancy timestamp ODH has for each.
        """
        stationtypes = ",".join(self._station_types) if self._station_types else "*"
        path = f"/tree,node/{stationtypes}/{self._occupancy_type}/latest"
        where = _where_and([_where_eq("sactive", "true"), _where_in("mperiod", [str(self._occupancy_period)])])
        body = self._get(path, {"where": where, "limit": "-1"})

        out: list[StationInfo] = []
        for _stype, stype_data in body.get("data", {}).items():
            for scode, st in stype_data.get("stations", {}).items():
                # ParkingSensor stations are single-space sensors and don't
                # carry a "capacity" metadata field; only ParkingStation
                # aggregates do.
                station_type = st.get("stype", "")
                capacity = 1.0
                if station_type == "ParkingStation":
                    capacity = 0.0
                    meta_capacity = (st.get("smetadata") or {}).get("capacity")
                    if isinstance(meta_capacity, (int, float)):
                        capacity = float(meta_capacity)

                coord = st.get("scoordinate") or {}
                info = StationInfo(
                    scode=scode,
                    name=st.get("sname", ""),
                    station_type=station_type,
                    lat=float(coord.get("Y", coord.get("y", 0.0))),
                    lon=float(coord.get("X", coord.get("x", 0.0))),
                    capacity=capacity,
                )

                dt = (st.get("sdatatypes") or {}).get(self._occupancy_type)
                if dt is not None:
                    for m in dt.get("tmeasurements", []):
                        if int(m.get("mperiod", -1)) != self._occupancy_period:
                            continue
                        ts = _parse_response_time(m.get("mvalidtime", ""))
                        if ts is not None:
                            info.last_occupancy_ts = ts
                out.append(info)
        return out

    def fetch_occupancy_history(
        self, station_type: str, scodes: list[str], from_ts: datetime, to_ts: datetime
    ) -> list[Measurement]:
        """Raw occupancy measurements in the half-open interval [from, to)."""
        if not scodes or not to_ts > from_ts:
            return []

        path = (
            f"/flat,node/{station_type}/{self._occupancy_type}"
            f"/{_format_request_time(from_ts)}/{_format_request_time(to_ts)}"
        )
        where = _where_and(
            [
                _where_eq("sactive", "true"),
                _where_in("mperiod", [str(self._occupancy_period)]),
                _where_in("scode", _escape_list(scodes)),
            ]
        )

        out: list[Measurement] = []
        offset = 0
        limit = -1
        while True:
            body = self._get(
                path,
                {
                    "select": "mvalue,mperiod,mvalidtime,scode,stype,tname",
                    "where": where,
                    "limit": str(limit),
                    "offset": str(offset),
                },
            )
            data = body.get("data") or []
            for m in data:
                value = m.get("mvalue")
                if not isinstance(value, (int, float)) or isinstance(value, bool):
                    continue
                ts = _parse_response_time(m.get("mvalidtime", ""))
                if ts is None:
                    continue
                out.append(Measurement(station_code=m.get("scode", ""), timestamp=ts, value=float(value)))

            # limit is fixed to -1 here, so this loop only ever runs once.
            resp_limit = body.get("limit")
            if resp_limit != len(data):
                break
            offset += len(data)

        return out

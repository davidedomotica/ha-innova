"""Async client for the Innova 3.x cloud (REST v2 + raw gRPC/protobuf)."""
from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass, field
import logging
import struct
import uuid

import httpx

from .const import API_BASE, GRPC_HOST, M_SEND_DEVICE, M_SUBSCRIBE

_LOGGER = logging.getLogger(__name__)


class InnovaError(Exception):
    """Network, cloud or protocol error."""


class InnovaAuthError(InnovaError):
    """Invalid credentials or expired authorization."""


def _varint(value: int) -> bytes:
    value &= 0xFFFFFFFFFFFFFFFF
    out = bytearray()
    while value >= 0x80:
        out.append((value & 0x7F) | 0x80)
        value >>= 7
    out.append(value)
    return bytes(out)


def _read_varint(data: bytes, offset: int) -> tuple[int, int]:
    value = 0
    shift = 0
    while offset < len(data):
        byte = data[offset]
        offset += 1
        value |= (byte & 0x7F) << shift
        if byte < 0x80:
            return value, offset
        shift += 7
        if shift > 70:
            break
    raise InnovaError("invalid protobuf varint")


def _field_varint(number: int, value: int) -> bytes:
    return _varint(number << 3) + _varint(value)


def _field_bytes(number: int, value: bytes) -> bytes:
    return _varint((number << 3) | 2) + _varint(len(value)) + value


def _field_float(number: int, value: float) -> bytes:
    return _varint((number << 3) | 5) + struct.pack("<f", value)


def _parse(data: bytes) -> dict[int, list[int | bytes]]:
    result: dict[int, list[int | bytes]] = {}
    offset = 0
    while offset < len(data):
        key, offset = _read_varint(data, offset)
        number, wire = key >> 3, key & 7
        if wire == 0:
            value, offset = _read_varint(data, offset)
        elif wire == 1:
            value = data[offset : offset + 8]
            offset += 8
        elif wire == 2:
            length, offset = _read_varint(data, offset)
            value = data[offset : offset + length]
            offset += length
        elif wire == 5:
            value = data[offset : offset + 4]
            offset += 4
        else:
            raise InnovaError(f"unsupported protobuf wire type {wire}")
        result.setdefault(number, []).append(value)
    return result


def _first(message: dict[int, list], number: int, default=None):
    values = message.get(number)
    return values[0] if values else default


def _message(message: dict[int, list], number: int) -> dict[int, list]:
    value = _first(message, number)
    return _parse(value) if isinstance(value, bytes) else {}


def _float(message: dict[int, list], number: int) -> float | None:
    value = _first(message, number)
    if isinstance(value, bytes) and len(value) == 4:
        return round(struct.unpack("<f", value)[0], 3)
    return None


def _packed_ints(value: int | bytes | None) -> set[int]:
    if isinstance(value, int):
        return {value}
    if not isinstance(value, bytes):
        return set()
    values: set[int] = set()
    offset = 0
    while offset < len(value):
        item, offset = _read_varint(value, offset)
        values.add(item)
    return values


def _mac_bytes(mac: str) -> bytes:
    try:
        return bytes.fromhex(mac.replace(":", ""))
    except ValueError as err:
        raise InnovaError(f"invalid MAC address {mac}") from err


def _mac_string(raw: bytes) -> str:
    return ":".join(f"{byte:02X}" for byte in raw)


@dataclass(slots=True)
class InnovaDevice:
    mac: str
    node_id: int
    name: str
    room: str = ""
    serial: str = ""
    product_id: int | None = None
    home_id: str = ""

    @property
    def key(self) -> str:
        return f"{self.mac}/{self.node_id}"


@dataclass(slots=True)
class HvacUnitStatus:
    power: bool = False
    setpoint: float | None = None
    cooling_setpoint: float | None = None
    heating_setpoint: float | None = None
    current_setpoint: float | None = None
    water_temp: float | None = None
    sp_min: float = 5.0
    sp_max: float = 40.0
    sp_step: float = 0.5
    boost_active: bool | None = None
    boost_minutes: int | None = None


@dataclass(slots=True)
class DeviceStatus:
    online: bool = False
    kind: str = "unknown"
    power: bool = False
    setpoint: float | None = None
    sp_min: float = 5.0
    sp_max: float = 40.0
    sp_step: float = 0.5
    room_temp: float | None = None
    humidity: float | None = None
    mode: int = 0
    mode_actual: int | None = None
    mode_capabilities: set[int] = field(default_factory=set)
    fan: int = 0
    fan_capabilities: set[int] = field(default_factory=set)
    has_flap: bool = False
    flap: bool = False
    has_silent: bool = False
    silent: bool = False
    silent_level: int | None = None
    has_erv: bool = False
    erv: bool = False
    operation_mode: int = 0
    alarm: bool = False
    alarm_code: int = 0
    outdoor_temp: float | None = None
    water_pressure: float | None = None
    load_priority: int | None = None
    active_load: int | None = None
    units: dict[str, HvacUnitStatus] = field(default_factory=dict)

    def apply_event(self, event: bytes) -> None:
        """Merge a v2 DeviceEvent, retaining fields not present in the event."""
        top = _parse(event)
        device = _message(top, 3)
        event_fields = {"ac": 2, "fancoil": 3, "thermostat": 5, "heatpump": 6}
        for kind, number in event_fields.items():
            raw = _first(device, number)
            if isinstance(raw, bytes):
                self.online = True
                if kind == "heatpump":
                    _merge_heatpump_event(self, _parse(raw))
                else:
                    _merge_comfort_event(self, kind, _parse(raw))
                return


def _parse_setpoint(raw: bytes | None) -> tuple[float | None, float, float, float]:
    if not isinstance(raw, bytes):
        return None, 5.0, 40.0, 0.5
    data = _parse(raw)
    return (
        _float(data, 1),
        _float(data, 2) or 5.0,
        _float(data, 3) or 40.0,
        _float(data, 4) or 0.5,
    )


def _parse_enum_wrapper(raw: bytes | None) -> tuple[int, int | None, set[int]]:
    if not isinstance(raw, bytes):
        return 0, None, set()
    data = _parse(raw)
    capabilities: set[int] = set()
    for item in data.get(3, []):
        capabilities |= _packed_ints(item)
    return int(_first(data, 1, 0)), _first(data, 2), capabilities


def _parse_fan_wrapper(raw: bytes | None) -> tuple[int, set[int]]:
    if not isinstance(raw, bytes):
        return 0, set()
    data = _parse(raw)
    capabilities: set[int] = set()
    for item in data.get(2, []):
        capabilities |= _packed_ints(item)
    return int(_first(data, 1, 0)), capabilities


def _parse_comfort_status(kind: str, data: dict[int, list]) -> DeviceStatus:
    status = DeviceStatus(online=True, kind=kind)
    status.alarm_code = int(_first(data, 1, 0))
    status.alarm = status.alarm_code != 0
    status.power = bool(_first(data, 2, 0))
    status.setpoint, status.sp_min, status.sp_max, status.sp_step = _parse_setpoint(
        _first(data, 3)
    )
    status.mode, status.mode_actual, status.mode_capabilities = _parse_enum_wrapper(
        _first(data, 4)
    )
    status.fan, status.fan_capabilities = _parse_fan_wrapper(_first(data, 5))
    status.has_flap = 6 in data
    status.flap = bool(_first(data, 6, 0))
    status.room_temp = _float(data, 7)
    status.humidity = _float(data, 8)
    operation_field = 10 if kind == "ac" else 9
    operation = _message(data, operation_field)
    status.operation_mode = int(_first(operation, 1, 0))
    if kind == "ac":
        status.has_erv = 9 in data
        status.erv = bool(_first(data, 9, 0))
        status.has_silent = 11 in data
        status.silent = bool(_first(data, 11, 0))
    return status


def _unit_setpoint(raw: bytes | None) -> HvacUnitStatus:
    value, minimum, maximum, step = _parse_setpoint(raw)
    return HvacUnitStatus(setpoint=value, sp_min=minimum, sp_max=maximum, sp_step=step)


def _parse_hp_unit(data: dict[int, list], dhw: bool) -> HvacUnitStatus:
    unit = _unit_setpoint(_first(data, 2))
    unit.power = bool(_first(data, 1, 0))
    if dhw:
        unit.current_setpoint = _float(data, 3)
        unit.water_temp = _float(data, 4)
        boost = _message(data, 5)
        state = _message(boost, 1)
        unit.boost_minutes = _first(state, 1)
        unit.boost_active = bool(unit.boost_minutes) if state else None
    else:
        cooling, _, _, _ = _parse_setpoint(_first(data, 3))
        unit.heating_setpoint = unit.setpoint
        unit.cooling_setpoint = cooling
        unit.current_setpoint = _float(data, 4)
        unit.water_temp = _float(data, 5)
    return unit


def _parse_heatpump_status(data: dict[int, list]) -> DeviceStatus:
    status = DeviceStatus(online=True, kind="heatpump")
    status.alarm_code = int(_first(data, 1, 0))
    status.alarm = status.alarm_code != 0
    for name, number, dhw in (("dhw", 2, True), ("zone1", 3, False), ("zone2", 4, False)):
        raw = _first(data, number)
        if isinstance(raw, bytes):
            status.units[name] = _parse_hp_unit(_parse(raw), dhw)
    status.mode, status.mode_actual, status.mode_capabilities = _parse_enum_wrapper(
        _first(data, 7)
    )
    status.active_load = _first(data, 8)
    status.outdoor_temp = _float(data, 9)
    status.water_pressure = _float(data, 10)
    silent, _, silent_caps = _parse_enum_wrapper(_first(data, 11))
    status.has_silent = bool(silent_caps) or 11 in data
    status.silent_level = silent
    status.load_priority = _first(data, 12)
    status.operation_mode = int(_first(_message(data, 13), 1, 0))
    primary = status.units.get("zone1") or status.units.get("dhw")
    if primary:
        status.power = primary.power
        status.setpoint = primary.setpoint
        status.sp_min, status.sp_max, status.sp_step = (
            primary.sp_min,
            primary.sp_max,
            primary.sp_step,
        )
        status.room_temp = primary.water_temp
    return status


def _merge_comfort_event(status: DeviceStatus, kind: str, data: dict[int, list]) -> None:
    status.kind = kind
    if 1 in data:
        status.alarm_code = int(_first(data, 1, 0))
        status.alarm = status.alarm_code != 0
    if 2 in data:
        status.power = bool(_first(data, 2, 0))
    if 3 in data:
        value, minimum, maximum, step = _parse_setpoint(_first(data, 3))
        status.setpoint = value
        status.sp_min, status.sp_max, status.sp_step = minimum, maximum, step
    if 4 in data:
        status.room_temp = _float(data, 4)
    if 5 in data:
        status.mode = int(_first(data, 5, 0))
    if 6 in data:
        status.fan = int(_first(data, 6, 0))
    if 7 in data:
        status.has_flap = True
        status.flap = bool(_first(data, 7, 0))
    operation_field = 9 if kind == "ac" else 8
    humidity_field = 10 if kind == "ac" else 9
    if operation_field in data:
        status.operation_mode = int(_first(_message(data, operation_field), 1, 0))
    if humidity_field in data:
        status.humidity = _float(data, humidity_field)
    if kind == "ac":
        if 8 in data:
            status.has_erv = True
            status.erv = bool(_first(data, 8, 0))
        if 11 in data:
            status.has_silent = True
            status.silent = bool(_first(data, 11, 0))


def _merge_heatpump_event(status: DeviceStatus, data: dict[int, list]) -> None:
    fresh = _parse_heatpump_status(data)
    # Heat-pump events contain only changed fields, so merge selectively.
    status.kind = "heatpump"
    if 1 in data:
        status.alarm, status.alarm_code = fresh.alarm, fresh.alarm_code
    for name, number in (("dhw", 2), ("zone1", 3), ("zone2", 4)):
        if number in data:
            status.units[name] = fresh.units[name]
    if 7 in data:
        status.mode, status.mode_actual = fresh.mode, fresh.mode_actual
    if 8 in data:
        status.active_load = fresh.active_load
    if 9 in data:
        status.outdoor_temp = fresh.outdoor_temp
    if 10 in data:
        status.water_pressure = fresh.water_pressure
    if 11 in data:
        status.has_silent, status.silent_level = True, fresh.silent_level
    if 12 in data:
        status.load_priority = fresh.load_priority
    if 13 in data:
        status.operation_mode = fresh.operation_mode


def _status_from_response(response: bytes, node_id: int) -> DeviceStatus:
    top = _parse(response)
    device_response = _message(top, 2)
    shared = _message(device_response, 1)
    state = _message(shared, 1)
    for entry_raw in state.get(2, []):
        if not isinstance(entry_raw, bytes):
            continue
        entry = _parse(entry_raw)
        if int(_first(entry, 1, 0)) != node_id:
            continue
        node = _message(entry, 2)
        for kind, number in (("ac", 1), ("fancoil", 2), ("thermostat", 3), ("heatpump", 4)):
            raw = _first(node, number)
            if isinstance(raw, bytes):
                data = _parse(raw)
                return _parse_heatpump_status(data) if kind == "heatpump" else _parse_comfort_status(kind, data)
    return DeviceStatus(online=False)


class InnovaApi:
    """Client for the Innova 3.x cloud."""

    def __init__(self, email: str, password: str, client: httpx.AsyncClient | None = None) -> None:
        self._email = email
        self._password = password
        self._token: str | None = None
        self.user: dict = {}
        self.homes: list[dict] = []
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient(http2=True, timeout=20.0)

    @property
    def token(self) -> str | None:
        return self._token

    async def async_close(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def async_login(self) -> str:
        try:
            response = await self._client.post(
                f"{API_BASE}/users/login",
                json={"email": self._email, "password": self._password},
            )
        except httpx.HTTPError as err:
            raise InnovaError(f"connection failed: {err}") from err
        if response.status_code in (400, 401, 403):
            raise InnovaAuthError("invalid credentials")
        if response.status_code != 200:
            raise InnovaError(f"login HTTP {response.status_code}")
        data = response.json()
        self._token = data.get("token")
        self.user = data.get("user") or {}
        if not self._token:
            raise InnovaAuthError("missing token")
        return self._token

    async def async_get_devices(self) -> list[InnovaDevice]:
        if not self._token:
            await self.async_login()
        try:
            response = await self._client.get(
                f"{API_BASE}/homes",
                headers={"Authorization": f"Bearer {self._token}"},
            )
        except httpx.HTTPError as err:
            raise InnovaError(f"connection failed: {err}") from err
        if response.status_code in (401, 403):
            raise InnovaAuthError("invalid token")
        if response.status_code != 200:
            raise InnovaError(f"homes HTTP {response.status_code}")
        self.homes = response.json()
        devices: list[InnovaDevice] = []
        for home in self.homes:
            rooms = {room.get("id"): room.get("name", "") for room in home.get("rooms") or []}
            for raw in home.get("devices") or []:
                uid = raw.get("uid") or {}
                devices.append(
                    InnovaDevice(
                        mac=raw.get("macAddress", "").upper(),
                        node_id=int(raw.get("nodeId", 0)),
                        name=raw.get("name", ""),
                        room=rooms.get(raw.get("roomId"), ""),
                        serial=raw.get("serialNumber") or "",
                        product_id=uid.get("productId"),
                        home_id=home.get("id", ""),
                    )
                )
        return devices

    def _headers(self) -> dict[str, str]:
        return {
            "authorization": f"Bearer {self._token}",
            "content-type": "application/grpc",
            "te": "trailers",
            "grpc-accept-encoding": "identity",
            "user-agent": "innova-ha/0.3",
        }

    async def _grpc_unary(self, mac: str, node_id: int, request: bytes, retry: bool = True) -> bytes:
        if not self._token:
            await self.async_login()
        body = _field_bytes(1, _mac_bytes(mac))
        if node_id:
            body += _field_varint(2, node_id)
        body += _field_bytes(3, request)
        framed = b"\0" + len(body).to_bytes(4, "big") + body
        try:
            response = await self._client.post(
                f"https://{GRPC_HOST}{M_SEND_DEVICE}",
                content=framed,
                headers=self._headers(),
            )
        except httpx.HTTPError as err:
            raise InnovaError(f"gRPC connection failed: {err}") from err
        grpc_status = response.headers.get("grpc-status")
        if response.status_code in (401, 403) or grpc_status in ("7", "16"):
            if retry:
                await self.async_login()
                return await self._grpc_unary(mac, node_id, request, False)
            raise InnovaAuthError("gRPC authorization failed")
        if response.status_code != 200 or grpc_status not in (None, "0"):
            raise InnovaError(f"gRPC status {grpc_status} (HTTP {response.status_code})")
        data = response.content
        if len(data) < 5:
            raise InnovaError("empty gRPC response")
        length = int.from_bytes(data[1:5], "big")
        message = data[5 : 5 + length]
        top = _parse(message)
        error = _first(top, 1)
        if isinstance(error, bytes):
            detail = _parse(error)
            raise InnovaError(str(_first(detail, 2, b"device error")))
        return message

    async def async_get_status(self, mac: str, node_id: int = 0) -> DeviceStatus:
        # Request.Shared.GetState. The gateway returns a map containing all nodes.
        request = _field_bytes(2, _field_bytes(1, b""))
        response = await self._grpc_unary(mac, 0, request)
        return _status_from_response(response, node_id)

    async def async_set_comfort_value(
        self, device: InnovaDevice, kind: str, field_number: int, value: int | bool | float
    ) -> None:
        kind_field = {"ac": 3, "fancoil": 5, "thermostat": 6}[kind]
        encoded = (
            _field_float(field_number, value)
            if isinstance(value, float)
            else _field_varint(field_number, int(value))
        )
        request = _field_bytes(kind_field, _field_bytes(1, encoded))
        await self._grpc_unary(device.mac, device.node_id, request)

    async def async_set_power(self, device: InnovaDevice, kind: str, on: bool) -> None:
        await self.async_set_comfort_value(device, kind, 1, on)

    async def async_set_setpoint(self, device: InnovaDevice, kind: str, celsius: float) -> None:
        await self.async_set_comfort_value(device, kind, 2, float(celsius))

    async def async_set_mode(self, device: InnovaDevice, kind: str, mode: int) -> None:
        await self.async_set_comfort_value(device, kind, 3, mode)

    async def async_set_fan(self, device: InnovaDevice, kind: str, fan: int) -> None:
        await self.async_set_comfort_value(device, kind, 4, fan)

    async def async_set_flap(self, device: InnovaDevice, kind: str, on: bool) -> None:
        await self.async_set_comfort_value(device, kind, 5, on)

    async def async_set_erv(self, device: InnovaDevice, on: bool) -> None:
        await self.async_set_comfort_value(device, "ac", 6, on)

    async def async_set_silent(self, device: InnovaDevice, on: bool) -> None:
        await self.async_set_comfort_value(device, "ac", 7, on)

    async def async_set_heatpump_unit(
        self,
        device: InnovaDevice,
        unit: str,
        *,
        power: bool | None = None,
        setpoint: float | None = None,
        cooling: bool = False,
    ) -> None:
        number = {"dhw": 1, "zone1": 2, "zone2": 3}[unit]
        fields = b""
        if power is not None:
            fields += _field_varint(1, int(power))
        if setpoint is not None:
            fields += _field_float(3 if cooling and unit != "dhw" else 2, setpoint)
        request = _field_bytes(7, _field_bytes(1, _field_bytes(number, fields)))
        await self._grpc_unary(device.mac, device.node_id, request)

    async def async_set_heatpump_mode(self, device: InnovaDevice, mode: int) -> None:
        request = _field_bytes(7, _field_bytes(1, _field_varint(4, mode)))
        await self._grpc_unary(device.mac, device.node_id, request)

    async def async_set_heatpump_option(
        self, device: InnovaDevice, field_number: int, value: int
    ) -> None:
        request = _field_bytes(7, _field_bytes(1, _field_varint(field_number, value)))
        await self._grpc_unary(device.mac, device.node_id, request)

    async def async_stream_events(
        self, home_id: str
    ) -> AsyncIterator[tuple[str, int, bytes]]:
        if not self._token:
            await self.async_login()
        try:
            home_bytes = uuid.UUID(home_id).bytes
        except ValueError as err:
            raise InnovaError(f"invalid home id {home_id}") from err
        request = _field_bytes(1, home_bytes)
        framed = b"\0" + len(request).to_bytes(4, "big") + request
        buffer = b""
        async with self._client.stream(
            "POST",
            f"https://{GRPC_HOST}{M_SUBSCRIBE}",
            content=framed,
            headers=self._headers(),
            timeout=None,
        ) as response:
            if response.status_code in (401, 403):
                raise InnovaAuthError("stream authorization failed")
            if response.status_code != 200:
                raise InnovaError(f"stream HTTP {response.status_code}")
            async for chunk in response.aiter_bytes():
                buffer += chunk
                while len(buffer) >= 5:
                    length = int.from_bytes(buffer[1:5], "big")
                    if len(buffer) < length + 5:
                        break
                    message = buffer[5 : 5 + length]
                    buffer = buffer[5 + length :]
                    top = _parse(message)
                    device = _message(top, 1)
                    raw_mac = _first(device, 1)
                    event = _first(device, 3)
                    if isinstance(raw_mac, bytes) and isinstance(event, bytes):
                        yield _mac_string(raw_mac), int(_first(device, 2, 0)), event

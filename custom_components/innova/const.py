"""Constants for the Innova integration."""
from __future__ import annotations

import logging

LOGGER = logging.getLogger(__package__)
DOMAIN = "innova"

API_BASE = "https://v2.api.innova.solutiontech.tech/app"
GRPC_HOST = "v2.grpc.innova.solutiontech.tech"
M_SEND_DEVICE = "/services.app.AppService/SendDevice"
M_SUBSCRIBE = "/services.app.AppService/SubscribeEvents"

# Innova v2 protobuf enums.
MODE_AUTO = 1
MODE_HEAT = 2
MODE_COOL = 3
MODE_DRY = 4
MODE_FAN = 5

FAN_AUTO = 1
FAN_MIN = 2
FAN_MID = 3
FAN_MAX = 4
FAN_BOOST = 5
FAN_MODES = {
    FAN_AUTO: "auto",
    FAN_MIN: "min",
    FAN_MID: "mid",
    FAN_MAX: "max",
    FAN_BOOST: "boost",
}
FAN_MODES_REV = {value: key for key, value in FAN_MODES.items()}

OPERATION_MODES = {0: "unknown", 1: "calendar", 2: "manual", 3: "antifreeze"}

CONF_EMAIL = "email"
CONF_PASSWORD = "password"
CONF_SCAN_INTERVAL = "scan_interval"
DEFAULT_SCAN_INTERVAL = 60

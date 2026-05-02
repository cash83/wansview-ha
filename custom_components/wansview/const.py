DOMAIN = "wansview"

CONF_REGION = "region"

DEFAULT_AGENT_NAME = "SM-S926B"
DEFAULT_AGENT_MODEL = "SM-S926B"
DEFAULT_APP_VERSION = "2.0.26012704"
DEFAULT_VENDOR_CODE = "WVC"
DEFAULT_LOCALE = "it"
DEFAULT_COUNTRY_CODE = "it"
DEFAULT_USER_AGENT = (
    "15; en-us; SM-S926B Build/AP3A.240905.015.A2;wansview/V2.0.26012704"
)

REGION_EU = "eu"
REGIONS = {
    REGION_EU: {
        "uac": "https://uac-eu.ajcloud.net/api",
        "sdc": "https://sdc-portal.ajcloud.net/api",
        "cam_gw": "https://cam-gw-eu02.ajcloud.net/api",
    }
}

NIGHT_MODE_OPTIONS = ["auto", "ir", "color"]
NIGHT_MODE_MAP: dict[str, str] = {"0": "auto", "1": "ir", "2": "color"}
NIGHT_MODE_REVERSE: dict[str, str] = {"auto": "0", "ir": "1", "color": "2"}

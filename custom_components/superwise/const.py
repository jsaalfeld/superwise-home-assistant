"""Integration constants."""

DOMAIN = "superwise"
DEFAULT_URL = "https://www.superwise.eu"
CONF_URL = "url"
CONF_SERIAL = "serial_number"
CONF_POWER = "rated_power_kw"
CONF_CONTROL = "enable_control"
CONF_COOKIES = "session_cookies"
IDLE = {"PS_IDLE", "PS_STOPPED", "PS_FINISHED"}
ACTIVE = {"PS_RUNNING", "PS_HOLDED", "PS_WAITSTART"}
PLATFORMS = ["sensor", "binary_sensor", "select", "button"]

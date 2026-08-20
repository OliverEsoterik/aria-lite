"""Exchange configuration for European ticker population.

Maps EODHD exchange codes to yfinance-compatible suffixes.
EURONEXT is multi-country, resolved by the Country field in API responses.
"""

EXCHANGE_CONFIG = [
    # (EODHD code, country -> suffix mapping, default suffix)
    ("LSE",      {"UK": ".L"},                  ".L"),
    ("XETRA",    {"Germany": ".DE"},             ".DE"),
    ("SW",       {"Switzerland": ".SW"},          ".SW"),
    ("BIT",      {"Italy": ".MI"},               ".MI"),
    ("STO",      {"Sweden": ".ST"},              ".ST"),
    ("HEL",      {"Finland": ".HE"},             ".HE"),
    ("CPH",      {"Denmark": ".CO"},             ".CO"),
    ("OSL",      {"Norway": ".OL"},              ".OL"),
    ("WAR",      {"Poland": ".WA"},              ".WA"),
    ("BME",      {"Spain": ".MC"},              ".MC"),
    ("IR",       {"Ireland": ".IR"},             ".IR"),
    ("EURONEXT", {
        "France": ".PA",
        "Netherlands": ".AS",
        "Belgium": ".BR",
        "Portugal": ".LS",
    }, ".PA"),
]


def get_suffix(exchange_code: str, country: str) -> str:
    """Return the yfinance suffix for an exchange code + country."""
    for code, country_map, default in EXCHANGE_CONFIG:
        if code == exchange_code:
            return country_map.get(country, default)
    return ""
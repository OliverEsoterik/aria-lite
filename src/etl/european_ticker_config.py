"""Exchange configuration for European ticker population.

Maps EODHD exchange codes to yfinance-compatible suffixes.
Each exchange is listed individually with its country mapping.
"""

EXCHANGE_CONFIG = [
    # (EODHD code, country -> suffix mapping, default suffix)
    ("LSE",      {"UK": ".L"},            ".L"),
    ("XETRA",    {"Germany": ".DE"},       ".DE"),
    ("SW",       {"Switzerland": ".SW"},    ".SW"),
    ("ST",       {"Sweden": ".ST"},        ".ST"),
    ("HE",       {"Finland": ".HE"},       ".HE"),
    ("CO",       {"Denmark": ".CO"},       ".CO"),
    ("OL",       {"Norway": ".OL"},        ".OL"),
    ("WAR",      {"Poland": ".WA"},        ".WA"),
    ("MC",       {"Spain": ".MC"},        ".MC"),
    ("IR",       {"Ireland": ".IR"},       ".IR"),
    ("PA",       {"France": ".PA"},        ".PA"),
    ("AS",       {"Netherlands": ".AS"},    ".AS"),
    ("BR",       {"Belgium": ".BR"},        ".BR"),
    ("LS",       {"Portugal": ".LS"},       ".LS"),
]


def get_suffix(exchange_code: str, country: str) -> str:
    """Return the yfinance suffix for an exchange code + country."""
    for code, country_map, default in EXCHANGE_CONFIG:
        if code == exchange_code:
            return country_map.get(country, default)
    return ""
"""ISO country codes where Anthropic (Claude / Opus) API access is supported.

Source: https://docs.anthropic.com/en/api/supported-regions
"""

from __future__ import annotations

# ISO 3166-1 alpha-2 codes matching Anthropic's published supported regions.
# Notable omissions vs many VPN menus: CN (mainland China), HK, MO, RU, BY, etc.
ANTHROPIC_SUPPORTED_REGIONS = frozenset({
    "AL", "DZ", "AD", "AO", "AG", "AR", "AM", "AU", "AT", "AZ",
    "BS", "BH", "BD", "BB", "BE", "BZ", "BJ", "BT", "BO", "BA",
    "BW", "BR", "BN", "BG", "BF", "BI", "CV", "KH", "CM", "CA",
    "TD", "CL", "CO", "KM", "CG", "CR", "CI", "HR", "CY", "CZ",
    "DK", "DJ", "DM", "DO", "EC", "EG", "SV", "GQ", "EE", "SZ",
    "FJ", "FI", "FR", "GA", "GM", "GE", "DE", "GH", "GR", "GD",
    "GT", "GN", "GW", "GY", "HT", "VA", "HN", "HU", "IS", "IN",
    "ID", "IQ", "IE", "IL", "IT", "JM", "JP", "JO", "KZ", "KE",
    "KI", "KW", "KG", "LA", "LV", "LB", "LS", "LR", "LI", "LT",
    "LU", "MG", "MW", "MY", "MV", "MT", "MH", "MR", "MU", "MX",
    "FM", "MD", "MC", "MN", "ME", "MA", "MZ", "NA", "NR", "NP",
    "NL", "NZ", "NE", "NG", "MK", "NO", "OM", "PK", "PW", "PS",
    "PA", "PG", "PY", "PE", "PH", "PL", "PT", "QA", "RO", "RW",
    "KN", "LC", "VC", "WS", "SM", "ST", "SA", "SN", "RS", "SC",
    "SL", "SG", "SK", "SI", "SB", "ZA", "KR", "ES", "LK", "SR",
    "SE", "CH", "TW", "TJ", "TZ", "TH", "TL", "TG", "TO", "TT",
    "TN", "TR", "TM", "TV", "UG", "UA", "AE", "GB", "US", "UY",
    "UZ", "VU", "VN", "ZM", "ZW",
})

# Node-name hints unlikely to exit in an Anthropic-supported region.
NAME_BLOCKLIST = (
    "香港", "HONG KONG", "HK-", "-HK", "🇭🇰",
    "澳门", "MACAU", "MACAO", "MO-", "-MO", "🇲🇴",
    "俄罗斯", "俄国", "RUSSIA", "RU-", "-RU", "🇷🇺",
    "大陆", "内地", "CHINA", "🇨🇳",
    "伊朗", "IRAN", "🇮🇷",
    "朝鲜", "KOREA-N", "🇰🇵",
    "古巴", "CUBA", "🇨🇺",
    "叙利亚", "SYRIA", "🇸🇾",
    "克里米亚", "CRIMEA",
)

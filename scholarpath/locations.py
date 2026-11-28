"""Indian locations for internships: canonical names, aliases and states (pure functions).

Job boards write the same place in many ways ("Bangalore", "Bengaluru Urban, KA",
"Madras", "Gurgaon, Haryana, India"). Every internship stores canonical city names
and the state or union territory each city belongs to, so filters, counts and the
quick location choices agree whichever spelling a source used.

Priorities: Chennai first, Bengaluru second (Kaarthik's brief). They lead every list
of places; the other hubs follow alphabetically.
"""

from __future__ import annotations

import re
import unicodedata

PRIORITY_CITIES = ("Chennai", "Bengaluru")

# Quick choices on Find Internships. "all_india" applies no location filter at all.
QUICK_PLACES = {
    "chennai": "Chennai",
    "bengaluru": "Bengaluru",
    "all_india": "All India",
    "remote": "Remote",
}

# All 28 states and 8 union territories.
STATES = (
    "Andhra Pradesh", "Arunachal Pradesh", "Assam", "Bihar", "Chhattisgarh", "Goa", "Gujarat", "Haryana",
    "Himachal Pradesh", "Jharkhand", "Karnataka", "Kerala", "Madhya Pradesh", "Maharashtra", "Manipur",
    "Meghalaya", "Mizoram", "Nagaland", "Odisha", "Punjab", "Rajasthan", "Sikkim", "Tamil Nadu", "Telangana",
    "Tripura", "Uttar Pradesh", "Uttarakhand", "West Bengal",
)
UNION_TERRITORIES = (
    "Andaman and Nicobar Islands", "Chandigarh", "Dadra and Nagar Haveli and Daman and Diu", "Delhi",
    "Jammu and Kashmir", "Ladakh", "Lakshadweep", "Puducherry",
)
STATE_ALIASES = {
    "tn": "Tamil Nadu", "ka": "Karnataka", "kar": "Karnataka", "mh": "Maharashtra", "ts": "Telangana",
    "tg": "Telangana", "ap": "Andhra Pradesh", "kl": "Kerala", "dl": "Delhi", "nct of delhi": "Delhi",
    "new delhi": "Delhi", "up": "Uttar Pradesh", "wb": "West Bengal", "gj": "Gujarat", "hr": "Haryana",
    "rj": "Rajasthan", "orissa": "Odisha", "pondicherry": "Puducherry", "j&k": "Jammu and Kashmir",
}

# Canonical city -> its state or union territory. Delhi NCR keeps its own canonical name
# (students search the region, not the municipality); its state comes from the alias used.
CITY_STATES = {
    "Chennai": "Tamil Nadu", "Coimbatore": "Tamil Nadu", "Madurai": "Tamil Nadu",
    "Tiruchirappalli": "Tamil Nadu", "Salem": "Tamil Nadu", "Tirunelveli": "Tamil Nadu", "Vellore": "Tamil Nadu",
    "Hosur": "Tamil Nadu", "Bengaluru": "Karnataka", "Mysuru": "Karnataka", "Mangaluru": "Karnataka",
    "Hubballi": "Karnataka", "Hyderabad": "Telangana", "Pune": "Maharashtra", "Mumbai": "Maharashtra",
    "Nagpur": "Maharashtra", "Nashik": "Maharashtra", "Delhi NCR": "Delhi", "Kolkata": "West Bengal",
    "Ahmedabad": "Gujarat", "Vadodara": "Gujarat", "Surat": "Gujarat", "Gandhinagar": "Gujarat",
    "Kochi": "Kerala", "Thiruvananthapuram": "Kerala", "Kozhikode": "Kerala", "Jaipur": "Rajasthan",
    "Chandigarh": "Chandigarh", "Mohali": "Punjab", "Indore": "Madhya Pradesh", "Bhopal": "Madhya Pradesh",
    "Bhubaneswar": "Odisha", "Visakhapatnam": "Andhra Pradesh", "Vijayawada": "Andhra Pradesh",
    "Lucknow": "Uttar Pradesh", "Kanpur": "Uttar Pradesh", "Guwahati": "Assam", "Patna": "Bihar",
    "Ranchi": "Jharkhand", "Dehradun": "Uttarakhand", "Goa": "Goa", "Puducherry": "Puducherry",
    "Srinagar": "Jammu and Kashmir",
}
# Spelling -> (canonical city, state when it differs from CITY_STATES).
CITY_ALIASES = {
    "chennai": ("Chennai", None), "madras": ("Chennai", None), "chennai - india": ("Chennai", None),
    "sholinganallur": ("Chennai", None), "guindy": ("Chennai", None), "taramani": ("Chennai", None),
    "ambattur": ("Chennai", None), "perungudi": ("Chennai", None), "siruseri": ("Chennai", None),
    "coimbatore": ("Coimbatore", None), "kovai": ("Coimbatore", None), "madurai": ("Madurai", None),
    "trichy": ("Tiruchirappalli", None), "tiruchirappalli": ("Tiruchirappalli", None), "salem": ("Salem", None),
    "tirunelveli": ("Tirunelveli", None), "vellore": ("Vellore", None), "hosur": ("Hosur", None),
    "bengaluru": ("Bengaluru", None), "bangalore": ("Bengaluru", None), "bengaluru urban": ("Bengaluru", None),
    "bangalore urban": ("Bengaluru", None), "blr": ("Bengaluru", None), "mysuru": ("Mysuru", None),
    "mysore": ("Mysuru", None), "mangaluru": ("Mangaluru", None), "mangalore": ("Mangaluru", None),
    "hubli": ("Hubballi", None), "hubballi": ("Hubballi", None),
    "hyderabad": ("Hyderabad", None), "secunderabad": ("Hyderabad", None), "pune": ("Pune", None),
    "mumbai": ("Mumbai", None), "bombay": ("Mumbai", None), "navi mumbai": ("Mumbai", None),
    "thane": ("Mumbai", None), "nagpur": ("Nagpur", None), "nashik": ("Nashik", None),
    "delhi": ("Delhi NCR", "Delhi"), "new delhi": ("Delhi NCR", "Delhi"), "delhi ncr": ("Delhi NCR", "Delhi"),
    "ncr": ("Delhi NCR", "Delhi"), "gurgaon": ("Delhi NCR", "Haryana"), "gurugram": ("Delhi NCR", "Haryana"),
    "faridabad": ("Delhi NCR", "Haryana"), "noida": ("Delhi NCR", "Uttar Pradesh"),
    "greater noida": ("Delhi NCR", "Uttar Pradesh"), "ghaziabad": ("Delhi NCR", "Uttar Pradesh"),
    "kolkata": ("Kolkata", None), "calcutta": ("Kolkata", None), "ahmedabad": ("Ahmedabad", None),
    "vadodara": ("Vadodara", None), "baroda": ("Vadodara", None), "surat": ("Surat", None),
    "gandhinagar": ("Gandhinagar", None), "gift city": ("Gandhinagar", None),
    "kochi": ("Kochi", None), "cochin": ("Kochi", None), "ernakulam": ("Kochi", None),
    "thiruvananthapuram": ("Thiruvananthapuram", None), "trivandrum": ("Thiruvananthapuram", None),
    "kozhikode": ("Kozhikode", None), "calicut": ("Kozhikode", None), "jaipur": ("Jaipur", None),
    "chandigarh": ("Chandigarh", None), "mohali": ("Mohali", None), "indore": ("Indore", None),
    "bhopal": ("Bhopal", None), "bhubaneswar": ("Bhubaneswar", None), "visakhapatnam": ("Visakhapatnam", None),
    "vizag": ("Visakhapatnam", None), "vijayawada": ("Vijayawada", None), "lucknow": ("Lucknow", None),
    "kanpur": ("Kanpur", None), "guwahati": ("Guwahati", None), "patna": ("Patna", None),
    "ranchi": ("Ranchi", None), "dehradun": ("Dehradun", None), "goa": ("Goa", None), "panaji": ("Goa", None),
    "puducherry": ("Puducherry", None), "pondicherry": ("Puducherry", None), "srinagar": ("Srinagar", None),
}
INDIA_WORDS = ("india", "bharat", "ind")
REMOTE_WORDS = ("remote", "work from home", "wfh", "anywhere")
HYBRID_WORDS = ("hybrid",)
ONSITE_WORDS = ("on-site", "onsite", "on site", "in-office", "in office", "office")


def _plain(text: str) -> str:
    text = unicodedata.normalize("NFKC", text or "").casefold()
    return " ".join(re.sub(r"[^\w&\- ]+", " ", text).split())


def canonical_city(name: str) -> str | None:
    """'Bangalore' -> 'Bengaluru', 'Madras' -> 'Chennai'; None for an unknown place."""
    hit = CITY_ALIASES.get(_plain(name))
    return hit[0] if hit else None


def canonical_state(name: str) -> str | None:
    plain = _plain(name)
    for state in STATES + UNION_TERRITORIES:
        if plain == state.casefold():
            return state
    return STATE_ALIASES.get(plain)


def parse_location(text: str) -> dict:
    """Read a free-text location into canonical parts.

    Returns {"cities": [...], "states": [...], "india": bool, "arrangement": str}. ``india``
    is True when any part names India, an Indian state or an Indian city. ``arrangement``
    is "remote"/"hybrid"/"onsite" only when the text says so, otherwise "unknown".
    Unknown places are ignored, never guessed.
    """
    cities: list[str] = []
    states: list[str] = []
    india = False
    plain_all = _plain(text)
    # Split on separators job boards use between places: ',', ';', '/', '|', ' - ', ' or ', ' and '.
    parts = re.split(r"\s*(?:[,;/|()]|\s-\s|\bor\b|\band\b)\s*", text or "", flags=re.IGNORECASE)
    for part in parts:
        plain = _plain(part)
        if not plain:
            continue
        if plain in INDIA_WORDS:
            india = True
            continue
        hit = CITY_ALIASES.get(plain)
        if hit is None:   # "Bengaluru Karnataka" written without a comma: try each word pair
            words = plain.split()
            for size in (3, 2, 1):
                for i in range(len(words) - size + 1):
                    hit = CITY_ALIASES.get(" ".join(words[i:i + size]))
                    if hit:
                        break
                if hit:
                    break
        if hit:
            city, state = hit
            india = True
            if city not in cities:
                cities.append(city)
            state = state or CITY_STATES.get(city)
            if state and state not in states:
                states.append(state)
            continue
        state = canonical_state(plain)
        if state:
            india = True
            if state not in states:
                states.append(state)
    arrangement = "unknown"
    if any(w in plain_all for w in HYBRID_WORDS):
        arrangement = "hybrid"
    elif any(w in plain_all for w in REMOTE_WORDS):
        arrangement = "remote"
    elif any(w in plain_all for w in ONSITE_WORDS):
        arrangement = "onsite"
    return {"cities": order_places(cities), "states": sorted(states), "india": india, "arrangement": arrangement}


def order_places(cities) -> list[str]:
    """Chennai, then Bengaluru, then every other place alphabetically."""
    def key(city: str):
        return (PRIORITY_CITIES.index(city) if city in PRIORITY_CITIES else len(PRIORITY_CITIES), city.casefold())

    return sorted(dict.fromkeys(cities), key=key)


def order_states(states) -> list[str]:
    """Tamil Nadu, then Karnataka, then the rest alphabetically."""
    first = ("Tamil Nadu", "Karnataka")

    def key(state: str):
        return (first.index(state) if state in first else len(first), state.casefold())

    return sorted(dict.fromkeys(states), key=key)


def place_text(cities: list[str], states: list[str], arrangement: str) -> str:
    """'Chennai, Tamil Nadu' / 'Remote (India)' / 'India (city not stated)' for cards and tables."""
    if cities:
        shown = ", ".join(cities[:3]) + (f" +{len(cities) - 3} more" if len(cities) > 3 else "")
        if len(states) == 1:
            shown += f", {states[0]}"
        return shown
    if states:
        return ", ".join(states)
    return "Remote (India)" if arrangement == "remote" else "India (city not stated)"

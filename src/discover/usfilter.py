"""
US-only location filter — we target jobs in the USA only; ignore other countries.

Job locations are freeform ("San Francisco, CA", "Remote, US", "London, UK",
"Bangalore, India", "Remote, EMEA"...). is_us() decides keep/drop robustly:
explicit US signal or a US state => keep; a known non-US country/region => drop;
bare "remote" with no foreign signal => keep (US company remote); empty => keep.
"""
from __future__ import annotations

import re

_US_STATES_FULL = {
    "alabama", "alaska", "arizona", "arkansas", "california", "colorado", "connecticut",
    "delaware", "florida", "georgia", "hawaii", "idaho", "illinois", "indiana", "iowa",
    "kansas", "kentucky", "louisiana", "maine", "maryland", "massachusetts", "michigan",
    "minnesota", "mississippi", "missouri", "montana", "nebraska", "nevada",
    "new hampshire", "new jersey", "new mexico", "new york", "north carolina",
    "north dakota", "ohio", "oklahoma", "oregon", "pennsylvania", "rhode island",
    "south carolina", "south dakota", "tennessee", "texas", "utah", "vermont",
    "virginia", "washington", "west virginia", "wisconsin", "wyoming",
    "district of columbia",
}
_US_ABBR = ("al|ak|az|ar|ca|co|ct|de|fl|ga|hi|id|il|in|ia|ks|ky|la|me|md|ma|mi|mn|ms|mo|"
            "mt|ne|nv|nh|nj|nm|ny|nc|nd|oh|ok|or|pa|ri|sc|sd|tn|tx|ut|vt|va|wa|wv|wi|wy|dc")

# Non-US countries / regions that mean "not a US job".
_NON_US = {
    "united kingdom", "uk", "england", "scotland", "wales", "ireland", "canada", "india",
    "germany", "france", "spain", "italy", "netherlands", "poland", "portugal", "sweden",
    "norway", "denmark", "finland", "switzerland", "austria", "belgium", "czech",
    "romania", "ukraine", "australia", "new zealand", "singapore", "japan", "china",
    "hong kong", "taiwan", "korea", "philippines", "indonesia", "malaysia", "thailand",
    "vietnam", "israel", "uae", "dubai", "saudi", "qatar", "egypt", "nigeria", "kenya",
    "south africa", "brazil", "mexico", "argentina", "chile", "colombia", "peru",
    "costa rica", "dominican", "emea", "apac", "latam", "europe", "asia", "global",
    "bengaluru", "bangalore", "hyderabad", "mumbai", "pune", "chennai", "delhi", "noida",
    "gurgaon", "london", "berlin", "paris", "toronto", "dublin", "amsterdam",
}

_RE_US = re.compile(r"\b(united states|u\.?s\.?a?|usa)\b", re.I)
_RE_US_TAIL = re.compile(r",\s*(us|u\.s\.)\b", re.I)
_RE_ABBR = re.compile(r",\s*(" + _US_ABBR + r")\b", re.I)


def is_us(location: str) -> bool:
    if not location or not location.strip():
        return True                                  # unknown location -> keep
    low = location.lower()
    if _RE_US.search(low) or _RE_US_TAIL.search(location):
        return True                                  # explicit US (even in a multi-location list)
    if _RE_ABBR.search(location):
        return True                                  # "City, ST" US form
    if any(s in low for s in _US_STATES_FULL):
        return True
    if any(c in low for c in _NON_US):
        return False                                 # known non-US country/region/city
    if "remote" in low:
        return True                                  # bare remote at a US-targeted company
    return False                                     # no US signal -> drop


def us_only(jobs) -> list:
    """Keep only US jobs."""
    return [j for j in jobs if is_us(getattr(j, "location", ""))]

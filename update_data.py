#!/usr/bin/env python3
"""
update_data.py
================

This script fetches live instability scores from the GDELT Stability Dashboard
API for every country in the world and produces two artifacts:

1. `risk_scores.json` – a JSON mapping of ISO‑3 country codes to a 0–100
   normalized crisis score.  A higher value indicates greater instability.
2. `world_crisis_map.html` – a self‑contained HTML file containing a
   Plotly choropleth map colored on the risk scores.  Countries with no
   current instability data are colored green and the scale transitions
   through yellow to dark red.

The script is designed to run in a networked environment (e.g., a GitHub
Actions runner) and requires only the standard library plus `pandas` and
`plotly`.  If those modules are not installed, they can be added to the
`requirements.txt` for your workflow.

The workflow of the script is:
1. Scrape the Trimble Country Code page to obtain a mapping of FIPS
   two‑letter country codes to ISO‑3 country codes.  The GDELT Stability
   API uses FIPS codes for the `LOC` parameter, while Plotly expects ISO‑3
   codes for coloring countries on a map.
2. For each FIPS code, query the GDELT Stability API to retrieve the
   instability timeline over the last 7 days (`NUMDAYS=7`).  The API
   returns a CSV file with a date and instability measure for each day.
   The script takes the most recent value as the current score.
3. Normalize all scores to a 0–100 range by dividing by the maximum score
   observed and multiplying by 100.  Countries with no data receive a
   score of zero.
4. Write the scores to `risk_scores.json` for consumption by other
   applications.
5. Build a choropleth map using Plotly Express, using ISO‑3 codes for
   locations and the normalized score as the color.  The `RdYlGn_r` color
   scale (reversed Red‑Yellow‑Green) ensures green for low risk and red
   for high risk.  The map is saved to `world_crisis_map.html`.

Note: This script catches exceptions for individual countries to avoid
failing the entire run if one API call fails.  Logging is printed to
standard output for transparency.
"""

import csv
import io
import json
import re
import sys
from datetime import datetime
from typing import Dict, Tuple

import requests


def fetch_country_code_mapping() -> Dict[str, str]:
    """Scrape the Trimble Country Code page to build a FIPS→ISO3 mapping.

    Returns:
        A dictionary mapping FIPS two‑letter country codes to ISO‑3 codes.
        Countries with missing FIPS or ISO3 codes are skipped.
    """
    url = "https://maps.alk.com/PCMDoc/CountryCode"
    resp = requests.get(url, timeout=30)
    resp.raise_for_status()
    html = resp.text
    # Use a regular expression to capture table rows consisting of
    # COUNTRY NAME, FIPS, ISO2, ISO3, GENC2, GENC3.  We ignore
    # ISO2/GENC columns and just take FIPS and ISO3.
    # The pattern looks for two uppercase letters (FIPS), a space, two
    # uppercase letters (ISO2 or '--'), a space, three uppercase letters
    # (ISO3).  We tolerate optional whitespace and missing values denoted by
    # '--'.
    pattern = re.compile(r"\b([A-Z]{2})\s+([A-Z]{2}|--)\s+([A-Z]{3}|--)\b")
    mapping: Dict[str, str] = {}
    for fips, iso2, iso3 in pattern.findall(html):
        if fips != "--" and iso3 != "--":
            mapping[fips] = iso3
    return mapping

# Define a fallback FIPS→ISO3 mapping for common countries.  This will be
# used if the automatic scrape of the Trimble website fails (e.g., due to
# network restrictions).  The keys are FIPS country codes and the values
# are the corresponding ISO‑3 codes.  Only a subset of countries is
# included here; users are encouraged to expand this dictionary as
# needed.
FALLBACK_FIPS_TO_ISO3: Dict[str, str] = {
    # Africa
    "AG": "DZA",  # Algeria
    "AO": "AGO",  # Angola
    "BN": "BEN",  # Benin
    "BC": "BWA",  # Botswana
    "UV": "BFA",  # Burkina Faso
    "BY": "BDI",  # Burundi
    "CM": "CMR",  # Cameroon
    "CV": "CPV",  # Cape Verde
    "CT": "CAF",  # Central African Republic
    "CD": "TCD",  # Chad
    "CN": "COM",  # Comoros
    "CG": "COD",  # Congo, Democratic Republic
    "CF": "COG",  # Congo, Republic
    "DJ": "DJI",  # Djibouti
    "EG": "EGY",  # Egypt
    "EK": "GNQ",  # Equatorial Guinea
    "ER": "ERI",  # Eritrea
    "ET": "ETH",  # Ethiopia
    "GB": "GAB",  # Gabon
    "GA": "GMB",  # Gambia
    "GH": "GHA",  # Ghana
    "GV": "GIN",  # Guinea
    "PU": "GNB",  # Guinea-Bissau
    "IV": "CIV",  # Côte d’Ivoire
    "KE": "KEN",  # Kenya
    "LT": "LSO",  # Lesotho
    "LI": "LBR",  # Liberia
    "LY": "LBY",  # Libya
    "MA": "MDG",  # Madagascar
    "MI": "MWI",  # Malawi
    "ML": "MLI",  # Mali
    "MR": "MRT",  # Mauritania
    "MP": "MUS",  # Mauritius
    "MO": "MAR",  # Morocco
    "MZ": "MOZ",  # Mozambique
    "WA": "NAM",  # Namibia
    "NG": "NER",  # Niger
    "NI": "NGA",  # Nigeria
    "RW": "RWA",  # Rwanda
    "TP": "STP",  # São Tomé and Príncipe
    "SG": "SEN",  # Senegal
    "SL": "SLE",  # Sierra Leone
    "SO": "SOM",  # Somalia
    "SF": "ZAF",  # South Africa
    "OD": "SSD",  # South Sudan
    "SU": "SDN",  # Sudan
    "TZ": "TZA",  # Tanzania
    "TO": "TGO",  # Togo
    "TS": "TUN",  # Tunisia
    "UG": "UGA",  # Uganda
    "ZA": "ZMB",  # Zambia
    "ZI": "ZWE",  # Zimbabwe
    # Asia / Pacific
    "BG": "BGD",  # Bangladesh
    "BT": "BTN",  # Bhutan
    "BX": "BRN",  # Brunei
    "BM": "MMR",  # Myanmar (Burma)
    "CB": "KHM",  # Cambodia
    "CH": "CHN",  # China
    "HK": "HKG",  # Hong Kong
    "IN": "IND",  # India
    "ID": "IDN",  # Indonesia
    "JA": "JPN",  # Japan
    "KN": "PRK",  # North Korea
    "KS": "KOR",  # South Korea
    "LA": "LAO",  # Laos
    "MY": "MYS",  # Malaysia
    "MV": "MDV",  # Maldives
    "MG": "MNG",  # Mongolia
    "NP": "NPL",  # Nepal
    "PK": "PAK",  # Pakistan
    "PS": "PLW",  # Palau
    "PP": "PNG",  # Papua New Guinea
    "RP": "PHL",  # Philippines
    "SN": "SGP",  # Singapore
    "BP": "SLB",  # Solomon Islands
    "CE": "LKA",  # Sri Lanka
    "TW": "TWN",  # Taiwan
    "TH": "THA",  # Thailand
    "VM": "VNM",  # Vietnam
    # Europe
    "AL": "ALB",  # Albania
    "AM": "ARM",  # Armenia
    "AN": "AND",  # Andorra
    "AU": "AUT",  # Austria
    "AJ": "AZE",  # Azerbaijan
    "BO": "BLR",  # Belarus
    "BE": "BEL",  # Belgium
    "BK": "BIH",  # Bosnia and Herzegovina
    "BU": "BGR",  # Bulgaria
    "HR": "HRV",  # Croatia
    "CY": "CYP",  # Cyprus
    "EZ": "CZE",  # Czech Republic
    "DA": "DNK",  # Denmark
    "EN": "EST",  # Estonia
    "FI": "FIN",  # Finland
    "FR": "FRA",  # France
    "GG": "GEO",  # Georgia
    "GM": "DEU",  # Germany
    "GI": "GIB",  # Gibraltar
    "GR": "GRC",  # Greece
    "HU": "HUN",  # Hungary
    "IC": "ISL",  # Iceland
    "EI": "IRL",  # Ireland
    "IT": "ITA",  # Italy
    "KZ": "KAZ",  # Kazakhstan
    "KG": "KGZ",  # Kyrgyzstan
    "LG": "LVA",  # Latvia
    "LS": "LIE",  # Liechtenstein
    "LH": "LTU",  # Lithuania
    "LU": "LUX",  # Luxembourg
    "MK": "MKD",  # North Macedonia
    "MT": "MLT",  # Malta
    "MD": "MDA",  # Moldova
    "MN": "MCO",  # Monaco
    "MJ": "MNE",  # Montenegro
    "NL": "NLD",  # Netherlands
    "NO": "NOR",  # Norway
    "PL": "POL",  # Poland
    "PO": "PRT",  # Portugal
    "RO": "ROU",  # Romania
    "RS": "RUS",  # Russia
    "SM": "SMR",  # San Marino
    "RI": "SRB",  # Serbia
    "LO": "SVK",  # Slovakia
    "SI": "SVN",  # Slovenia
    "SP": "ESP",  # Spain
    "SW": "SWE",  # Sweden
    "SZ": "CHE",  # Switzerland
    "TI": "TJK",  # Tajikistan
    "TU": "TUR",  # Turkey
    "TX": "TKM",  # Turkmenistan
    "UP": "UKR",  # Ukraine
    "UK": "GBR",  # United Kingdom
    "UZ": "UZB",  # Uzbekistan
    "VT": "VAT",  # Vatican City
    # Middle East
    "AF": "AFG",  # Afghanistan
    "BA": "BHR",  # Bahrain
    "IR": "IRN",  # Iran
    "IZ": "IRQ",  # Iraq
    "IS": "ISR",  # Israel
    "JO": "JOR",  # Jordan
    "KU": "KWT",  # Kuwait
    "LE": "LBN",  # Lebanon
    "MU": "OMN",  # Oman
    "QA": "QAT",  # Qatar
    "SA": "SAU",  # Saudi Arabia
    "SY": "SYR",  # Syria
    "AE": "ARE",  # United Arab Emirates
    "YM": "YEM",  # Yemen
    # North America
    "CA": "CAN",  # Canada
    "GL": "GRL",  # Greenland
    "MX": "MEX",  # Mexico
    "PR": "PRI",  # Puerto Rico
    "US": "USA",  # United States
    "VI": "VIR",  # U.S. Virgin Islands
    # Oceania
    "AQ": "ASM",  # American Samoa
    "AS": "AUS",  # Australia
    "CW": "COK",  # Cook Islands
    "FJ": "FJI",  # Fiji
    "FP": "PYF",  # French Polynesia
    "FS": "ATF",  # French Southern and Antarctic Lands
    "KR": "KIR",  # Kiribati
    "RM": "MHL",  # Marshall Islands
    "FM": "FSM",  # Micronesia
    "NR": "NRU",  # Nauru
    "NC": "NCL",  # New Caledonia
    "NZ": "NZL",  # New Zealand
    "NE": "NIU",  # Niue
    "NF": "NFK",  # Norfolk Island
    "PC": "PCN",  # Pitcairn Islands
    "WS": "WSM",  # Samoa
    "TL": "TKL",  # Tokelau
    "TN": "TON",  # Tonga
    "TV": "TUV",  # Tuvalu
    "NH": "VUT",  # Vanuatu
    "WF": "WLF",  # Wallis and Futuna
    # South America & Caribbean
    "AV": "AIA",  # Anguilla
    "AC": "ATG",  # Antigua and Barbuda
    "AR": "ARG",  # Argentina
    "AA": "ABW",  # Aruba
    "BF": "BHS",  # Bahamas
    "BB": "BRB",  # Barbados
    "BH": "BLZ",  # Belize
    "BD": "BMU",  # Bermuda
    "BL": "BOL",  # Bolivia
    "BR": "BRA",  # Brazil
    "CJ": "CYM",  # Cayman Islands
    "CI": "CHL",  # Chile
    "CO": "COL",  # Colombia
    "CS": "CRI",  # Costa Rica
    "CU": "CUB",  # Cuba
    "GJ": "GRD",  # Grenada
    "GP": "GLP",  # Guadeloupe
    "HA": "HTI",  # Haiti
    "HO": "HND",  # Honduras
    "JM": "JAM",  # Jamaica
    "MB": "MTQ",  # Martinique
    "MH": "MSR",  # Montserrat
    "NU": "NIC",  # Nicaragua
    "PM": "PAN",  # Panama
    "PA": "PRY",  # Paraguay
    "PE": "PER",  # Peru
    "ST": "LCA",  # Saint Lucia
    "VC": "VCT",  # Saint Vincent and the Grenadines
    "SC": "KNA",  # Saint Kitts and Nevis
    "RN": "MAF",  # Saint Martin (French part)
    "TD": "TTO",  # Trinidad and Tobago
    "TK": "TCA",  # Turks and Caicos Islands
    "UY": "URY",  # Uruguay
    "VE": "VEN",  # Venezuela
    "VG": "VGB",  # British Virgin Islands
}


def fetch_instability_score(fips_code: str, numdays: int = 7) -> float:
    """Fetch the most recent instability score for a given FIPS country code.

    The GDELT Stability API returns a CSV with a date and value per row.  We
    request a daily timeline for the past `numdays` days and take the last
    value.  See the GDELT API documentation for details【911104533239858†L20-L23】【911104533239858†L58-L63】.

    Args:
        fips_code: Two‑letter FIPS country code used by the GDELT API.
        numdays: Number of days to request in the timeline (maximum 7 for
                 15‑minute resolution or 180 for daily resolution).

    Returns:
        The most recent instability score as a float.  Returns 0.0 if the
        request fails or the CSV cannot be parsed.
    """
    api_url = (
        "https://api.gdeltproject.org/api/v1/dash_stabilitytimeline/"
        "dash_stabilitytimeline"
        f"?LOC={fips_code}&VAR=instability&OUTPUT=csv&TIMERES=day&NUMDAYS={numdays}"
    )
    try:
        resp = requests.get(api_url, timeout=30)
        resp.raise_for_status()
    except Exception as exc:
        print(f"Error fetching data for {fips_code}: {exc}", file=sys.stderr)
        return 0.0
    csv_text = resp.text.strip()
    # Some API responses include HTML if the country code is invalid.  Ensure
    # we have CSV by checking for comma separation in the first line.
    if "," not in csv_text.splitlines()[0]:
        return 0.0
    reader = csv.reader(io.StringIO(csv_text))
    # Skip header if present; header is usually DATE,VALUE
    rows = list(reader)
    # The last row should contain the most recent date/value pair
    if not rows:
        return 0.0
    # Skip header if the first row contains non-numeric value in second column
    start_idx = 0
    if rows[0] and not rows[0][1].replace(".", "", 1).isdigit():
        start_idx = 1
    rows = rows[start_idx:]
    if not rows:
        return 0.0
    last_row = rows[-1]
    try:
        value = float(last_row[1])
        return value
    except Exception:
        return 0.0


def normalize_scores(raw_scores: Dict[str, float]) -> Dict[str, int]:
    """Normalize raw instability scores to a 0–100 integer scale.

    Args:
        raw_scores: Mapping of ISO‑3 country codes to raw instability scores.

    Returns:
        Mapping of ISO‑3 codes to integer scores between 0 and 100 inclusive.
    """
    if not raw_scores:
        return {}
    max_score = max(raw_scores.values())
    if max_score <= 0:
        return {iso: 0 for iso in raw_scores}
    normalized: Dict[str, int] = {}
    for iso3, score in raw_scores.items():
        normalized_value = int(round((score / max_score) * 100)) if score > 0 else 0
        normalized[iso3] = normalized_value
    return normalized


def build_choropleth_map(scores: Dict[str, int], output_path: str) -> None:
    """Generate a Plotly choropleth map from normalized scores and save as HTML.

    Args:
        scores: Mapping of ISO‑3 codes to normalized scores (0–100).
        output_path: Path to write the HTML file.
    """
    import pandas as pd
    import plotly.express as px

    # Build a DataFrame with ISO‑3 codes and scores.  Countries not present
    # receive a score of 0.  Plotly will treat missing scores as NaN and color
    # them according to the lowest value on the scale (green).
    df = pd.DataFrame({"iso3": list(scores.keys()), "score": list(scores.values())})
    # Create the choropleth
    fig = px.choropleth(
        df,
        locations="iso3",
        color="score",
        color_continuous_scale="RdYlGn_r",
        range_color=(0, 100),
        locationmode="ISO-3",
        title="World Crisis Map – 7‑Day Instability Score",
        labels={"score": "Instability (0–100)"},
    )
    fig.update_layout(
        margin=dict(l=0, r=0, t=50, b=0),
        coloraxis_colorbar=dict(
            title="Instability",
            ticks="outside",
            tickvals=[0, 25, 50, 75, 100],
            ticktext=["Low", "Moderate", "High", "Very High", "Extreme"],
        ),
    )
    fig.write_html(output_path, include_plotlyjs="cdn")


def main() -> None:
    # Step 1: Build mapping of FIPS→ISO3 codes
    print("Fetching country code mapping…")
    try:
        fips_to_iso3 = fetch_country_code_mapping()
        if not fips_to_iso3:
            raise ValueError("No country codes parsed")
        print(f"Fetched {len(fips_to_iso3)} country codes")
    except Exception as exc:
        # Fall back to the embedded mapping if fetching fails
        print(f"Failed to fetch country codes from remote source: {exc}", file=sys.stderr)
        fips_to_iso3 = FALLBACK_FIPS_TO_ISO3.copy()
        print(f"Using fallback mapping with {len(fips_to_iso3)} country codes")

    # Step 2: Fetch raw instability scores for each FIPS code
    raw_scores: Dict[str, float] = {}
    for fips, iso3 in fips_to_iso3.items():
        # Skip pseudo codes (e.g., 'Bonaire') if iso3 is unknown
        print(f"Fetching instability for {fips} ({iso3})…")
        score = fetch_instability_score(fips)
        raw_scores[iso3] = score

    # Step 3: Normalize scores to 0–100
    print("Normalizing scores…")
    normalized_scores = normalize_scores(raw_scores)

    # Step 4: Write JSON
    with open("risk_scores.json", "w") as jf:
        json.dump(normalized_scores, jf, indent=2)
    print("Wrote risk_scores.json")

    # Step 5: Generate choropleth
    print("Building choropleth map…")
    build_choropleth_map(normalized_scores, "world_crisis_map.html")
    print("Wrote world_crisis_map.html")


if __name__ == "__main__":
    main()
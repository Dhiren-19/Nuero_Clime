"""
Heat index and risk-band derivation (TRD 2.1 "DERIVE" stage).

Uses a simplified WBGT-style heat index (a well-known Rothfusz-style
regression, the same family used by the US NWS) rather than the full
psychrometric WBGT calculation, since we don't have wind/radiation
observations for every hex at every horizon. This is explicitly a
"WBGT-lite" per TRD 2.1's DERIVE box.

Risk bands follow PRD 1.4's accessibility requirement: every band has a
color AND an icon AND a text label, never color alone.
"""
from dataclasses import dataclass


@dataclass(frozen=True)
class RiskBand:
    key: str
    label: str
    color: str  # colorblind-safe (Okabe-Ito inspired) palette
    icon: str  # simple text/emoji glyph as a stand-in for a real icon asset


RISK_BANDS = [
    RiskBand("safe", "Safe", "#0072B2", "🟦"),
    RiskBand("caution", "Caution", "#E69F00", "🟧"),
    RiskBand("danger", "Danger", "#D55E00", "🟥"),
    RiskBand("extreme", "Extreme", "#7A0000", "⬛"),
]


def heat_index_c(temp_c: float, humidity_pct: float) -> float:
    """
    Simplified apparent-temperature ("feels like") heat index in Celsius,
    adapted from the NWS Rothfusz regression (originally in Fahrenheit).
    Falls back to plain air temperature below 27°C, where the heat-index
    regression is not considered valid/meaningful.
    """
    if temp_c < 27 or humidity_pct <= 0:
        return round(temp_c, 2)

    t_f = temp_c * 9 / 5 + 32
    rh = humidity_pct

    hi_f = (
        -42.379
        + 2.04901523 * t_f
        + 10.14333127 * rh
        - 0.22475541 * t_f * rh
        - 0.00683783 * t_f * t_f
        - 0.05481717 * rh * rh
        + 0.00122874 * t_f * t_f * rh
        + 0.00085282 * t_f * rh * rh
        - 0.00000199 * t_f * t_f * rh * rh
    )
    hi_c = (hi_f - 32) * 5 / 9
    # Heat index should not read cooler than actual temperature.
    return round(max(hi_c, temp_c), 2)


def risk_band_for(heat_index: float) -> RiskBand:
    """
    Threshold bands loosely aligned to NWS/IMD heat-index caution levels,
    adapted for Indian urban contexts where 40-45°C heat index is common
    in summer and needs its own "extreme" tier above the NWS scale.
    """
    if heat_index < 33:
        return RISK_BANDS[0]
    if heat_index < 41:
        return RISK_BANDS[1]
    if heat_index < 47:
        return RISK_BANDS[2]
    return RISK_BANDS[3]


def risk_band_dict(heat_index: float) -> dict:
    band = risk_band_for(heat_index)
    return {"key": band.key, "label": band.label, "color": band.color, "icon": band.icon}

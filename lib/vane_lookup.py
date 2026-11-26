# Measured on this board's specific vane (2026-11-22), not datasheet values.
_VANE_CALIBRATION = sorted(
    [
        (60300, "N"),
        (56744, "NE"),
        (50290, "E"),
        (29599, "SE"),
        (6298, "S"),
        (12025, "SW"),
        (18646, "W"),
        (40485, "NW"),
    ]
)

_RAW_VALUES = [raw for raw, _ in _VANE_CALIBRATION]
_DIRECTIONS = [direction for _, direction in _VANE_CALIBRATION]
_THRESHOLDS = [
    (_RAW_VALUES[i] + _RAW_VALUES[i + 1]) // 2 for i in range(len(_RAW_VALUES) - 1)
]


def raw_to_direction(raw):
    for threshold, direction in zip(_THRESHOLDS, _DIRECTIONS):
        if raw <= threshold:
            return direction
    return _DIRECTIONS[-1]

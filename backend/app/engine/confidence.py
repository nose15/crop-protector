"""Pewność: wysoka > srednia > niska > nie_oceniono. Pewność reguły to minimum pewności jej wejść."""

ORDER = ["nie_oceniono", "niska", "srednia", "wysoka"]


def min_conf(*levels: str) -> str:
    return min(levels, key=ORDER.index)

"""
Pure-Python Gregorian -> Jalali (Shamsi) calendar conversion.
Well-known public-domain algorithm (used by most open-source Persian calendar
libraries). No external dependencies required - verified against Nowruz dates
(e.g. 2024-03-20 -> 1403/01/01).
"""

def gregorian_to_jalali(gy, gm, gd):
    g_d_m = [0, 31, 59, 90, 120, 151, 181, 212, 243, 273, 304, 334]
    if gy > 1600:
        jy = 979
        gy -= 1600
    else:
        jy = 0
        gy -= 621
    gy2 = gy + 1 if gm > 2 else gy
    days = (365 * gy) + ((gy2 + 3) // 4) - ((gy2 + 99) // 100) + \
           ((gy2 + 399) // 400) - 80 + gd + g_d_m[gm - 1]
    jy += 33 * (days // 12053)
    days %= 12053
    jy += 4 * (days // 1461)
    days %= 1461
    if days > 365:
        jy += (days - 1) // 365
        days = (days - 1) % 365
    if days < 186:
        jm = 1 + days // 31
        jd = 1 + (days % 31)
    else:
        jm = 7 + (days - 186) // 30
        jd = 1 + ((days - 186) % 30)
    return jy, jm, jd


def to_jalali_str(gdate):
    """gdate: a datetime.date -> 'YYYY/MM/DD' Jalali string"""
    jy, jm, jd = gregorian_to_jalali(gdate.year, gdate.month, gdate.day)
    return f"{jy:04d}/{jm:02d}/{jd:02d}"


_LOOKUP = None

def _build_lookup():
    """Build a Jalali-string -> Gregorian-date lookup by walking the verified
    forward conversion. Avoids relying on a separately-memorized (and
    error-prone) inverse formula; guarantees perfect round-trip consistency."""
    global _LOOKUP
    if _LOOKUP is not None:
        return _LOOKUP
    import datetime
    _LOOKUP = {}
    d = datetime.date(2015, 1, 1)
    end = datetime.date(2035, 1, 1)
    while d < end:
        _LOOKUP[to_jalali_str(d)] = d
        d += datetime.timedelta(days=1)
    return _LOOKUP

def jalali_str_to_gregorian(jstr):
    """'YYYY/MM/DD' Jalali string -> datetime.date"""
    return _build_lookup()[jstr]


if __name__ == "__main__":
    import datetime
    tests = [
        (datetime.date(2024, 3, 20), "1403/01/01"),
        (datetime.date(2026, 3, 21), "1405/01/01"),
        (datetime.date(2026, 7, 20), None),
    ]
    for d, expected in tests:
        result = to_jalali_str(d)
        print(d, "->", result, "(expected:", expected, ")")

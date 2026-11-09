import time


def time_float():
    """Devuelve marca de tiempo epoch en segundos con resolución de microsegundos como string."""
    if hasattr(time, "time_ns"):
        t_ns_str = str(time.time_ns())
        if len(t_ns_str) > 9:
            return t_ns_str[:-9] + "." + t_ns_str[-9:-3]
    return "{:.6f}".format(time.time())


def ticks_ms():
    if hasattr(time, "ticks_ms"):
        return time.ticks_ms()
    return int(time.monotonic() * 1000)


def ticks_us():
    if hasattr(time, "ticks_us"):
        return time.ticks_us()
    return int(time.monotonic() * 1_000_000)


def ticks_add(t, delta):
    if hasattr(time, "ticks_add"):
        return time.ticks_add(t, delta)
    return t + delta


def ticks_diff(t1, t2):
    if hasattr(time, "ticks_diff"):
        return time.ticks_diff(t1, t2)
    return t1 - t2


def sleep_ms(ms):
    if hasattr(time, "sleep_ms"):
        time.sleep_ms(ms)
    else:
        time.sleep(ms / 1000.0)


def _is_leap_year(year):
    return (year % 4 == 0 and year % 100 != 0) or (year % 400 == 0)


def _days_before_year(year, base_year=1970):
    days = 0
    if year >= base_year:
        for y in range(base_year, year):
            days += 366 if _is_leap_year(y) else 365
    else:
        for y in range(year, base_year):
            days -= 366 if _is_leap_year(y) else 365
    return days


_DAYS_IN_MONTH = (31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31)


def parse_iso8601_utc(ts_str):
    """
    Convierte una fecha ISO-8601 (ej. '2026-11-01T20:00:00Z' o con offset '+00:00'/'-05:00')
    a segundos epoch compatibles con `time.time()` de la plataforma actual (Unix 1970 o MicroPython).
    Retorna float o None si el formato no es válido.
    """
    if not isinstance(ts_str, str):
        return None
    s = ts_str.strip()
    if not s:
        return None

    # Detectar epoch base de la plataforma (1970 en CPython / RP2 MicroPython moderno)
    try:
        base_year = time.gmtime(0)[0]
    except Exception:
        base_year = 1970

    tz_offset_s = 0
    if s.endswith("Z") or s.endswith("z"):
        s = s[:-1]
    elif len(s) >= 25 and s[-6] in ("+", "-") and s[-3] == ":":
        sign = 1 if s[-6] == "+" else -1
        try:
            tz_h = int(s[-5:-3])
            tz_m = int(s[-2:])
            tz_offset_s = sign * (tz_h * 3600 + tz_m * 60)
            s = s[:-6]
        except ValueError:
            return None

    sep = "T" if "T" in s else ("t" if "t" in s else (" " if " " in s else None))
    if sep is None:
        return None

    try:
        date_part, time_part = s.split(sep, 1)
        y_s, m_s, d_s = date_part.split("-")
        year, month, day = int(y_s), int(m_s), int(d_s)
        if not (1 <= month <= 12):
            return None

        t_fields = time_part.split(":")
        if len(t_fields) < 2:
            return None
        hour = int(t_fields[0])
        minute = int(t_fields[1])
        sec = float(t_fields[2]) if len(t_fields) >= 3 else 0.0

        max_day = _DAYS_IN_MONTH[month - 1] + (1 if month == 2 and _is_leap_year(year) else 0)
        if not (1 <= day <= max_day):
            return None
        if not (0 <= hour <= 23 and 0 <= minute <= 59 and 0.0 <= sec < 61.0):
            return None

        days = _days_before_year(year, base_year=base_year)
        for m in range(1, month):
            days += _DAYS_IN_MONTH[m - 1] + (1 if m == 2 and _is_leap_year(year) else 0)
        days += day - 1

        total_seconds = days * 86400 + hour * 3600 + minute * 60 + sec - tz_offset_s
        return float(total_seconds)
    except Exception:
        return None


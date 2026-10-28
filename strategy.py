
"""
strategy.py - Moteur de signaux TRADER AI PRO.

Analyse les bougies et génère des signaux indicatifs.
Ce fichier ne passe aucun ordre et n'effectue aucun accès réseau.

ATTENTION :
PIP_SIZE est provisoire et doit être vérifié pour chaque indice
avant toute utilisation en réel. Le code ne garantit pas que
0.01 corresponde à un pip sur tous les indices Deriv.
"""

import datetime as dt

# ----------------------------------------------------------------------
# PARAMÈTRES
# ----------------------------------------------------------------------

TRIGGER_TFS = ["H1", "H2"]

SWING_N = 5
MAX_SWEEP_ATR = 0.5

# SL : marge fixe provisoire de 20 pips autour de la zone.
PIP_SIZE = 0.01
SL_BUFFER_PIPS = 20

# TP : ratio risque/rendement de 1:3.
RR = 3.0

# Filtres de risque conservés.
MIN_RISK_ATR = 0.3
MAX_RISK_ATR = 3.0

STALE_R = 0.5
STALE_BARS = 4

ZONE_TOUCH_ATR = 0.2
SR_TOL_ATR = 0.3
IMPULSE_ATR = 1.5
BASE_ATR = 0.6

USE_BIAS_FILTER = False
USE_TARGET_FILTER = False

MIN_TRIGGER_CANDLES = 400
MIN_ZONE_CANDLES = 200
ZONE_LOOKBACK = 200

ZT_SR, ZT_SD, ZT_OB = 1, 2, 3

ZONE_NAMES = {
    ZT_SR: "Support/Résistance",
    ZT_SD: "Offre/Demande",
    ZT_OB: "Order Block",
}


# ----------------------------------------------------------------------
# CONVERSION DES BOUGIES
# Les séries utilisées par la stratégie sont classées de la plus
# récente à la plus ancienne.
# ----------------------------------------------------------------------

def to_series(candles):
    """Convertit les bougies Deriv en séries récentes -> anciennes."""
    out = [
        {
            "t": int(c["epoch"]),
            "o": float(c["open"]),
            "h": float(c["high"]),
            "l": float(c["low"]),
            "c": float(c["close"]),
        }
        for c in candles
    ]
    out.reverse()
    return out


def atr_at(r, i, period=14):
    """Calcule l'ATR à partir de la bougie i."""
    if i + period >= len(r):
        return 0.0

    total = 0.0

    for k in range(i, i + period):
        total += max(
            r[k]["h"] - r[k]["l"],
            abs(r[k]["h"] - r[k + 1]["c"]),
            abs(r[k]["l"] - r[k + 1]["c"]),
        )

    return total / period


def is_swing_high(r, i, n_side):
    if i < n_side or i + n_side >= len(r):
        return False

    high = r[i]["h"]

    for k in range(1, n_side + 1):
        if r[i - k]["h"] >= high or r[i + k]["h"] >= high:
            return False

    return True


def is_swing_low(r, i, n_side):
    if i < n_side or i + n_side >= len(r):
        return False

    low = r[i]["l"]

    for k in range(1, n_side + 1):
        if r[i - k]["l"] <= low or r[i + k]["l"] <= low:
            return False

    return True


def decimals_of(r):
    """Déduit un nombre de décimales d'affichage à partir des prix."""
    decimals = 2

    for candle in r[:50]:
        for key in ("o", "h", "l", "c"):
            value = repr(round(float(candle[key]), 6))

            if "e" in value or "." not in value:
                continue

            decimals = max(
                decimals,
                len(value.split(".")[1].rstrip("0")),
            )

    return min(decimals, 5)


def display_name(symbol):
    if symbol.startswith("R_"):
        return "Volatility %s Index" % symbol[2:]

    if symbol.startswith("1HZ") and symbol.endswith("V"):
        return "Volatility %s (1s) Index" % symbol[3:-1]

    return symbol


def to_weekly(d1):
    """Reconstruit les bougies W1 à partir des bougies D1."""
    buckets = {}

    for candle in reversed(d1):
        day = dt.datetime.fromtimestamp(
            candle["t"], dt.timezone.utc
        ).date()

        monday = day - dt.timedelta(days=day.weekday())
        bucket = buckets.get(monday)

        if bucket is None:
            buckets[monday] = {
                "t": candle["t"],
                "o": candle["o"],
                "h": candle["h"],
                "l": candle["l"],
                "c": candle["c"],
            }
        else:
            bucket["h"] = max(bucket["h"], candle["h"])
            bucket["l"] = min(bucket["l"], candle["l"])
            bucket["c"] = candle["c"]

    current_monday = dt.datetime.now(dt.timezone.utc).date()
    current_monday -= dt.timedelta(days=current_monday.weekday())

    weeks = [
        buckets[key]
        for key in sorted(buckets)
        if key != current_monday
    ]

    weeks.reverse()
    return weeks


# ----------------------------------------------------------------------
# ZONES DE SUPPORT, RÉSISTANCE, OFFRE, DEMANDE ET ORDER BLOCKS
#
# Format d'une zone :
# (bas, haut, type, direction, unité de temps)
#
# direction : +1 = support/demande ; -1 = résistance/offre
# ----------------------------------------------------------------------

def zone_broken(r, frm, lo, hi, direction):
    for k in range(frm, -1, -1):
        if direction > 0 and r[k]["c"] < lo:
            return True

        if direction < 0 and r[k]["c"] > hi:
            return True

    return False


def build_sr(r, min_touches, tf):
    zones = []
    n = len(r)
    atr = atr_at(r, 0)

    if atr <= 0:
        return zones

    tolerance = SR_TOL_ATR * atr
    points = []

    for i in range(3, n - 3):
        if is_swing_high(r, i, 3):
            points.append((r[i]["h"], -1))
        elif is_swing_low(r, i, 3):
            points.append((r[i]["l"], 1))

    for a, (level, kind) in enumerate(points):
        touches = 1 + sum(
            1
            for b, (level2, _) in enumerate(points)
            if b != a and abs(level - level2) <= tolerance
        )

        if touches >= min_touches:
            zones.append(
                (
                    level - tolerance / 2,
                    level + tolerance / 2,
                    ZT_SR,
                    kind,
                    tf,
                )
            )

    return zones


def build_sdob(r, tf):
    """Construit des zones candidates d'offre/demande et d'OB."""
    zones = []
    n = len(r)

    for i in range(0, n - 30):
        atr = atr_at(r, i + 1)

        if atr <= 0:
            continue

        if abs(r[i]["c"] - r[i]["o"]) < IMPULSE_ATR * atr:
            continue

        direction = 1 if r[i]["c"] > r[i]["o"] else -1

        # Vérifie si l'impulsion dépasse la structure précédente.
        broke_structure = True

        for k in range(i + 1, i + 11):
            if direction > 0 and r[i]["c"] <= r[k]["h"]:
                broke_structure = False
                break

            if direction < 0 and r[i]["c"] >= r[k]["l"]:
                broke_structure = False
                break

        # Recherche de la dernière bougie opposée à l'impulsion.
        if broke_structure:
            for j in range(i + 1, i + 6):
                opposite = (
                    direction > 0
                    and r[j]["c"] < r[j]["o"]
                ) or (
                    direction < 0
                    and r[j]["c"] > r[j]["o"]
                )

                if opposite:
                    if not zone_broken(
                        r, i - 1, r[j]["l"], r[j]["h"], direction
                    ):
                        zones.append(
                            (
                                r[j]["l"],
                                r[j]["h"],
                                ZT_OB,
                                direction,
                                tf,
                            )
                        )
                    break

        # Recherche d'une base d'une à trois bougies.
        count = 0
        lo = float("inf")
        hi = float("-inf")

        while count < 3:
            candle = r[i + 1 + count]

            if candle["h"] - candle["l"] >= BASE_ATR * atr:
                break

            lo = min(lo, candle["l"])
            hi = max(hi, candle["h"])
            count += 1

        if count >= 1 and not zone_broken(
            r, i - 1, lo, hi, direction
        ):
            zones.append((lo, hi, ZT_SD, direction, tf))

    return zones


def build_zones(h4, d1):
    """Construit les zones W1, D1 et H4."""
    zones = []

    w1 = to_weekly(d1)
    d1z = d1[:ZONE_LOOKBACK]
    h4z = h4[:ZONE_LOOKBACK]

    if len(w1) >= 30:
        zones += build_sr(w1, 1, "W1")

    if len(d1z) >= MIN_ZONE_CANDLES:
        zones += build_sr(d1z, 2, "D1")
        zones += build_sdob(d1z, "D1")

    if len(h4z) >= MIN_ZONE_CANDLES:
        zones += build_sr(h4z, 2, "H4")
        zones += build_sdob(h4z, "H4")

    return zones


def trend_bias(r):
    """+1 haussier ; -1 baissier ; 0 indéterminé."""
    if len(r) < 60:
        return 0

    k = 2.0 / 51.0
    ema = r[-1]["c"]

    for i in range(len(r) - 2, -1, -1):
        ema = r[i]["c"] * k + ema * (1.0 - k)

    return 1 if r[0]["c"] > ema else -1


# ----------------------------------------------------------------------
# DÉTECTION DU BALAYAGE
# rs[0] représente la bougie de balayage.
# -1 = SELL ; +1 = BUY ; 0 = aucun balayage
# ----------------------------------------------------------------------

def detect_sweep(rs, atr):
    n = len(rs)
    candle = rs[0]

    for i in range(SWING_N + 1, n - SWING_N - 1):
        if is_swing_high(rs, i, SWING_N):
            level = rs[i]["h"]

            if (
                candle["h"] > level
                and candle["c"] < level
                and candle["h"] - level <= MAX_SWEEP_ATR * atr
            ):
                if all(rs[k]["h"] <= level for k in range(1, i)):
                    return -1, level

    for i in range(SWING_N + 1, n - SWING_N - 1):
        if is_swing_low(rs, i, SWING_N):
            level = rs[i]["l"]

            if (
                candle["l"] < level
                and candle["c"] > level
                and level - candle["l"] <= MAX_SWEEP_ATR * atr
            ):
                if all(rs[k]["l"] >= level for k in range(1, i)):
                    return 1, level

    return 0, 0.0


def has_opposite_liquidity(rs, direction, entry, tp):
    """Vérifie l'existence éventuelle d'une liquidité opposée."""
    n = len(rs)

    for i in range(SWING_N + 1, n - SWING_N - 1):
        if direction < 0 and is_swing_low(rs, i, SWING_N):
            level = rs[i]["l"]

            if (
                tp <= level < entry
                and all(rs[k]["l"] > level for k in range(0, i))
            ):
                return True

        if direction > 0 and is_swing_high(rs, i, SWING_N):
            level = rs[i]["h"]

            if (
                entry < level <= tp
                and all(rs[k]["h"] < level for k in range(0, i))
            ):
                return True

    return False


# ----------------------------------------------------------------------
# ÉVALUATION D'UN SIGNAL
# ----------------------------------------------------------------------

def evaluate_bar(tf, r, s, get_zones, price_now, bias, symbol):
    """Retourne un signal ou None, ainsi qu'une note de rejet éventuelle."""
    rs = r[s:]
    atr = atr_at(rs, 0)

    if atr <= 0:
        return None, None

    direction, level = detect_sweep(rs, atr)

    if direction == 0:
        return None, None

    candle = rs[0]
    when = dt.datetime.fromtimestamp(
        candle["t"], dt.timezone.utc
    ).strftime("%d/%m %H:%M")

    sens = "VENTE" if direction < 0 else "ACHAT"

    depth = (
        candle["h"] - level
        if direction < 0
        else level - candle["l"]
    )

    # Vérifie que la mèche de balayage touche une zone cohérente.
    wick_lo, wick_hi = (
        (level, candle["h"])
        if direction < 0
        else (candle["l"], level)
    )

    margin = ZONE_TOUCH_ATR * atr
    touched = []
    reaction_zones = []

    for lo, hi, ztype, zdir, ztf in get_zones():
        if (
            zdir == direction
            and hi >= wick_lo - margin
            and lo <= wick_hi + margin
        ):
            reaction_zones.append((lo, hi, ztype, zdir, ztf))

            if (ztype, ztf) not in touched:
                touched.append((ztype, ztf))

    if not reaction_zones:
        return None, (
            "balayage %s %s %s rejeté : "
            "aucune zone du bon côté ne touche la mèche"
        ) % (sens, tf, when)

    # Sélectionne la zone de référence pour le calcul du SL.
    # SELL : limite haute la plus éloignée.
    # BUY : limite basse la plus éloignée.
    if direction < 0:
        reaction_zone = max(reaction_zones, key=lambda z: z[1])
    else:
        reaction_zone = min(reaction_zones, key=lambda z: z[0])

    reaction_lo, reaction_hi, reaction_type, reaction_dir, reaction_tf = (
        reaction_zone
    )

    # --------------------------------------------------------------
    # ENTRÉE, SL À 20 PIPS DE LA ZONE, TP À 1:3
    # --------------------------------------------------------------

    entry = candle["c"]
    sl_buffer = SL_BUFFER_PIPS * PIP_SIZE

    if direction < 0:  # SELL
        sl = reaction_hi + sl_buffer
        risk = sl - entry
        tp = entry - RR * risk
    else:              # BUY
        sl = reaction_lo - sl_buffer
        risk = entry - sl
        tp = entry + RR * risk

    zone_lo = reaction_lo
    zone_hi = reaction_hi

    if (
        risk <= 0
        or risk < MIN_RISK_ATR * atr
        or risk > MAX_RISK_ATR * atr
    ):
        return None, (
            "balayage %s %s %s rejeté : risque hors limites (%.2f ATR)"
        ) % (sens, tf, when, risk / atr)

    # --------------------------------------------------------------
    # ANNULATION DES SETUPS DEVENUS INVALIDES OU TROP TARDIFS
    # --------------------------------------------------------------

    newer = r[:s]

    if direction < 0:
        if any(c["c"] > candle["h"] for c in newer):
            return None, (
                "setup %s %s %s annulé : clôture au-dessus de la mèche"
            ) % (sens, tf, when)

        if any(c["h"] >= sl for c in newer):
            return None, (
                "setup %s %s %s annulé : stop déjà touché"
            ) % (sens, tf, when)

        if (
            any(c["l"] <= entry - STALE_R * risk for c in newer)
            or price_now <= entry - STALE_R * risk
        ):
            return None, (
                "setup %s %s %s annulé : le prix a déjà trop avancé"
            ) % (sens, tf, when)

        if price_now > level:
            return None, (
                "setup %s %s %s annulé : prix revenu au-dessus "
                "du niveau balayé"
            ) % (sens, tf, when)

    else:
        if any(c["c"] < candle["l"] for c in newer):
            return None, (
                "setup %s %s %s annulé : clôture sous la mèche"
            ) % (sens, tf, when)

        if any(c["l"] <= sl for c in newer):
            return None, (
                "setup %s %s %s annulé : stop déjà touché"
            ) % (sens, tf, when)

        if (
            any(c["h"] >= entry + STALE_R * risk for c in newer)
            or price_now >= entry + STALE_R * risk
        ):
            return None, (
                "setup %s %s %s annulé : le prix a déjà trop avancé"
            ) % (sens, tf, when)

        if price_now < level:
            return None, (
                "setup %s %s %s annulé : prix repassé sous "
                "le niveau balayé"
            ) % (sens, tf, when)

    # Filtres optionnels, désactivés par défaut.
    d1b, w1b = bias

    if USE_BIAS_FILTER and (d1b != direction or w1b != direction):
        return None, (
            "setup %s %s %s écarté : biais D1/W1 opposé"
        ) % (sens, tf, when)

    if USE_TARGET_FILTER and not has_opposite_liquidity(
        rs, direction, entry, tp
    ):
        return None, (
            "setup %s %s %s écarté : pas de liquidité opposée avant le TP"
        ) % (sens, tf, when)

    decimals = decimals_of(r)
    direction_text = "SELL" if direction < 0 else "BUY"

    return {
        "symbol": symbol,
        "tf": tf,
        "direction": direction_text,
        "entry": entry,
        "zone_low": zone_lo,
        "zone_high": zone_hi,
        "stop_loss": sl,
        "take_profit": tp,
        "risk": risk,
        "risk_atr": risk / atr,
        "level": level,
        "depth_atr": depth / atr,
        "zones": touched,
        "bias_d1": d1b,
        "bias_w1": w1b,
        "bar_time": candle["t"],
        "decimals": decimals,
        "sl_buffer_pips": SL_BUFFER_PIPS,
        "pip_size_used": PIP_SIZE,
        "key": "%s|%s|%.*f" % (
            symbol, direction_text, decimals, level
        ),
    }, None


# ----------------------------------------------------------------------
# RECHERCHE DE SIGNAUX
# ----------------------------------------------------------------------

def find_signals(symbol, h1, h2, h4, d1, price_now=None):
    """
    Analyse un indice à partir des séries H1, H2, H4 et D1.
    Retourne (liste de signaux, liste de journaux).
    """
    logs = []
    signals = []

    if len(h4) < MIN_ZONE_CANDLES or len(d1) < MIN_ZONE_CANDLES:
        return [], [
            "%s : pas assez de bougies H4/D1 (%d/%d)"
            % (symbol, len(h4), len(d1))
        ]

    if not h1:
        return [], ["%s : aucune bougie H1 disponible" % symbol]

    if price_now is None:
        price_now = h1[0]["c"]

    bias = (trend_bias(d1), trend_bias(to_weekly(d1)))
    cache = {}

    def get_zones():
        if "zones" not in cache:
            cache["zones"] = build_zones(h4, d1)
        return cache["zones"]

    for tf, candles in (("H1", h1), ("H2", h2)):
        if tf not in TRIGGER_TFS:
            continue

        if len(candles) < MIN_TRIGGER_CANDLES:
            logs.append(
                "%s : pas assez de bougies %s (%d/%d)"
                % (symbol, tf, len(candles), MIN_TRIGGER_CANDLES)
            )
            continue

        for s in range(STALE_BARS):
            signal, note = evaluate_bar(
                tf, candles, s, get_zones, price_now, bias, symbol
            )

            if signal:
                signals.append(signal)
            elif note:
                logs.append("%s : %s" % (symbol, note))

    # Évite d'envoyer un achat et une vente simultanés sur le même indice.
    if len({signal["direction"] for signal in signals}) > 1:
        logs.append(
            "%s : ACHAT et VENTE simultanés, "
            "aucun signal envoyé (conflit)" % symbol
        )
        signals = []

    return signals, logs


# ----------------------------------------------------------------------
# FORMATAGE DU MESSAGE TELEGRAM
# ----------------------------------------------------------------------

def _bias_txt(value):
    if value > 0:
        return "haussier"
    if value < 0:
        return "baissier"
    return "indisponible"


def format_message(sig):
    decimals = sig["decimals"]

    def fmt(value):
        return "%.*f" % (decimals, value)

    when = dt.datetime.fromtimestamp(
        sig["bar_time"], dt.timezone.utc
    ).strftime("%d/%m %H:%M UTC")

    zones_txt = ", ".join(
        "%s (%s)" % (ZONE_NAMES[ztype], tf)
        for ztype, tf in sig["zones"]
    )

    if sig["direction"] == "SELL":
        motif = "Balayage d'un sommet puis clôture sous le niveau"
    else:
        motif = "Balayage d'un creux puis clôture au-dessus du niveau"

    return (
        "📊 TRADER AI PRO — %s (%s)\n"
        "Signal : %s\n"
        "Unité d'entrée : %s\n"
        "Niveau balayé : %s (mèche de %.2f ATR)\n"
        "Zone de réaction : %s – %s\n"
        "Entrée indicative : %s\n"
        "SL : %s\n"
        "Marge SL : %s pips (valeur du pip provisoire : %s)\n"
        "TP : %s\n"
        "Risque/rendement visé : 1:3 (risque %.2f ATR)\n"
        "Zones touchées : %s\n"
        "Contexte D1 : %s | W1 : %s\n"
        "Motif : %s\n"
        "Bougie de balayage ouverte à : %s\n\n"
        "⚠️ Signal indicatif, non validé par backtest. "
        "Vérifie le prix, la zone et la convention du pip "
        "avant toute entrée."
    ) % (
        display_name(sig["symbol"]),
        sig["symbol"],
        sig["direction"],
        sig["

"""
strategy.py - Règles de la stratégie TRADER AI PRO (v1).

Ce fichier ne fait AUCUN accès réseau et n'ouvre JAMAIS de transaction :
il reçoit des bougies et renvoie des signaux sous forme de texte et de chiffres.

Les valeurs ci-dessous sont des VALEURS DE DÉPART (hypothèses), à calibrer
avec un backtest. Elles ne sont pas tirées d'une mesure sur tes captures.
"""
import datetime as dt

# ----------------------------------------------------------------------
# PARAMÈTRES
# ----------------------------------------------------------------------
TRIGGER_TFS = ["H1", "H2"]       # unités de déclenchement (M30 désactivée en v1)

SWING_N = 5            # R2 : bougies de chaque côté pour définir un sommet/creux
MAX_SWEEP_ATR = 0.5    # R4 : profondeur max de la mèche au-delà du niveau (x ATR)
SL_BUFFER_ATR = 0.1    # R7 : marge du stop loss derrière la mèche (x ATR)
MIN_RISK_ATR = 0.3     # R8 : risque minimum (x ATR)
MAX_RISK_ATR = 3.0     # R8 : risque maximum (x ATR)
RR = 3.0               # R9 : take profit = 3 fois le risque
STALE_R = 0.5          # R10 : le prix a déjà avancé de 0,5 R dans le sens du trade
STALE_BARS = 4         # R10 : un signal de plus de 4 bougies est ignoré

ZONE_TOUCH_ATR = 0.2   # R5 : tolérance entre la mèche et la zone (x ATR)
SR_TOL_ATR = 0.3       # R5 : largeur d'une zone de support/résistance (x ATR)
IMPULSE_ATR = 1.5      # R5 : corps minimal d'une impulsion (x ATR)
BASE_ATR = 0.6         # R5 : amplitude maximale d'une bougie de base (x ATR)

USE_BIAS_FILTER = False     # Option A (désactivée tant que le backtest ne la justifie pas)
USE_TARGET_FILTER = False   # Option B (désactivée tant que le backtest ne la justifie pas)

MIN_TRIGGER_CANDLES = 400   # R11 : bougies minimum en H1 / H2
MIN_ZONE_CANDLES = 200      # R11 : bougies minimum en H4 / D1
ZONE_LOOKBACK = 200

ZT_SR, ZT_SD, ZT_OB = 1, 2, 3
ZONE_NAMES = {ZT_SR: "Support/Résistance", ZT_SD: "Offre/Demande", ZT_OB: "Order Block"}


# ----------------------------------------------------------------------
# OUTILS
# bougies : liste de dictionnaires {"t","o","h","l","c"}, la PLUS RÉCENTE EN PREMIER
# ----------------------------------------------------------------------
def to_series(candles):
    """Convertit la sortie de get_candles (ancienne -> récente) en liste récente -> ancienne."""
    out = [
        {"t": int(c["epoch"]), "o": float(c["open"]), "h": float(c["high"]),
         "l": float(c["low"]), "c": float(c["close"])}
        for c in candles
    ]
    out.reverse()
    return out


def atr_at(r, i, period=14):
    if i + period >= len(r):
        return 0.0
    s = 0.0
    for k in range(i, i + period):
        s += max(r[k]["h"] - r[k]["l"],
                 abs(r[k]["h"] - r[k + 1]["c"]),
                 abs(r[k]["l"] - r[k + 1]["c"]))
    return s / period


def is_swing_high(r, i, n_side):
    if i < n_side or i + n_side >= len(r):
        return False
    h = r[i]["h"]
    for k in range(1, n_side + 1):
        if r[i - k]["h"] >= h or r[i + k]["h"] >= h:
            return False
    return True


def is_swing_low(r, i, n_side):
    if i < n_side or i + n_side >= len(r):
        return False
    lo = r[i]["l"]
    for k in range(1, n_side + 1):
        if r[i - k]["l"] <= lo or r[i + k]["l"] <= lo:
            return False
    return True


def decimals_of(r):
    """Nombre de décimales à afficher, déduit des prix (on ne suppose pas un pip fixe)."""
    d = 2
    for c in r[:50]:
        for k in ("o", "h", "l", "c"):
            s = repr(round(float(c[k]), 6))
            if "e" in s or "." not in s:
                continue
            d = max(d, len(s.split(".")[1].rstrip("0")))
    return min(d, 5)


def display_name(symbol):
    if symbol.startswith("R_"):
        return "Volatility %s Index" % symbol[2:]
    if symbol.startswith("1HZ") and symbol.endswith("V"):
        return "Volatility %s (1s) Index" % symbol[3:-1]
    return symbol


def to_weekly(d1):
    """Reconstruit le Weekly (semaine du lundi, UTC) à partir du Daily (récent -> ancien)."""
    buckets = {}
    for c in reversed(d1):
        day = dt.datetime.fromtimestamp(c["t"], dt.timezone.utc).date()
        monday = day - dt.timedelta(days=day.weekday())
        b = buckets.get(monday)
        if b is None:
            buckets[monday] = {"t": c["t"], "o": c["o"], "h": c["h"], "l": c["l"], "c": c["c"]}
        else:
            b["h"] = max(b["h"], c["h"])
            b["l"] = min(b["l"], c["l"])
            b["c"] = c["c"]
    this_monday = dt.datetime.now(dt.timezone.utc).date()
    this_monday -= dt.timedelta(days=this_monday.weekday())
    weeks = [buckets[k] for k in sorted(buckets) if k != this_monday]   # semaine en cours = incomplète
    weeks.reverse()
    return weeks


# ----------------------------------------------------------------------
# ZONES (R5)  -> tuples (bas, haut, type, direction, unité de temps)
# direction : +1 = support/demande, -1 = résistance/offre
# ----------------------------------------------------------------------
def zone_broken(r, frm, lo, hi, d):
    for k in range(frm, -1, -1):
        if d > 0 and r[k]["c"] < lo:
            return True
        if d < 0 and r[k]["c"] > hi:
            return True
    return False


def build_sr(r, min_touches, tf):
    zones = []
    n = len(r)
    atr = atr_at(r, 0)
    if atr <= 0:
        return zones
    tol = SR_TOL_ATR * atr
    pts = []
    for i in range(3, n - 3):
        if is_swing_high(r, i, 3):
            pts.append((r[i]["h"], -1))
        elif is_swing_low(r, i, 3):
            pts.append((r[i]["l"], 1))
    for a, (lv, kind) in enumerate(pts):
        touches = 1 + sum(1 for b, (lv2, _) in enumerate(pts) if b != a and abs(lv - lv2) <= tol)
        if touches >= min_touches:
            zones.append((lv - tol / 2, lv + tol / 2, ZT_SR, kind, tf))
    return zones


def build_sdob(r, tf):
    zones = []
    n = len(r)
    for i in range(0, n - 30):
        atr = atr_at(r, i + 1)
        if atr <= 0:
            continue
        if abs(r[i]["c"] - r[i]["o"]) < IMPULSE_ATR * atr:
            continue
        d = 1 if r[i]["c"] > r[i]["o"] else -1

        brk = True      # l'impulsion casse-t-elle la structure des 10 bougies précédentes ?
        for k in range(i + 1, i + 11):
            if d > 0 and r[i]["c"] <= r[k]["h"]:
                brk = False
                break
            if d < 0 and r[i]["c"] >= r[k]["l"]:
                brk = False
                break

        if brk:         # order block : dernière bougie de couleur opposée
            for j in range(i + 1, i + 6):
                opp = (d > 0 and r[j]["c"] < r[j]["o"]) or (d < 0 and r[j]["c"] > r[j]["o"])
                if opp:
                    if not zone_broken(r, i - 1, r[j]["l"], r[j]["h"], d):
                        zones.append((r[j]["l"], r[j]["h"], ZT_OB, d, tf))
                    break

        b = 0           # offre / demande : 1 à 3 petites bougies de base
        lo, hi = float("inf"), float("-inf")
        while b < 3 and (r[i + 1 + b]["h"] - r[i + 1 + b]["l"]) < BASE_ATR * atr:
            lo = min(lo, r[i + 1 + b]["l"])
            hi = max(hi, r[i + 1 + b]["h"])
            b += 1
        if b >= 1 and not zone_broken(r, i - 1, lo, hi, d):
            zones.append((lo, hi, ZT_SD, d, tf))
    return zones


def build_zones(h4, d1):
    """Zones calculées sur W1 (reconstruit depuis D1), D1 et H4."""
    zones = []
    w1 = to_weekly(d1)
    d1z = d1[:ZONE_LOOKBACK]
    h4z = h4[:ZONE_LOOKBACK]
    if len(w1) >= 30:
        zones += build_sr(w1, 1, "W1")
    if len(d1z) >= MIN_ZONE_CANDLES:
        zones += build_sr(d1z, 2, "D1") + build_sdob(d1z, "D1")
    if len(h4z) >= MIN_ZONE_CANDLES:
        zones += build_sr(h4z, 2, "H4") + build_sdob(h4z, "H4")
    return zones


def trend_bias(r):
    """+1 : clôture au-dessus de l'EMA 50 ; -1 : en dessous ; 0 : pas assez de données."""
    if len(r) < 60:
        return 0
    k = 2.0 / 51.0
    ema = r[-1]["c"]
    for i in range(len(r) - 2, -1, -1):
        ema = r[i]["c"] * k + ema * (1.0 - k)
    return 1 if r[0]["c"] > ema else -1


# ----------------------------------------------------------------------
# BALAYAGE (R2, R3, R4)   rs[0] = bougie de balayage S
# ----------------------------------------------------------------------
def detect_sweep(rs, atr):
    """Retourne (direction, niveau) : -1 = VENTE (sommet balayé), +1 = ACHAT (creux balayé), 0 = rien."""
    n = len(rs)
    s = rs[0]
    for i in range(SWING_N + 1, n - SWING_N - 1):
        if is_swing_high(rs, i, SWING_N):
            lvl = rs[i]["h"]
            if s["h"] > lvl and s["c"] < lvl and (s["h"] - lvl) <= MAX_SWEEP_ATR * atr:
                if all(rs[k]["h"] <= lvl for k in range(1, i)):       # niveau encore intact
                    return -1, lvl
    for i in range(SWING_N + 1, n - SWING_N - 1):
        if is_swing_low(rs, i, SWING_N):
            lvl = rs[i]["l"]
            if s["l"] < lvl and s["c"] > lvl and (lvl - s["l"]) <= MAX_SWEEP_ATR * atr:
                if all(rs[k]["l"] >= lvl for k in range(1, i)):
                    return 1, lvl
    return 0, 0.0


def has_opposite_liquidity(rs, d, entry, tp):
    """Option B : existe-t-il une liquidité opposée intacte entre l'entrée et le TP ?"""
    n = len(rs)
    for i in range(SWING_N + 1, n - SWING_N - 1):
        if d < 0 and is_swing_low(rs, i, SWING_N):
            lvl = rs[i]["l"]
            if tp <= lvl < entry and all(rs[k]["l"] > lvl for k in range(0, i)):
                return True
        if d > 0 and is_swing_high(rs, i, SWING_N):
            lvl = rs[i]["h"]
            if entry < lvl <= tp and all(rs[k]["h"] < lvl for k in range(0, i)):
                return True
    return False


# ----------------------------------------------------------------------
# ÉVALUATION D'UNE BOUGIE (R2 à R10)
# r : bougies de l'unité de déclenchement (récent -> ancien) ; s : position de S
# ----------------------------------------------------------------------
def evaluate_bar(tf, r, s, get_zones, price_now, bias, symbol):
    """Retourne (signal ou None, note de rejet ou None)."""
    rs = r[s:]
    atr = atr_at(rs, 0)
    if atr <= 0:
        return None, None
    d, level = detect_sweep(rs, atr)
    if d == 0:
        return None, None

    S = rs[0]
    when = dt.datetime.fromtimestamp(S["t"], dt.timezone.utc).strftime("%d/%m %H:%M")
    sens = "VENTE" if d < 0 else "ACHAT"
    depth = (S["h"] - level) if d < 0 else (level - S["l"])

    # R5 : la mèche doit toucher une zone du bon côté
    wick_lo, wick_hi = (level, S["h"]) if d < 0 else (S["l"], level)
    margin = ZONE_TOUCH_ATR * atr
    touched = []
    for lo, hi, ztype, zdir, ztf in get_zones():
        if zdir == d and hi >= wick_lo - margin and lo <= wick_hi + margin:
            if (ztype, ztf) not in touched:
                touched.append((ztype, ztf))
    if not touched:
        return None, "balayage %s %s %s rejeté : aucune zone du bon côté ne touche la mèche" % (sens, tf, when)

    # R6, R7, R8, R9 : entrée, stop, risque, objectif
    entry = S["c"]
    if d < 0:
        sl = S["h"] + SL_BUFFER_ATR * atr
        risk = sl - entry
        tp = entry - RR * risk
        zone_lo, zone_hi = entry, level
    else:
        sl = S["l"] - SL_BUFFER_ATR * atr
        risk = entry - sl
        tp = entry + RR * risk
        zone_lo, zone_hi = level, entry
    if risk <= 0 or risk < MIN_RISK_ATR * atr or risk > MAX_RISK_ATR * atr:
        return None, "balayage %s %s %s rejeté : risque hors limites (%.2f ATR)" % (
            sens, tf, when, risk / atr)

    # R10 : annulation avant l'entrée
    newer = r[:s]     # bougies postérieures à S
    if d < 0:
        if any(c["c"] > S["h"] for c in newer):
            return None, "setup %s %s %s annulé : clôture au-dessus de la mèche" % (sens, tf, when)
        if any(c["h"] >= sl for c in newer):
            return None, "setup %s %s %s annulé : stop déjà touché" % (sens, tf, when)
        if any(c["l"] <= entry - STALE_R * risk for c in newer) or price_now <= entry - STALE_R * risk:
            return None, "setup %s %s %s annulé : le prix a déjà trop avancé" % (sens, tf, when)
        if price_now > level:
            return None, "setup %s %s %s annulé : prix revenu au-dessus du niveau balayé" % (sens, tf, when)
    else:
        if any(c["c"] < S["l"] for c in newer):
            return None, "setup %s %s %s annulé : clôture sous la mèche" % (sens, tf, when)
        if any(c["l"] <= sl for c in newer):
            return None, "setup %s %s %s annulé : stop déjà touché" % (sens, tf, when)
        if any(c["h"] >= entry + STALE_R * risk for c in newer) or price_now >= entry + STALE_R * risk:
            return None, "setup %s %s %s annulé : le prix a déjà trop avancé" % (sens, tf, when)
        if price_now < level:
            return None, "setup %s %s %s annulé : prix repassé sous le niveau balayé" % (sens, tf, when)

    # Options (désactivées par défaut)
    d1b, w1b = bias
    if USE_BIAS_FILTER and (d1b != d or w1b != d):
        return None, "setup %s %s %s écarté : biais D1/W1 opposé" % (sens, tf, when)
    if USE_TARGET_FILTER and not has_opposite_liquidity(rs, d, entry, tp):
        return None, "setup %s %s %s écarté : pas de liquidité opposée avant le TP" % (sens, tf, when)

    dg = decimals_of(r)
    return {
        "symbol": symbol,
        "tf": tf,
        "direction": "SELL" if d < 0 else "BUY",
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
        "bar_time": S["t"],
        "decimals": dg,
        "key": "%s|%s|%.*f" % (symbol, "SELL" if d < 0 else "BUY", dg, level),
    }, None


def find_signals(symbol, h1, h2, h4, d1, price_now=None):
    """
    Applique la stratégie à un indice.
    h1, h2, h4, d1 : bougies (récent -> ancien) renvoyées par to_series().
    Retourne (liste de signaux, liste de lignes de journal).
    """
    logs = []
    sigs = []
    if len(h4) < MIN_ZONE_CANDLES or len(d1) < MIN_ZONE_CANDLES:
        return [], ["%s : pas assez de bougies H4/D1 (%d/%d)" % (symbol, len(h4), len(d1))]
    if price_now is None:
        price_now = h1[0]["c"]
    bias = (trend_bias(d1), trend_bias(to_weekly(d1)))

    cache = {}

    def get_zones():
        if "z" not in cache:
            cache["z"] = build_zones(h4, d1)
        return cache["z"]

    for tf, r in (("H1", h1), ("H2", h2)):
        if tf not in TRIGGER_TFS:
            continue
        if len(r) < MIN_TRIGGER_CANDLES:
            logs.append("%s : pas assez de bougies %s (%d/%d)" % (symbol, tf, len(r), MIN_TRIGGER_CANDLES))
            continue
        for s in range(STALE_BARS):
            sig, note = evaluate_bar(tf, r, s, get_zones, price_now, bias, symbol)
            if sig:
                sigs.append(sig)
            elif note:
                logs.append("%s : %s" % (symbol, note))

    # R11 : un ACHAT et une VENTE valides en même temps sur le même indice -> aucun signal
    if len({x["direction"] for x in sigs}) > 1:
        logs.append("%s : ACHAT et VENTE simultanés, aucun signal envoyé (conflit)" % symbol)
        sigs = []

    return sigs, logs


# ----------------------------------------------------------------------
# MESSAGE TELEGRAM
# ----------------------------------------------------------------------
def _bias_txt(v):
    return "haussier" if v > 0 else ("baissier" if v < 0 else "indisponible")


def format_message(sig):
    dg = sig["decimals"]

    def f(x):
        return "%.*f" % (dg, x)

    when = dt.datetime.fromtimestamp(sig["bar_time"], dt.timezone.utc).strftime("%d/%m %H:%M UTC")
    zones_txt = ", ".join("%s (%s)" % (ZONE_NAMES[t], tf) for t, tf in sig["zones"])
    if sig["direction"] == "SELL":
        motif = "Balayage d'un sommet puis clôture sous le niveau"
    else:
        motif = "Balayage d'un creux puis clôture au-dessus du niveau"

    return (
        "📊 TRADER AI PRO — %s (%s)\n"
        "Signal : %s\n"
        "Unité d'entrée : %s\n"
        "Niveau balayé : %s (mèche de %.2f ATR)\n"
        "Zone d'entrée : %s – %s\n"
        "Entrée indicative : %s\n"
        "SL : %s\n"
        "TP : %s\n"
        "Risque/rendement visé : 1:3 (risque %.2f ATR)\n"
        "Zones touchées : %s\n"
        "Contexte D1 : %s | W1 : %s\n"
        "Motif : %s\n"
        "Bougie de balayage ouverte à : %s\n\n"
        "⚠️ Signal indicatif, non validé par backtest. "
        "Vérifie le prix, la zone et la distance du SL avant toute entrée."
    ) % (
        display_name(sig["symbol"]), sig["symbol"], sig["direction"], sig["tf"],
        f(sig["level"]), sig["depth_atr"],
        f(sig["zone_low"]), f(sig["zone_high"]), f(sig["entry"]),
        f(sig["stop_loss"]), f(sig["take_profit"]), sig["risk_atr"],
        zones_txt, _bias_txt(sig["bias_d1"]), _bias_txt(sig["bias_w1"]),
        motif, when,
)

# ============================================================
# 25. IMPORT POUR SECURISER LES MESSAGES TELEGRAM
# ============================================================

import html


# ============================================================
# 26. FONCTION PRINCIPALE D'ANALYSE MULTI-TIMEFRAME
# ============================================================

def find_signals(
    symbol,
    d1_candles,
    h4_candles,
    h2_candles,
    h1_candles,
    price_now,
    diagnostics=None,
):
    """
    Analyse un indice synthétique sur quatre unités de temps.

    D1 : détection des supports et résistances.
    H4 : affinage des zones et validation des trendlines.
    H2 : recherche de confluence horizontale.
    H1 : recherche de confluence horizontale.

    Les entrées sont anticipées.
    Aucun ordre n'est exécuté automatiquement.
    """

    if diagnostics is None:
        diagnostics = {}

    diagnostics.update({
        "symbol": symbol,
        "strategy": STRATEGY_NAME,
        "status": "ANALYZING",
        "reason": "",
        "signals_found": 0,
    })

    try:

        # ----------------------------------------------------
        # A. NORMALISATION DES DONNEES
        # ----------------------------------------------------

        d1 = _normalise_candles(d1_candles)
        h4 = _normalise_candles(h4_candles)
        h2 = _normalise_candles(h2_candles)
        h1 = _normalise_candles(h1_candles)

        candle_counts = {
            "D1": len(d1),
            "H4": len(h4),
            "H2": len(h2),
            "H1": len(h1),
        }

        diagnostics["candles"] = candle_counts

        # ----------------------------------------------------
        # B. VERIFICATION DU NOMBRE DE BOUGIES
        # ----------------------------------------------------

        for timeframe, candles in (
            ("D1", d1),
            ("H4", h4),
            ("H2", h2),
            ("H1", h1),
        ):

            minimum = MIN_CANDLES[timeframe]

            if len(candles) < minimum:

                diagnostics.update({
                    "status": "INSUFFICIENT_DATA",
                    "reason": (
                        f"{timeframe}: {len(candles)} bougies "
                        f"disponibles, {minimum} nécessaires."
                    ),
                })

                return []

        # ----------------------------------------------------
        # C. VERIFICATION DU PRIX ACTUEL
        # ----------------------------------------------------

        current_price = _number(price_now)

        if current_price is None or current_price <= 0:

            diagnostics.update({
                "status": "INVALID_PRICE",
                "reason": "Prix actuel absent ou invalide.",
            })

            return []

        # ----------------------------------------------------
        # D. CALCUL DES ATR
        # ----------------------------------------------------

        d1_atr = _calculate_atr(d1)
        h4_atr = _calculate_atr(h4)
        h2_atr = _calculate_atr(h2)
        h1_atr = _calculate_atr(h1)

        atr_values = {
            "D1": d1_atr,
            "H4": h4_atr,
            "H2": h2_atr,
            "H1": h1_atr,
        }

        for timeframe, atr in atr_values.items():

            if atr is None or atr <= 0:

                diagnostics.update({
                    "status": "INVALID_ATR",
                    "reason": (
                        f"ATR invalide sur {timeframe}."
                    ),
                })

                return []

        # ----------------------------------------------------
        # E. DETECTION DES ZONES D1
        # ----------------------------------------------------

        d1_supports, d1_resistances = _d1_zones(
            d1,
            d1_atr,
        )

        diagnostics["d1_supports"] = len(d1_supports)
        diagnostics["d1_resistances"] = len(d1_resistances)

        if not d1_supports and not d1_resistances:

            diagnostics.update({
                "status": "NO_VALID_ZONE",
                "reason": (
                    "Aucune zone horizontale D1 suffisamment "
                    "valide n'a été détectée."
                ),
            })

            return []

        # ----------------------------------------------------
        # F. AFFINAGE DES ZONES D1 AVEC LES REACTIONS H4
        # ----------------------------------------------------

        refined_supports = []
        refined_resistances = []

        for zone in d1_supports:

            refined = _refine_d1_zone_with_h4(
                zone,
                h4,
                h4_atr,
            )

            if refined:
                refined_supports.append(refined)

        for zone in d1_resistances:

            refined = _refine_d1_zone_with_h4(
                zone,
                h4,
                h4_atr,
            )

            if refined:
                refined_resistances.append(refined)

        diagnostics["refined_supports"] = len(
            refined_supports
        )

        diagnostics["refined_resistances"] = len(
            refined_resistances
        )

        if not refined_supports and not refined_resistances:

            diagnostics.update({
                "status": "NO_VALID_REFINEMENT",
                "reason": (
                    "Les réactions H4 ne permettent pas "
                    "d'affiner suffisamment les zones D1."
                ),
            })

            return []

        # ----------------------------------------------------
        # G. CONSTRUCTION DES OPPORTUNITES BUY ET SELL
        # ----------------------------------------------------

        candidates = []

        for zone in refined_supports:

            candidate = _build_candidate(
                symbol=symbol,
                direction="BUY",
                refined_zone=zone,
                h4_candles=h4,
                h2_candles=h2,
                h1_candles=h1,
                h4_atr=h4_atr,
                h2_atr=h2_atr,
                h1_atr=h1_atr,
                price_now=current_price,
            )

            if candidate:
                candidates.append(candidate)

        for zone in refined_resistances:

            candidate = _build_candidate(
                symbol=symbol,
                direction="SELL",
                refined_zone=zone,
                h4_candles=h4,
                h2_candles=h2,
                h1_candles=h1,
                h4_atr=h4_atr,
                h2_atr=h2_atr,
                h1_atr=h1_atr,
                price_now=current_price,
            )

            if candidate:
                candidates.append(candidate)

        # ----------------------------------------------------
        # H. VALIDATION ET IDENTIFICATION DES SIGNAUX
        # ----------------------------------------------------

        valid_signals = []

        for candidate in candidates:

            if not _validate_signal(candidate):
                continue

            candidate["signal_id"] = _make_signal_id(
                candidate
            )

            candidate["status"] = "NEW"

            valid_signals.append(candidate)

        # ----------------------------------------------------
        # I. RESULTAT FINAL
        # ----------------------------------------------------

        if not valid_signals:

            diagnostics.update({
                "status": "NO_SIGNAL",
                "reason": (
                    "Aucune configuration ne satisfait "
                    "tous les critères de la stratégie."
                ),
                "signals_found": 0,
            })

            return []

        diagnostics.update({
            "status": "SIGNALS_FOUND",
            "reason": "Configuration(s) valide(s) détectée(s).",
            "signals_found": len(valid_signals),
        })

        return valid_signals

    except Exception as exc:

        diagnostics.update({
            "status": "ANALYSIS_ERROR",
            "reason": (
                f"{type(exc).__name__}: {str(exc)}"
            ),
            "signals_found": 0,
        })

        return []


# ============================================================
# 27. FORMATAGE DU MESSAGE TELEGRAM
# ============================================================

def format_message(signal):
    """
    Produit un message Telegram au format HTML.
    """

    symbol = str(
        signal.get("symbol", "UNKNOWN")
    )

    symbol_name = SYMBOL_NAMES.get(
        symbol,
        symbol,
    )

    direction = signal.get(
        "direction",
        "UNKNOWN",
    )

    direction_label = (
        "ACHAT / BUY"
        if direction == "BUY"
        else "VENTE / SELL"
    )

    emoji = (
        "🟢"
        if direction == "BUY"
        else "🔴"
    )

    entry = signal.get("entry", 0)
    stop_loss = signal.get("stop_loss", 0)
    take_profit = signal.get("take_profit", 0)
    rr = signal.get("rr", 0)

    zone_low = signal.get("zone_low", 0)
    zone_high = signal.get("zone_high", 0)

    trendline_touches = signal.get(
        "trendline_touches",
        0,
    )

    zone_touches = signal.get(
        "zone_touches",
        0,
    )

    signal_id = html.escape(
        str(signal.get("signal_id", "N/A"))
    )

    safe_symbol = html.escape(symbol_name)

    lines = [
        "🚨 <b>TRADER AI PRO</b>",
        "━━━━━━━━━━━━━━━━━━",
        "",
        f"📊 <b>Indice :</b> {safe_symbol}",
        f"🔎 <b>Symbole :</b> {html.escape(symbol)}",
        f"{emoji} <b>Direction :</b> {direction_label}",
        "",
        "🎯 <b>PLAN DE TRADING</b>",
        f"📍 Entrée : <code>{entry}</code>",
        f"🛑 Stop Loss : <code>{stop_loss}</code>",
        f"🏁 Take Profit : <code>{take_profit}</code>",
        f"⚖️ Risk/Reward : <b>1:{rr}</b>",
        "",
        "📐 <b>ANALYSE TECHNIQUE</b>",
        f"• Zone affinée : {zone_low} - {zone_high}",
        f"• Réactions de la zone : {zone_touches}",
        f"• Contacts trendline : {trendline_touches}",
        "• Confluence : D1 + H4 + H2 + H1",
        "• Entrée : anticipée",
        "",
        f"🆔 Signal : <code>{signal_id}</code>",
        "",
        "⚠️ <b>ALERTE UNIQUEMENT</b>",
        "Aucun ordre automatique n'est exécuté.",
        "Vérifiez le graphique avant toute prise de position.",
        "",
        "━━━━━━━━━━━━━━━━━━",
        "Trader AI Pro — Analyse technique",
    ]

    return "\n".join(lines)
    # ============================================================
# 8. IMPORT DU MODULE DE DONNEES DERIV
# ============================================================

try:

    from deriv_market import (
        get_candles,
        get_current_price,
    )

except ImportError as exc:

    logger.critical(
        "Impossible d'importer deriv_market.py : %s",
        exc,
    )

    raise


# ============================================================
# 9. VERIFICATION DES DONNEES DE MARCHE
# ============================================================

def validate_candles(candles, timeframe):
    """
    Vérifie que les bougies reçues sont exploitables.
    """

    if not isinstance(candles, list):
        logger.warning(
            "%s : format de bougies invalide.",
            timeframe,
        )
        return False

    minimum = TIMEFRAMES[timeframe]["candles"]

    if len(candles) < minimum:
        logger.warning(
            "%s : seulement %s bougies reçues, %s nécessaires.",
            timeframe,
            len(candles),
            minimum,
        )
        return False

    return True


# ============================================================
# 10. RECUPERATION DES BOUGIES D'UN INDICE
# ============================================================

def fetch_symbol_candles(symbol):
    """
    Récupère les 200 bougies de chaque unité de temps.
    """

    market_data = {}

    for timeframe, settings in TIMEFRAMES.items():

        candles = None

        for attempt in range(1, MAX_RETRIES + 1):

            try:

                logger.info(
                    "%s | Récupération %s | tentative %s/%s",
                    symbol,
                    timeframe,
                    attempt,
                    MAX_RETRIES,
                )

                candles = get_candles(
                    symbol=symbol,
                    granularity=settings["granularity"],
                    count=settings["candles"],
                )

                if validate_candles(
                    candles,
                    timeframe,
                ):
                    break

                candles = None

            except Exception as exc:

                logger.warning(
                    "%s | Erreur récupération %s : %s",
                    symbol,
                    timeframe,
                    exc,
                )

                candles = None

            if attempt < MAX_RETRIES:
                time.sleep(RETRY_DELAY)

        if candles is None:

            logger.error(
                "%s | Impossible de récupérer les bougies %s.",
                symbol,
                timeframe,
            )

            return None

        market_data[timeframe] = candles

    return market_data


# ============================================================
# 11. RECUPERATION DU PRIX ACTUEL
# ============================================================

def fetch_current_price(symbol):
    """
    Récupère le dernier prix disponible.
    """

    for attempt in range(1, MAX_RETRIES + 1):

        try:

            price = get_current_price(
                symbol=symbol,
            )

            if price is None:
                raise ValueError(
                    "Prix actuel absent."
                )

            price = float(price)

            if price <= 0:
                raise ValueError(
                    "Prix actuel invalide."
                )

            return price

        except Exception as exc:

            logger.warning(
                "%s | Erreur prix actuel : %s | tentative %s/%s",
                symbol,
                exc,
                attempt,
                MAX_RETRIES,
            )

            if attempt < MAX_RETRIES:
                time.sleep(RETRY_DELAY)

    return None


# ============================================================
# 12. RECUPERATION COMPLETE DES DONNEES
# ============================================================

def fetch_market_data(symbol):
    """
    Récupère les bougies D1, H4, H2, H1
    et le prix actuel d'un indice.
    """

    logger.info(
        "%s | Début récupération des données.",
        symbol,
    )

    candles = fetch_symbol_candles(symbol)

    if candles is None:
        return None

    price_now = fetch_current_price(symbol)

    if price_now is None:

        logger.error(
            "%s | Prix actuel indisponible.",
            symbol,
        )

        return None

    return {
        "d1_candles": candles["D1"],
        "h4_candles": candles["H4"],
        "h2_candles": candles["H2"],
        "h1_candles": candles["H1"],
        "price_now": price_now,
    }
    # ============================================================
# 13. VERIFICATION DE LA CONFIGURATION TELEGRAM
# ============================================================

def telegram_is_ready():
    """
    Vérifie que Telegram est correctement configuré.
    """

    if not ENABLE_TELEGRAM_ALERTS:
        logger.info("Alertes Telegram désactivées.")
        return False

    if not TELEGRAM_BOT_TOKEN:
        logger.error("Token Telegram manquant.")
        return False

    if not TELEGRAM_CHAT_ID:
        logger.error("Chat ID Telegram manquant.")
        return False

    return True


# ============================================================
# 14. ENVOI D'UN MESSAGE TELEGRAM
# ============================================================

def send_telegram_message(message):
    """
    Envoie une alerte Telegram.

    Aucun ordre de trading n'est exécuté ici.
    """

    if not telegram_is_ready():
        return False

    url = (
        f"https://api.telegram.org/bot"
        f"{TELEGRAM_BOT_TOKEN}/sendMessage"
    )

    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }

    for attempt in range(1, MAX_RETRIES + 1):

        try:

            response = requests.post(
                url,
                json=payload,
                timeout=REQUEST_TIMEOUT,
            )

            response.raise_for_status()

            result = response.json()

            if not result.get("ok", False):
                raise RuntimeError(
                    result.get(
                        "description",
                        "Erreur Telegram inconnue.",
                    )
                )

            logger.info("Alerte Telegram envoyée.")

            return True

        except Exception as exc:

            logger.error(
                "Erreur Telegram : %s | tentative %s/%s",
                exc,
                attempt,
                MAX_RETRIES,
            )

            if attempt < MAX_RETRIES:
                time.sleep(RETRY_DELAY)

    return False


# ============================================================
# 15. ANALYSE D'UN INDICE
# ============================================================

def analyze_symbol(symbol):
    """
    Récupère les données puis lance l'analyse technique.
    """

    logger.info("-" * 55)

    logger.info(
        "ANALYSE DE L'INDICE : %s",
        symbol,
    )

    market_data = fetch_market_data(symbol)

    if market_data is None:

        logger.warning(
            "%s | Analyse ignorée : données indisponibles.",
            symbol,
        )

        return []

    diagnostics = {}

    signals = find_signals(
        symbol=symbol,
        d1_candles=market_data["d1_candles"],
        h4_candles=market_data["h4_candles"],
        h2_candles=market_data["h2_candles"],
        h1_candles=market_data["h1_candles"],
        price_now=market_data["price_now"],
        diagnostics=diagnostics,
    )

    logger.info(
        "%s | Résultat : %s",
        symbol,
        diagnostics.get("status", "UNKNOWN"),
    )

    if diagnostics.get("reason"):
        logger.info(
            "%s | Motif : %s",
            symbol,
            diagnostics["reason"],
        )

    if not signals:

        logger.info(
            "%s | Aucun signal valide.",
            symbol,
        )

        return []

    logger.info(
        "%s | %s signal(aux) détecté(s).",
        symbol,
        len(signals),
    )

    return signals


# ============================================================
# 16. TRAITEMENT DES SIGNAUX
# ============================================================

def process_signals(signals):
    """
    Formate et transmet les signaux à Telegram.
    """

    if not signals:
        return 0

    sent_count = 0

    for signal in signals:

        try:

            message = format_message(signal)

            logger.info(
                "%s | Signal %s détecté.",
                signal.get("symbol"),
                signal.get("direction"),
            )

            if ENABLE_TELEGRAM_ALERTS:

                if send_telegram_message(message):
                    sent_count += 1

                else:
                    logger.error(
                        "Impossible d'envoyer le signal %s.",
                        signal.get("signal_id"),
                    )

            else:

                logger.info(
                    "Alerte non envoyée : Telegram désactivé."
                )

        except Exception:

            logger.error(
                "Erreur lors du traitement d'un signal :\n%s",
                traceback.format_exc(),
            )

    return sent_count


# ============================================================
# 17. ANALYSE DE TOUS LES INDICES
# ============================================================

def analyze_all_symbols():
    """
    Parcourt tous les indices configurés.
    """

    total_signals = 0
    total_alerts_sent = 0

    for index, symbol in enumerate(SYMBOLS, start=1):

        logger.info(
            "Indice %s/%s : %s",
            index,
            len(SYMBOLS),
            symbol,
        )

        try:

            signals = analyze_symbol(symbol)

            total_signals += len(signals)

            sent = process_signals(signals)

            total_alerts_sent += sent

        except Exception:

            logger.error(
                "%s | Erreur générale :\n%s",
                symbol,
                traceback.format_exc(),
            )

        if index < len(SYMBOLS):
            time.sleep(SYMBOL_DELAY)

    return {
        "symbols_analyzed": len(SYMBOLS),
        "signals_found": total_signals,
        "alerts_sent": total_alerts_sent,
    }
    # ============================================================
# 18. AFFICHAGE DU BILAN FINAL
# ============================================================

def print_analysis_summary(results, start_time):
    """
    Affiche le bilan complet de l'analyse.
    """

    end_time = time.time()

    duration = round(
        end_time - start_time,
        2,
    )

    logger.info("=" * 55)
    logger.info("BILAN DE L'ANALYSE TRADER AI PRO")
    logger.info("=" * 55)

    logger.info(
        "Indices analysés : %s",
        results["symbols_analyzed"],
    )

    logger.info(
        "Signaux détectés : %s",
        results["signals_found"],
    )

    logger.info(
        "Alertes Telegram envoyées : %s",
        results["alerts_sent"],
    )

    logger.info(
        "Durée totale : %s secondes",
        duration,
    )

    logger.info(
        "DRY_RUN : %s",
        DRY_RUN,
    )

    logger.info(
        "Exécution automatique des ordres : DÉSACTIVÉE",
    )

    logger.info("=" * 55)


# ============================================================
# 19. FONCTION PRINCIPALE
# ============================================================

def main():
    """
    Point d'entrée du programme.
    """

    start_time = time.time()

    print_startup_information()

    logger.info(
        "Démarrage de l'analyse programmée."
    )

    # Vérification de la configuration Telegram.
    if ENABLE_TELEGRAM_ALERTS:

        if telegram_is_ready():

            logger.info(
                "Configuration Telegram valide."
            )

        else:

            logger.warning(
                "Telegram est activé mais sa configuration "
                "est incomplète."
            )

    # Analyse des indices.
    try:

        results = analyze_all_symbols()

    except KeyboardInterrupt:

        logger.warning(
            "Analyse interrompue manuellement."
        )

        return 1

    except Exception:

        logger.critical(
            "Erreur critique pendant l'analyse :\n%s",
            traceback.format_exc(),
        )

        return 1

    # Affichage du bilan.
    print_analysis_summary(
        results,
        start_time,
    )

    logger.info(
        "Analyse programmée terminée."
    )

    return 0


# ============================================================
# 20. EXECUTION DU PROGRAMME
# ============================================================

if __name__ == "__main__":

    exit_code = main()

    sys.exit(exit_code)
    

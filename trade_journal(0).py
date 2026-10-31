"""Outils de consultation et de mise à jour manuelle du journal de trades."""
import argparse
import os
import sqlite3
from pathlib import Path

DB_PATH = Path(os.environ.get("TRADER_DB_PATH", "state/trader_ai_pro.sqlite3"))
OUTCOMES = {"WIN", "LOSS", "BREAKEVEN", "NOT_TAKEN", "OPEN"}


def main():
    parser = argparse.ArgumentParser(description="Journal manuel des signaux Trader AI Pro")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("list", help="Afficher les derniers signaux")
    update = sub.add_parser("update", help="Enregistrer le résultat d'un signal")
    update.add_argument("--id", required=True, help="ID exact indiqué dans le message Telegram")
    update.add_argument("--outcome", required=True, choices=sorted(OUTCOMES))
    update.add_argument("--r", type=float, default=None, help="Résultat en R, par ex. 3 pour +3R, -1 pour -1R")
    update.add_argument("--notes", default="", help="Commentaire facultatif")
    args = parser.parse_args()

    if not DB_PATH.exists():
        raise SystemExit(f"Base absente: {DB_PATH}. Lance d'abord le workflow d'analyse.")
    with sqlite3.connect(DB_PATH) as db:
        if args.command == "list":
            rows = db.execute(
                "SELECT signal_id, created_at, symbol, direction, entry, stop_loss, take_profit, status, outcome, result_r "
                "FROM signals ORDER BY created_at DESC LIMIT 30"
            ).fetchall()
            if not rows:
                print("Aucun signal enregistré.")
            for row in rows:
                print(" | ".join("" if v is None else str(v) for v in row))
        else:
            cur = db.execute(
                "UPDATE signals SET status=?, outcome=?, result_r=?, notes=? WHERE signal_id=?",
                ("CLOTURE" if args.outcome not in ("OPEN", "NOT_TAKEN") else args.outcome,
                 args.outcome, args.r, args.notes, args.id),
            )
            if cur.rowcount == 0:
                raise SystemExit("ID inconnu. Vérifie l'ID exact du message Telegram et la base de données.")
            db.execute("INSERT INTO run_log(event, detail) VALUES (?, ?)",
                       ("RESULT_UPDATED", f"{args.id} | {args.outcome} | R={args.r} | {args.notes}"))
            db.commit()
            print("Résultat enregistré.")


if __name__ == "__main__":
    main()

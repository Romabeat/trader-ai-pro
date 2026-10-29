name: Trader AI Pro — SMC Telegram

on:
  workflow_dispatch:
    inputs:
      journal_signal_id:
        description: "ID du signal Telegram (laisser vide pour un scan normal)"
        required: false
        type: string
      journal_outcome:
        description: "Résultat manuel (utilisé si un ID est fourni)"
        required: false
        type: choice
        options:
          - OPEN
          - WIN
          - LOSS
          - BREAKEVEN
          - NOT_TAKEN
        default: OPEN
      journal_result_r:
        description: "Résultat en R : 3, -1, 0, etc. (laisser vide si inconnu)"
        required: false
        type: string
      journal_notes:
        description: "Notes facultatives"
        required: false
        type: string
  schedule:
    - cron: "17,47 * * * *"

permissions:
  contents: read

concurrency:
  group: trader-ai-pro-scheduled-scan
  cancel-in-progress: false

jobs:
  analysis:
    runs-on: ubuntu-latest
    timeout-minutes: 15
    env:
      PYTHONUNBUFFERED: "1"
      DRY_RUN: "true"
      ENABLE_TELEGRAM_ALERTS: "true"
      TRADER_DB_PATH: "state/trader_ai_pro.sqlite3"
      TELEGRAM_TOKEN: ${{ secrets.TELEGRAM_TOKEN }}
      TELEGRAM_CHAT_ID: ${{ secrets.TELEGRAM_CHAT_ID }}
      JOURNAL_SIGNAL_ID: ${{ inputs.journal_signal_id }}
      JOURNAL_OUTCOME: ${{ inputs.journal_outcome }}
      JOURNAL_RESULT_R: ${{ inputs.journal_result_r }}
      JOURNAL_NOTES: ${{ inputs.journal_notes }}
    steps:
      - name: Récupérer le dépôt
        uses: actions/checkout@v4

      - name: Installer Python
        uses: actions/setup-python@v5
        with:
          python-version: "3.12"
          cache: pip

      - name: Installer les dépendances
        run: | python -m pip install --upgrade pip pip install -r requirements.txt 
      - name: Restaurer le journal et la mémoire anti-doublons
        uses: actions/cache/restore@v4
        with:
          path: state
          key: trader-ai-pro-state-${{ github.run_id }}
          restore-keys: | trader-ai-pro-state- 
      - name: Vérifier la syntaxe
        run: python -m py_compile strategy.py scheduled_analysis.py trade_journal.py deriv_market.py

      - name: Enregistrer un résultat manuel si demandé
        if: ${{ inputs.journal_signal_id != '' }}
        run: | python - <<'PY' import os, sqlite3, sys from pathlib import Path db_path = Path(os.environ["TRADER_DB_PATH"]) if not db_path.exists(): sys.exit("Base de journal absente : lance d'abord un scan qui enregistre un signal.") signal_id = os.environ["JOURNAL_SIGNAL_ID"].strip() outcome = os.environ.get("JOURNAL_OUTCOME", "OPEN").strip() notes = os.environ.get("JOURNAL_NOTES", "") raw_r = os.environ.get("JOURNAL_RESULT_R", "").strip() result_r = float(raw_r) if raw_r else None if outcome not in {"OPEN", "WIN", "LOSS", "BREAKEVEN", "NOT_TAKEN"}: sys.exit("Résultat invalide.") with sqlite3.connect(db_path) as db: cur = db.execute( "UPDATE signals SET status=?, outcome=?, result_r=?, notes=? WHERE signal_id=?", ("CLOTURE" if outcome in {"WIN", "LOSS", "BREAKEVEN"} else outcome, outcome, result_r, notes, signal_id) ) if cur.rowcount == 0: sys.exit("ID inconnu dans le journal restauré.") db.execute("INSERT INTO run_log(event, detail) VALUES (?, ?)", ("RESULT_UPDATED", f"{signal_id} | {outcome} | R={result_r} | {notes}")) db.commit() print("Résultat manuel enregistré.") PY 
      - name: Analyser les marchés et envoyer les signaux
        if: ${{ inputs.journal_signal_id == '' }}
        run: python -u scheduled_analysis.py

      - name: Sauvegarder journal et anti-doublons
        if: always()
        uses: actions/cache/save@v4
        with:
          path: state
          key: trader-ai-pro-state-${{ github.run_id }}

      - name: Publier une copie du journal comme artefact
        if: always()
        uses: actions/upload-artifact@v4
        with:
          name: trader-ai-pro-journal-${{ github.run_id }}
          path: state/trader_ai_pro.sqlite3
          if-no-files-found: ignore
          retention-days: 30

#!/usr/bin/env python3
"""Trwałe przechowywanie pomiarów ciała użytkownika."""

from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


BASE_DIR = Path(__file__).resolve().parent
DATABASE_PATH = Path(os.getenv("FITMENTOR_DB_PATH", BASE_DIR / ".fitmentor.db"))

SAVE_BODY_MEASUREMENTS_TOOL = {
    "type": "function",
    "function": {
        "name": "save_body_measurements",
        "description": "Zapisuje aktualną masę ciała i podane obwody mięśni w lokalnej bazie FitMentor.",
        "parameters": {
            "type": "object",
            "properties": {
                "weight_kg": {"type": "number", "description": "Masa ciała w kilogramach.", "minimum": 1, "maximum": 500},
                "circumferences_cm": {
                    "type": "object",
                    "description": "Obwody wskazanych mięśni w centymetrach, np. {'biceps': 34.5}.",
                    "additionalProperties": {"type": "number", "minimum": 1, "maximum": 300},
                },
            },
            "additionalProperties": False,
        },
    },
}

GET_BODY_MEASUREMENTS_TOOL = {
    "type": "function",
    "function": {
        "name": "get_body_measurements",
        "description": "Odczytuje najnowsze zapisane pomiary ciała z lokalnej bazy FitMentor.",
        "parameters": {
            "type": "object",
            "properties": {
                "muscle": {"type": "string", "description": "Opcjonalna nazwa mięśnia, np. biceps albo udo."},
                "history_limit": {"type": "integer", "description": "Liczba ostatnich zapisów (1-20).", "minimum": 1, "maximum": 20},
            },
            "additionalProperties": False,
        },
    },
}


def _connect() -> sqlite3.Connection:
    DATABASE_PATH.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(DATABASE_PATH)
    connection.row_factory = sqlite3.Row
    connection.execute(
        """CREATE TABLE IF NOT EXISTS body_measurements (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            recorded_at TEXT NOT NULL,
            weight_kg REAL,
            circumferences_cm TEXT NOT NULL
        )"""
    )
    connection.commit()
    return connection


def _validate_measurements(weight_kg: float | None, circumferences_cm: dict[str, float] | None) -> dict[str, float]:
    if weight_kg is None and not circumferences_cm:
        raise ValueError("Podaj masę ciała albo co najmniej jeden obwód mięśnia.")
    if weight_kg is not None and not 1 <= weight_kg <= 500:
        raise ValueError("Masa musi mieścić się w zakresie 1-500 kg.")
    if circumferences_cm is None:
        return {}
    if not isinstance(circumferences_cm, dict):
        raise ValueError("Obwody muszą być obiektem: nazwa mięśnia -> centymetry.")

    validated: dict[str, float] = {}
    for muscle, circumference in circumferences_cm.items():
        name = str(muscle).strip().lower()
        if not name:
            raise ValueError("Nazwa mięśnia nie może być pusta.")
        if not isinstance(circumference, (int, float)) or not 1 <= circumference <= 300:
            raise ValueError(f"Obwód mięśnia {name} musi mieścić się w zakresie 1-300 cm.")
        validated[name] = round(float(circumference), 1)
    return validated


def save_body_measurements(weight_kg: float | None = None, circumferences_cm: dict[str, float] | None = None) -> dict[str, object]:
    """Zapisuje pojedynczy pomiar i zwraca potwierdzenie."""
    validated_circumferences = _validate_measurements(weight_kg, circumferences_cm)
    recorded_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    with _connect() as connection:
        connection.execute(
            "INSERT INTO body_measurements (recorded_at, weight_kg, circumferences_cm) VALUES (?, ?, ?)",
            (recorded_at, weight_kg, json.dumps(validated_circumferences, ensure_ascii=False)),
        )
    return {"saved": True, "recorded_at": recorded_at, "weight_kg": weight_kg, "circumferences_cm": validated_circumferences}


def get_body_measurements(muscle: str | None = None, history_limit: int = 5) -> dict[str, object]:
    """Zwraca najnowszy stan pomiarów oraz ostatnie zapisy."""
    if not 1 <= history_limit <= 20:
        raise ValueError("history_limit musi mieścić się w zakresie 1-20.")
    muscle = muscle.strip().lower() if muscle else None
    with _connect() as connection:
        rows = connection.execute(
            "SELECT recorded_at, weight_kg, circumferences_cm FROM body_measurements ORDER BY id DESC LIMIT ?",
            (history_limit,),
        ).fetchall()
    if not rows:
        return {"found": False, "message": "Brak zapisanych pomiarów."}

    latest_weight = next((row["weight_kg"] for row in rows if row["weight_kg"] is not None), None)
    latest_circumferences: dict[str, float] = {}
    history: list[dict[str, Any]] = []
    for row in rows:
        circumferences = json.loads(row["circumferences_cm"])
        if muscle:
            circumferences = {muscle: circumferences[muscle]} if muscle in circumferences else {}
        for name, value in circumferences.items():
            latest_circumferences.setdefault(name, value)
        history.append({"recorded_at": row["recorded_at"], "weight_kg": row["weight_kg"], "circumferences_cm": circumferences})
    return {"found": True, "latest": {"weight_kg": latest_weight, "circumferences_cm": latest_circumferences}, "history": history}
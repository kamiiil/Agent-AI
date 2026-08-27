#!/usr/bin/env python3
"""Prosty klient konsolowy OpenRouter Chat Completions API."""

import argparse
import json
import os
import sys
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


API_URL = "https://openrouter.ai/api/v1/chat/completions"
DEFAULT_MODEL = "openai/gpt-4o-mini"


def load_api_key() -> str:
    """Reads API_KEY from the environment or the local env.env file."""
    api_key = os.getenv("OPENROUTER_API_KEY") or os.getenv("API_KEY")
    if api_key:
        return api_key.strip().strip('"').strip("'")

    env_file = Path(__file__).with_name("env.env")
    if env_file.exists():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            name, value = line.split("=", 1)
            if name.strip() in {"OPENROUTER_API_KEY", "API_KEY"}:
                return value.strip().strip('"').strip("'")

    return ""


def ask_openrouter(api_key: str, model: str, messages: list[dict[str, str]], temperature: float) -> str:
    payload = json.dumps(
        {
            "model": model,
            "messages": messages,
            "temperature": temperature,
        }
    ).encode("utf-8")
    request = Request(
        API_URL,
        data=payload,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "http://localhost",
            "X-Title": "Konsolowy klient OpenRouter",
        },
        method="POST",
    )

    try:
        with urlopen(request, timeout=120) as response:
            data = json.loads(response.read().decode("utf-8"))
    except HTTPError as error:
        details = error.read().decode("utf-8", errors="replace")
        try:
            details = json.loads(details).get("error", {}).get("message", details)
        except json.JSONDecodeError:
            pass
        raise RuntimeError(f"OpenRouter zwrócił HTTP {error.code}: {details}") from error
    except URLError as error:
        raise RuntimeError(f"Nie można połączyć się z OpenRouterem: {error.reason}") from error

    try:
        return data["choices"][0]["message"]["content"].strip()
    except (KeyError, IndexError, TypeError) as error:
        raise RuntimeError(f"Nieoczekiwana odpowiedź API: {data}") from error


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Rozmowa z modelem przez OpenRouter API")
    parser.add_argument(
        "-m",
        "--model",
        default=os.getenv("OPENROUTER_MODEL", DEFAULT_MODEL),
        help=f"nazwa modelu OpenRouter (domyślnie: {DEFAULT_MODEL})",
    )
    parser.add_argument(
        "--temperature",
        type=float,
        default=0.7,
        help="temperatura odpowiedzi od 0 do 2 (domyślnie: 0.7)",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if not 0 <= args.temperature <= 2:
        print("Temperatura musi być w zakresie od 0 do 2.", file=sys.stderr)
        return 2

    api_key = load_api_key()
    if not api_key:
        print("Brak klucza API. Ustaw OPENROUTER_API_KEY albo uzupełnij env.env.", file=sys.stderr)
        return 1

    messages: list[dict[str, str]] = []
    print(f"OpenRouter | model: {args.model}")
    print("Wpisz wiadomość. Komendy: /exit, /quit, /clear")

    while True:
        try:
            prompt = input("\nTy: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nDo widzenia!")
            return 0

        if not prompt:
            continue
        if prompt.lower() in {"/exit", "/quit"}:
            print("Do widzenia!")
            return 0
        if prompt.lower() == "/clear":
            messages.clear()
            print("Historia rozmowy wyczyszczona.")
            continue

        messages.append({"role": "user", "content": prompt})
        try:
            answer = ask_openrouter(api_key, args.model, messages, args.temperature)
        except RuntimeError as error:
            messages.pop()
            print(f"Błąd: {error}", file=sys.stderr)
            continue

        messages.append({"role": "assistant", "content": answer})
        print(f"\nModel: {answer}")


if __name__ == "__main__":
    raise SystemExit(main())
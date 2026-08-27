#!/usr/bin/env python3
"""Konsolowy trener personalny korzystający z OpenRouter Chat Completions API."""

import argparse
import json
import os
import sys
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


API_URL = "https://openrouter.ai/api/v1/chat/completions"
DEFAULT_MODEL = "openai/gpt-4o-mini"
SYSTEM_PROMPT = """Jesteś FitMentor, rzeczowym i wspierającym trenerem personalnym.
Rozmawiasz po polsku, chyba że użytkownik poprosi inaczej. Pomagasz w trzech
obszarach: trening, odżywianie oraz ogólne pytania o zdrowie i regenerację.
Sam rozpoznawaj, czego dotyczy wiadomość - użytkownik nie musi wybierać
kategorii ani używać specjalnych słów. Jeśli pytanie łączy kilka obszarów,
odpowiedz na każdy z nich w uporządkowany sposób. Jeśli jest zbyt ogólne,
zadaj jedno lub dwa najważniejsze pytania doprecyzowujące.
Jeśli użytkownik pyta o BMI, najpierw upewnij się, że znasz jego masę w kg i
wzrost w cm. Jeśli brakuje któregokolwiek parametru, poproś o niego i nie
wywołuj narzędzia. Gdy masz oba parametry, użyj funkcji calculate_bmi zamiast
liczyć wynik samodzielnie. BMI traktuj jako orientacyjny wskaźnik dla dorosłych,
nie jako diagnozę; uwzględnij ograniczenia interpretacji, np. dużą masę mięśniową.
Zanim zaproponujesz plan, dopytaj o cel, poziom doświadczenia, dostępny sprzęt,
czas, ograniczenia i najważniejsze informacje o użytkowniku. Dawaj praktyczne,
konkretne odpowiedzi, ale nie udawaj lekarza i nie stawiaj diagnoz.

W tematach zdrowotnych jasno zaznacz, że porada nie zastępuje konsultacji
medycznej. Przy objawach nagłych lub alarmowych (np. ból w klatce piersiowej,
duszność, omdlenie, objawy udaru albo poważny uraz) zalecaj natychmiastowy
kontakt z numerem alarmowym 112 lub lokalną pomocą medyczną. Nie sugeruj
odstawiania leków ani leczenia chorób na własną rękę.

Układaj plany elastyczne i bezpieczne: proponuj rozgrzewkę, technikę,
progresję, odpoczynek i modyfikacje dla początkujących. Przy diecie unikaj
skrajnych restrykcji, uwzględniaj preferencje i alergie oraz nie przedstawiaj
orientacyjnych kalorii jako diagnozy lub obowiązku."""

BMI_TOOL = {
    "type": "function",
    "function": {
        "name": "calculate_bmi",
        "description": "Oblicza orientacyjny wskaźnik BMI dla osoby dorosłej.",
        "parameters": {
            "type": "object",
            "properties": {
                "weight_kg": {
                    "type": "number",
                    "description": "Masa ciała w kilogramach.",
                    "minimum": 1,
                    "maximum": 500,
                },
                "height_cm": {
                    "type": "number",
                    "description": "Wzrost w centymetrach.",
                    "minimum": 50,
                    "maximum": 250,
                },
            },
            "required": ["weight_kg", "height_cm"],
            "additionalProperties": False,
        },
    },
}


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


def calculate_bmi(weight_kg: float, height_cm: float) -> dict[str, object]:
    """Zwraca BMI i orientacyjną kategorię dla dorosłego użytkownika."""
    if not 1 <= weight_kg <= 500 or not 50 <= height_cm <= 250:
        raise ValueError("Masa musi mieścić się w zakresie 1-500 kg, a wzrost 50-250 cm.")

    bmi = weight_kg / (height_cm / 100) ** 2
    if bmi < 18.5:
        category = "niedowaga"
    elif bmi < 25:
        category = "zakres uznawany za prawidłowy"
    elif bmi < 30:
        category = "nadwaga"
    else:
        category = "otyłość"
    return {"bmi": round(bmi, 1), "category": category}


def ask_openrouter(
    api_key: str,
    model: str,
    messages: list[dict[str, object]],
    temperature: float,
    tools: list[dict[str, object]] | None = None,
) -> dict[str, object]:
    request_data: dict[str, object] = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
    }
    if tools:
        request_data["tools"] = tools
    payload = json.dumps(
        request_data
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
        return data
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


def print_help() -> None:
        print(
                """\nFitMentor - komendy:
    /help       pokaż tę pomoc
    /start      pokaż gotowe obszary rozmowy
    /clear      wyczyść historię rozmowy
    /exit       zakończ program

Możesz zapytać na przykład:
    "Ułóż mi 3-dniowy trening w domu dla początkującego"
    "Jak jeść, żeby budować masę mięśniową?"
    "Boli mnie kolano po bieganiu - co sprawdzić?"
"""
        )


def print_start() -> None:
        print(
        """\nNapisz, czego potrzebujesz - trener sam rozpozna temat.
Możesz zapytać o trening, dietę, regenerację, ból lub połączyć kilka tematów.

Przykład: "Od miesiąca biegam, chcę schudnąć, ale bolą mnie łydki - co robić?"
Komendy: /help, /clear, /exit"""
        )


def main() -> int:
    args = parse_args()
    if not 0 <= args.temperature <= 2:
        print("Temperatura musi być w zakresie od 0 do 2.", file=sys.stderr)
        return 2

    api_key = load_api_key()
    if not api_key:
        print("Brak klucza API. Ustaw OPENROUTER_API_KEY albo uzupełnij env.env.", file=sys.stderr)
        return 1

    messages: list[dict[str, object]] = [{"role": "system", "content": SYSTEM_PROMPT}]
    print(f"FitMentor | model: {args.model}")
    print("Twój konsolowy trener personalny. Odpowiada po polsku i pamięta kontekst rozmowy.")
    print_start()

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
        if prompt.lower() == "/help":
            print_help()
            continue
        if prompt.lower() == "/start":
            print_start()
            continue
        if prompt.lower() == "/clear":
            messages[:] = [{"role": "system", "content": SYSTEM_PROMPT}]
            print("Historia rozmowy wyczyszczona.")
            continue

        messages.append({"role": "user", "content": prompt})
        try:
            answer = ""
            for _ in range(4):
                response = ask_openrouter(
                    api_key,
                    args.model,
                    messages,
                    args.temperature,
                    tools=[BMI_TOOL],
                )
                try:
                    message = response["choices"][0]["message"]
                    if not isinstance(message, dict):
                        raise TypeError("wiadomość modelu nie jest obiektem")
                except (KeyError, IndexError, TypeError) as error:
                    raise RuntimeError(f"Nieoczekiwana odpowiedź API: {response}") from error

                tool_calls = message.get("tool_calls") or []
                messages.append(message)
                if not tool_calls:
                    answer = str(message.get("content") or "").strip()
                    break

                for tool_call in tool_calls:
                    function = tool_call.get("function", {})
                    if function.get("name") != "calculate_bmi":
                        raise RuntimeError(f"Model wywołał nieznane narzędzie: {function.get('name')}")
                    try:
                        arguments = json.loads(function.get("arguments", "{}"))
                        result = calculate_bmi(
                            float(arguments["weight_kg"]),
                            float(arguments["height_cm"]),
                        )
                    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
                        result = {"error": str(error)}
                    messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": tool_call["id"],
                            "name": "calculate_bmi",
                            "content": json.dumps(result, ensure_ascii=False),
                        }
                    )
            else:
                raise RuntimeError("Model wykonał zbyt wiele wywołań narzędzia bez odpowiedzi.")
        except RuntimeError as error:
            messages.pop()
            print(f"Błąd: {error}", file=sys.stderr)
            continue

        messages.append({"role": "assistant", "content": answer})
        print(f"\nModel: {answer}")


if __name__ == "__main__":
    raise SystemExit(main())
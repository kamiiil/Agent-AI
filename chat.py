#!/usr/bin/env python3
"""Konsolowy trener personalny korzystający z OpenRouter Chat Completions API."""

import argparse
import json
import os
import sys
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

import anyio
from mcp.client.session import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client


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
Jeśli użytkownik pyta o produkt spożywczy, jego kalorie, makro, skład lub
alergeny, użyj funkcji analyze_product. Przyjmij nazwę produktu albo kod
kreskowy. Po otrzymaniu danych z narzędzia zinterpretuj je w kontekście celu
użytkownika, ale nie wymyślaj brakujących wartości i zaznacz, gdy dane są
niepełne. Wartości odżywcze podawaj przede wszystkim na 100 g lub 100 ml.
Zanim zaproponujesz plan, dopytaj o cel, poziom doświadczenia, dostępny sprzęt,
czas, ograniczenia i najważniejsze informacje o użytkowniku. Dawaj praktyczne,
konkretne odpowiedzi, ale nie udawaj lekarza i nie stawiaj diagnoz.

W tematach zdrowotnych jasno zaznacz, że porada nie zastępuje konsultacji
medycznej. Przy objawach nagłych lub alarmowych (np. ból w klatce piersiowej,
duszność, omdlenie, objawy udaru albo poważny uraz) zalecaj natychmiastowy
kontakt z numerem alarmowym 112 lub lokalną pomocą medyczną. Nie sugeruj
odstawiania leków ani leczenia chorób na własną rękę.

Jeśli pytanie dotyczy własnych materiałów FitMentor, zasad treningu, odżywiania
lub regeneracji, użyj funkcji search_knowledge_base. Opieraj odpowiedź na
znalezionych materiałach i podaj ich nazwy. Jeśli baza nie zawiera odpowiedzi,
powiedz o tym wprost i dopiero wtedy udziel ostrożnej odpowiedzi ogólnej.

Jeśli użytkownik podaje aktualną masę ciała lub obwód mięśnia, zapisz te dane
przez save_body_measurements. Jeśli pyta o swoje wcześniejsze pomiary, trend,
masę lub obwód, najpierw użyj get_body_measurements. Nie twórz i nie zgaduj
pomiarów, których użytkownik nie podał.

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

PRODUCT_TOOL = {
    "type": "function",
    "function": {
        "name": "analyze_product",
        "description": "Pobiera z OpenFoodFacts informacje o produkcie spożywczym po kodzie kreskowym albo nazwie.",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Kod kreskowy produktu albo jego nazwa.",
                    "minLength": 2,
                }
            },
            "required": ["query"],
            "additionalProperties": False,
        },
    },
}


def measurement_read_requested(prompt: str) -> bool:
    """Rozpoznaje pytania, przy których agent musi odczytać zapisane pomiary."""
    normalized = prompt.lower()
    read_terms = (
        "moja masa", "aktualna masa", "ile ważę", "ile waze", "moje pomiary",
        "obwód", "obwod", "historia pomiarów", "historia pomiarow", "trend masy",
    )
    return any(term in normalized for term in read_terms) and "zapisz" not in normalized


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


def openfoodfacts_get(paths: list[str]) -> dict[str, object]:
    """Pobiera JSON z ponowieniem po chwilowej niedostępności usługi."""
    last_error: Exception | None = None
    for path in paths:
        for attempt in range(3):
            request = Request(path, headers={"User-Agent": "FitMentor/1.0 (nutrition assistant)"})
            try:
                with urlopen(request, timeout=15) as response:
                    data = json.loads(response.read().decode("utf-8"))
                if not isinstance(data, dict):
                    raise RuntimeError("OpenFoodFacts zwrócił nieprawidłową odpowiedź.")
                return data
            except HTTPError as error:
                last_error = error
                if error.code not in {429, 500, 502, 503, 504}:
                    raise RuntimeError(f"OpenFoodFacts zwrócił HTTP {error.code}.") from error
            except (URLError, json.JSONDecodeError, RuntimeError) as error:
                last_error = error
            if attempt < 2:
                time.sleep(1 + attempt)
    raise RuntimeError(
        "OpenFoodFacts jest chwilowo niedostępny (503). Spróbuj ponownie za chwilę."
    ) from last_error


def analyze_product(query: str) -> dict[str, object]:
    """Pobiera najważniejsze dane żywieniowe z OpenFoodFacts."""
    print(f"Pobieranie danych o produkcie: {query}", file=sys.stderr)
    query = query.strip()
    if not query:
        raise ValueError("Podaj nazwę produktu albo kod kreskowy.")

    if query.isdigit():
        paths = [
            f"https://world.openfoodfacts.org/api/v2/product/{quote(query)}.json",
            f"https://openfoodfacts.org/api/v2/product/{quote(query)}.json",
        ]
        payload = openfoodfacts_get(paths)
        products = [payload.get("product", {})] if payload.get("status") == 1 else []
    else:
        suffix = (
            "cgi/search.pl?"
            f"search_terms={quote(query)}&search_simple=1&action=process&json=1&page_size=5"
        )
        payload = openfoodfacts_get([
            f"https://world.openfoodfacts.org/{suffix}",
            f"https://openfoodfacts.org/{suffix}",
        ])
        products = payload.get("products", [])

    if not products:
        return {"found": False, "query": query, "message": "Nie znaleziono produktu."}

    product = products[0]
    nutrients = product.get("nutriments", {})
    nutrient_keys = {
        "energy_kcal_100g": "energy-kcal_100g",
        "protein_g_100g": "proteins_100g",
        "carbohydrates_g_100g": "carbohydrates_100g",
        "sugars_g_100g": "sugars_100g",
        "fat_g_100g": "fat_100g",
        "saturated_fat_g_100g": "saturated-fat_100g",
        "fiber_g_100g": "fiber_100g",
        "salt_g_100g": "salt_100g",
    }
    nutrition = {
        name: nutrients[key]
        for name, key in nutrient_keys.items()
        if nutrients.get(key) is not None
    }
    return {
        "found": True,
        "product_name": product.get("product_name") or product.get("product_name_pl") or "Nieznany produkt",
        "brand": product.get("brands", ""),
        "barcode": product.get("code"),
        "serving_size": product.get("serving_size"),
        "nutrition_per_100g": nutrition,
        "ingredients": product.get("ingredients_text_pl") or product.get("ingredients_text"),
        "allergens": product.get("allergens_tags", []),
        "nutriscore": product.get("nutriscore_grade"),
        "nova_group": product.get("nova_group"),
    }


def list_mcp_tools() -> list[dict[str, object]]:
    """Zwraca listę narzędzi z uruchomionego serwera MCP."""

    async def _run() -> list[dict[str, object]]:
        params = StdioServerParameters(
            command=sys.executable,
            args=["mcp_server.py"],
            cwd=str(Path(__file__).resolve().parent),
        )
        async with stdio_client(params) as (read_stream, write_stream):
            async with ClientSession(read_stream, write_stream) as session:
                await session.initialize()
                response = await session.list_tools()
                return [
                    {
                        "type": "function",
                        "function": {
                            "name": tool.name,
                            "description": tool.description or "",
                            "parameters": getattr(tool, "input_schema", None) or {"type": "object", "properties": {}},
                        },
                    }
                    for tool in response.tools
                ]

    return anyio.run(_run, backend="trio")


def call_mcp_tool(tool_name: str, arguments: dict[str, object]) -> dict[str, object]:
    """Wywołuje narzędzie serwera MCP i zwraca jego structured_content."""

    async def _run() -> dict[str, object]:
        params = StdioServerParameters(
            command=sys.executable,
            args=["mcp_server.py"],
            cwd=str(Path(__file__).resolve().parent),
        )
        async with stdio_client(params) as (read_stream, write_stream):
            async with ClientSession(read_stream, write_stream) as session:
                await session.initialize()
                response = await session.call_tool(tool_name, arguments)
                if response.structured_content is not None:
                    return dict(response.structured_content)

                text_parts: list[str] = []
                for item in response.content:
                    if hasattr(item, "text"):
                        text_parts.append(str(item.text))
                return {"content": "".join(text_parts)}

    return anyio.run(_run, backend="trio")


def ask_openrouter(
    api_key: str,
    model: str,
    messages: list[dict[str, object]],
    temperature: float,
    tools: list[dict[str, object]] | None = None,
    tool_choice: dict[str, object] | None = None,
) -> dict[str, object]:
    request_data: dict[str, object] = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
    }
    if tools:
        request_data["tools"] = tools
    if tool_choice:
        request_data["tool_choice"] = tool_choice
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
            mcp_tools = list_mcp_tools()
            for _ in range(4):
                tool_choice = None
                if _ == 0 and measurement_read_requested(prompt):
                    tool_choice = {
                        "type": "function",
                        "function": {"name": "get_body_measurements"},
                    }
                response = ask_openrouter(
                    api_key,
                    args.model,
                    messages,
                    args.temperature,
                    tools=mcp_tools,
                    tool_choice=tool_choice,
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
                    tool_name = function.get("name")
                    try:
                        arguments = json.loads(function.get("arguments", "{}"))
                        if tool_name is None:
                            raise ValueError("Model nie podał nazwy narzędzia.")
                        result = call_mcp_tool(tool_name, arguments)
                    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
                        result = {"error": str(error)}
                    messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": tool_call["id"],
                            "name": tool_name,
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
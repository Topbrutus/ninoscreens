#!/usr/bin/env python3
"""
nino_ai.py — Fabrication automatique IA pour Ninoscreens
Usage :
    python3 nino_ai.py "ajoute un bouton mute dans RunWorkspace"
    python3 nino_ai.py --patch app/widgets/run_workspace.py "fix le bug du double parecord"
    python3 nino_ai.py --new app/widgets/mon_widget.py "widget volume slider PySide6"
    python3 nino_ai.py --chat   (mode conversation interactif)

Requiert : pip install anthropic
Config    : export ANTHROPIC_API_KEY=sk-...
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

# ── Couleurs terminal ───────────────────────────────────────────────────────
RESET  = "\033[0m"
BOLD   = "\033[1m"
CYAN   = "\033[96m"
GREEN  = "\033[92m"
YELLOW = "\033[93m"
RED    = "\033[91m"
DIM    = "\033[2m"

def c(text: str, color: str) -> str:
    return f"{color}{text}{RESET}"

# ── Contexte projet ─────────────────────────────────────────────────────────
PROJECT_ROOT = Path(__file__).parent

CONTEXT_FILES = [
    "app/config.py",
    "app/state.py",
    "app/session_store.py",
    "app/user_config.py",
    "app/web_profile.py",
    "main.py",
]

SYSTEM_PROMPT = """\
Tu es un expert Python / PySide6 / Qt intégré dans le projet Ninoscreens.
Ninoscreens est une application Linux desktop : un tableau de bord multi-tuiles
de navigateurs web (QWebEngineView), avec vue focus, split-view, workspace RUN
(voice + CLI), session persistante et profil web partagé.

Règles de fabrication :
- Code Python 3.13 strict, PySide6, annotations complètes.
- Pas de commentaires inutiles, pas de TODO, code prêt à copier-coller.
- Si tu modifies un fichier existant, montre UNIQUEMENT les blocs changés avec
  contexte (3 lignes avant/après), format diff ou bloc python clairement délimité.
- Si tu crées un nouveau fichier, donne le fichier entier.
- Réponds en français.
- Ne répète pas la question. Va directement au code.
"""

def _load_context() -> str:
    """Charge les fichiers de contexte du projet dans le prompt."""
    parts: list[str] = []
    for rel in CONTEXT_FILES:
        path = PROJECT_ROOT / rel
        if path.exists():
            content = path.read_text(encoding="utf-8", errors="replace")
            parts.append(f"### {rel}\n```python\n{content}\n```")
    return "\n\n".join(parts)

def _load_file(path: Path) -> str:
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8", errors="replace")

# ── Appel API ───────────────────────────────────────────────────────────────
def ask_claude(messages: list[dict], *, stream: bool = True) -> str:
    try:
        import anthropic
    except ImportError:
        print(c("✗ Module 'anthropic' manquant. Lance :", RED))
        print(c("  pip install anthropic", YELLOW))
        sys.exit(1)

    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        print(c("✗ Variable ANTHROPIC_API_KEY non définie.", RED))
        print(c("  export ANTHROPIC_API_KEY=sk-ant-...", YELLOW))
        sys.exit(1)

    client = anthropic.Anthropic(api_key=api_key)

    if stream:
        print()
        full = ""
        with client.messages.stream(
            model="claude-sonnet-4-20250514",
            max_tokens=4096,
            system=SYSTEM_PROMPT,
            messages=messages,
        ) as s:
            for text in s.text_stream:
                print(text, end="", flush=True)
                full += text
        print()
        return full
    else:
        resp = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=4096,
            system=SYSTEM_PROMPT,
            messages=messages,
        )
        return resp.content[0].text

# ── Modes ────────────────────────────────────────────────────────────────────
def mode_simple(prompt: str) -> None:
    """Demande simple avec contexte projet injecté."""
    context = _load_context()
    user_msg = f"Contexte projet Ninoscreens :\n\n{context}\n\n---\n\nDemande : {prompt}"
    print(c(f"\n● Ninoscreens AI", BOLD + CYAN) + c(f"  — {prompt[:60]}...", DIM))
    print(c("─" * 60, DIM))
    ask_claude([{"role": "user", "content": user_msg}])


def mode_patch(file_path: str, prompt: str) -> None:
    """Patch un fichier existant."""
    path = PROJECT_ROOT / file_path
    content = _load_file(path)
    if not content:
        print(c(f"✗ Fichier introuvable : {path}", RED))
        sys.exit(1)

    context = _load_context()
    user_msg = (
        f"Contexte projet :\n\n{context}\n\n"
        f"---\n\n"
        f"Fichier à modifier : `{file_path}`\n"
        f"```python\n{content}\n```\n\n"
        f"Modification demandée : {prompt}\n\n"
        f"Montre uniquement les blocs modifiés avec 3 lignes de contexte."
    )
    print(c(f"\n● PATCH", BOLD + YELLOW) + c(f"  {file_path}", CYAN))
    print(c("─" * 60, DIM))
    result = ask_claude([{"role": "user", "content": user_msg}])
    _offer_apply(path, result)


def mode_new(file_path: str, prompt: str) -> None:
    """Crée un nouveau fichier."""
    path = PROJECT_ROOT / file_path
    context = _load_context()
    user_msg = (
        f"Contexte projet :\n\n{context}\n\n"
        f"---\n\n"
        f"Crée le fichier `{file_path}` : {prompt}\n\n"
        f"Donne le fichier Python complet, prêt à copier."
    )
    print(c(f"\n● NOUVEAU FICHIER", BOLD + GREEN) + c(f"  {file_path}", CYAN))
    print(c("─" * 60, DIM))
    result = ask_claude([{"role": "user", "content": user_msg}])
    _offer_write(path, result)


def mode_chat() -> None:
    """Mode conversation interactif."""
    context = _load_context()
    history: list[dict] = []
    print(c("\n● Ninoscreens AI — Mode chat", BOLD + CYAN))
    print(c("  Tape 'exit' ou Ctrl-C pour quitter.\n", DIM))

    # Injecter le contexte au premier tour
    system_context = f"Contexte projet Ninoscreens :\n\n{context}"

    while True:
        try:
            user_input = input(c("toi> ", BOLD + CYAN)).strip()
        except (KeyboardInterrupt, EOFError):
            print(c("\nAu revoir.", DIM))
            break

        if not user_input or user_input.lower() in {"exit", "quit", "q"}:
            print(c("Au revoir.", DIM))
            break

        # Premier message : coller le contexte projet
        if not history:
            content = f"{system_context}\n\n---\n\n{user_input}"
        else:
            content = user_input

        history.append({"role": "user", "content": content})
        print(c("nino> ", BOLD + GREEN), end="", flush=True)
        reply = ask_claude(history)
        history.append({"role": "assistant", "content": reply})


# ── Helpers write ────────────────────────────────────────────────────────────
def _extract_code_block(text: str) -> str:
    """Extrait le premier bloc ```python ... ``` de la réponse."""
    import re
    m = re.search(r"```(?:python)?\n(.*?)```", text, re.DOTALL)
    return m.group(1).strip() if m else text.strip()


def _offer_write(path: Path, response: str) -> None:
    code = _extract_code_block(response)
    print(c(f"\n─── Écrire dans {path} ? [o/N] : ", YELLOW), end="")
    try:
        ans = input().strip().lower()
    except (KeyboardInterrupt, EOFError):
        ans = "n"
    if ans in {"o", "oui", "y", "yes"}:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(code, encoding="utf-8")
        print(c(f"✓ Fichier écrit : {path}", GREEN))
    else:
        print(c("✗ Annulé.", DIM))


def _offer_apply(path: Path, response: str) -> None:
    print(c(f"\n─── Appliquer le patch à {path} manuellement (le diff est au-dessus).", DIM))
    print(c("    Copie les blocs modifiés dans ton éditeur.", DIM))


# ── CLI ──────────────────────────────────────────────────────────────────────
def main() -> None:
    parser = argparse.ArgumentParser(
        prog="nino_ai",
        description="Fabrication automatique IA pour Ninoscreens",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("prompt", nargs="?", help="Demande en français")
    parser.add_argument("--patch", metavar="FICHIER", help="Patcher un fichier existant")
    parser.add_argument("--new",   metavar="FICHIER", help="Créer un nouveau fichier")
    parser.add_argument("--chat",  action="store_true", help="Mode conversation interactif")

    args = parser.parse_args()

    if args.chat:
        mode_chat()
    elif args.patch:
        if not args.prompt:
            parser.error("--patch nécessite une demande. Ex: --patch app/widgets/run_workspace.py 'fix bug'")
        mode_patch(args.patch, args.prompt)
    elif args.new:
        if not args.prompt:
            parser.error("--new nécessite une description.")
        mode_new(args.new, args.prompt)
    elif args.prompt:
        mode_simple(args.prompt)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()

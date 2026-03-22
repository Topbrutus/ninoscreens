
from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Callable, Mapping


class CommandOutcome(str, Enum):
    SUCCESS = "success"
    BLOCKED = "blocked"
    ERROR = "error"


@dataclass(frozen=True)
class AgentCommand:
    name: str
    tile_number: int | None = None
    url: str = ""
    payload: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_mapping(cls, mapping: Mapping[str, Any]) -> "AgentCommand":
        payload = dict(mapping)
        name = str(payload.pop("name", "")).strip()
        tile_number_raw = payload.pop("tile_number", None)
        url = str(payload.pop("url", "")).strip()

        tile_number = None
        if tile_number_raw is not None:
            try:
                tile_number = int(tile_number_raw)
            except (TypeError, ValueError):
                tile_number = None

        return cls(
            name=name,
            tile_number=tile_number,
            url=url,
            payload=payload,
        )


@dataclass(frozen=True)
class ActionRecord:
    action_id: int
    timestamp: str
    command_name: str
    outcome: CommandOutcome
    message: str
    tile_number: int | None = None
    human_validation_required: bool = False
    details: dict[str, Any] = field(default_factory=dict)


class BlockedAction(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        human_validation_required: bool = False,
        details: Mapping[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.human_validation_required = human_validation_required
        self.details = dict(details or {})


Handler = Callable[[AgentCommand], dict[str, Any] | None]
ActivityCallback = Callable[[ActionRecord], None]


class AgentCockpitController:
    """
    Structured direct-control surface for the cockpit.

    It centralizes validation, traces every action, and distinguishes
    between normal errors and operational blockages that need visibility.
    """

    def __init__(
        self,
        *,
        tile_count: int,
        handlers: Mapping[str, Handler],
        activity_callback: ActivityCallback | None = None,
        max_history: int = 100,
    ) -> None:
        self._tile_count = tile_count
        self._handlers = dict(handlers)
        self._activity_callback = activity_callback
        self._history: deque[ActionRecord] = deque(maxlen=max_history)
        self._next_action_id = 1

    def execute(self, command: AgentCommand | Mapping[str, Any]) -> ActionRecord:
        agent_command = command if isinstance(command, AgentCommand) else AgentCommand.from_mapping(command)
        action_id = self._next_action_id
        self._next_action_id += 1
        timestamp = datetime.now().isoformat(timespec="seconds")

        try:
            details = self._dispatch(agent_command)
            message = self._build_success_message(agent_command, details)
            record = ActionRecord(
                action_id=action_id,
                timestamp=timestamp,
                command_name=agent_command.name,
                outcome=CommandOutcome.SUCCESS,
                message=message,
                tile_number=agent_command.tile_number,
                human_validation_required=False,
                details=details or {},
            )
        except BlockedAction as exc:
            record = ActionRecord(
                action_id=action_id,
                timestamp=timestamp,
                command_name=agent_command.name,
                outcome=CommandOutcome.BLOCKED,
                message=exc.message,
                tile_number=agent_command.tile_number,
                human_validation_required=exc.human_validation_required,
                details=exc.details,
            )
        except Exception as exc:  # pragma: no cover - defensive runtime guard
            record = ActionRecord(
                action_id=action_id,
                timestamp=timestamp,
                command_name=agent_command.name,
                outcome=CommandOutcome.ERROR,
                message=f"Erreur interne : {exc}",
                tile_number=agent_command.tile_number,
                human_validation_required=True,
                details={},
            )

        self._history.appendleft(record)
        if self._activity_callback is not None:
            self._activity_callback(record)
        return record

    def open_url(self, tile_number: int, url: str) -> ActionRecord:
        return self.execute(AgentCommand(name="open_url", tile_number=tile_number, url=url))

    def focus_tile(self, tile_number: int) -> ActionRecord:
        return self.execute(AgentCommand(name="focus_tile", tile_number=tile_number))

    def close_tile(self, tile_number: int) -> ActionRecord:
        return self.execute(AgentCommand(name="close_tile", tile_number=tile_number))

    def load_memory(self, tile_number: int) -> ActionRecord:
        return self.execute(AgentCommand(name="load_memory", tile_number=tile_number))

    def read_state(self) -> ActionRecord:
        return self.execute(AgentCommand(name="read_state"))

    def report_blocked(
        self,
        message: str,
        *,
        tile_number: int | None = None,
        human_validation_required: bool = True,
        details: Mapping[str, Any] | None = None,
    ) -> ActionRecord:
        command = AgentCommand(
            name="report_blocked",
            tile_number=tile_number,
            payload={
                "message": message,
                "human_validation_required": human_validation_required,
                "details": dict(details or {}),
            },
        )
        return self.execute(command)

    def recent_activity(self, limit: int = 20) -> list[ActionRecord]:
        return list(self._history)[: max(1, limit)]

    def _dispatch(self, command: AgentCommand) -> dict[str, Any] | None:
        normalized_name = command.name.strip().lower()
        if not normalized_name:
            raise BlockedAction(
                "Commande vide : nom requis.",
                human_validation_required=True,
                details={"reason": "missing_command_name"},
            )

        if normalized_name in {"open_url", "focus_tile", "close_tile", "load_memory"}:
            self._validate_tile_number(command.tile_number)

        if normalized_name == "report_blocked":
            raise BlockedAction(
                str(command.payload.get("message", "Blocage signalé.")),
                human_validation_required=bool(command.payload.get("human_validation_required", True)),
                details=command.payload.get("details", {}),
            )

        handler = self._handlers.get(normalized_name)
        if handler is None:
            raise BlockedAction(
                f"Commande inconnue : {command.name}.",
                human_validation_required=True,
                details={"reason": "unknown_command"},
            )

        result = handler(command)
        return dict(result or {})

    def _validate_tile_number(self, tile_number: int | None) -> None:
        if tile_number is None:
            raise BlockedAction(
                "Numéro de carreau requis.",
                human_validation_required=True,
                details={"reason": "missing_tile_number"},
            )
        if not 1 <= tile_number <= self._tile_count:
            raise BlockedAction(
                f"Carreau {tile_number} invalide. Utiliser un numéro entre 1 et {self._tile_count}.",
                human_validation_required=True,
                details={"reason": "invalid_tile_number", "tile_count": self._tile_count},
            )

    def _build_success_message(
        self,
        command: AgentCommand,
        details: Mapping[str, Any] | None,
    ) -> str:
        tile_suffix = f" dans le carreau {command.tile_number}" if command.tile_number is not None else ""
        details = details or {}
        custom_message = str(details.get("message", "")).strip()
        if custom_message:
            return custom_message

        match command.name:
            case "open_url":
                return f"URL ouverte{tile_suffix}."
            case "focus_tile":
                return f"Carreau {command.tile_number} mis en focus."
            case "close_tile":
                return f"Carreau {command.tile_number} fermé."
            case "load_memory":
                return f"Page mémorisée rechargée{tile_suffix}."
            case "read_state":
                return "État complet des carreaux lu."
            case _:
                return f"Commande {command.name} exécutée."

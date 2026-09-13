"""Regression guard: every handler parameter must be injectable.

aiogram passes the event as the first positional argument and fills the rest
from workflow data / known context. A handler that asks for something that is
never injected (e.g. a service we forgot to pass to ``start_polling``) fails at
runtime only when that update arrives. This test catches it at commit time.
"""

from __future__ import annotations

import inspect

from bot.handlers import routers

# Keys provided by aiogram plus our workflow data (see bot/main.py).
INJECTABLE = {
    "message",
    "callback_query",
    "event",
    "bot",
    "dispatcher",
    "state",
    "settings",
    "job_manager",
    "file_manager",
    "scraper",
    "event_from_user",
    "event_chat",
    "event_update",
    "event_context",
    "raw_state",
    "fsm_storage",
    "chat",
    "user",
}


def test_all_handler_params_injectable() -> None:
    missing: list[str] = []
    for router in routers:
        for observer in router.observers.values():
            for handler in getattr(observer, "handlers", []):
                callback = handler.callback
                params = list(inspect.signature(callback).parameters.values())
                for index, param in enumerate(params):
                    if index == 0:  # event, passed positionally
                        continue
                    if param.name in INJECTABLE:
                        continue
                    if param.default is not inspect.Parameter.empty:
                        continue
                    missing.append(f"{router.name}.{callback.__name__}: {param.name}")
    assert not missing, "Un-injected handler parameters: " + ", ".join(missing)

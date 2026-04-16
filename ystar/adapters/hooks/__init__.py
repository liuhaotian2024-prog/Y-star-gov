# ystar/adapters/hooks/__init__.py
"""
Y*gov Hook Extensions — Lifecycle event hooks for governance injection.

Available hooks:
- stop_hook: UserPromptSubmit lifecycle hook (injects K9-RT warnings)
"""
from ystar.adapters.hooks.stop_hook import inject_warnings_to_session

__all__ = ["inject_warnings_to_session"]

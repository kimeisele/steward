"""
Steward Interfaces — Universal I/O for the superagent.

Each interface connects the same StewardAgent to a different
input/output channel. The agent doesn't know or care which
interface it's talking through.

Available:
    CLI      — steward/__main__.py (default)
    Telegram — steward/interfaces/telegram.py
"""

"""MCP control surface for the video studio (M21).

Any MCP-capable LLM client — Claude Desktop, Claude Code, or anything else
speaking the Model Context Protocol — can drive the studio: projects,
generation (video/image/music/VFX), storyboards, avatar renders.

The server is a CLIENT of the studio's HTTP API, never an alternative
backend: every compliance gate (C1–C6) stays enforced server-side, and the
human-judgement actions (publish, consent, asset approval) are deliberately
NOT exposed as tools.
"""

"""Voice stage (factory stage 5a): story.json narration -> ElevenLabs voiceover + word timings.

    from factory.voice import synthesize
    synthesize("episodes/x/story.json", "episodes/x/audio")  # REST, needs ELEVENLABS_API_KEY

See stage.py for the pipeline, backends.py for REST / MCP-import / offline, voices.json for voices.
"""
from .stage import mcp_plan, resolve_voice, synthesize  # noqa: F401

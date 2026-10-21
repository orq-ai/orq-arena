"""Harbor agent that lets codex talk to the orq router.

Loaded by the ``harbor`` process (``-a orq_codex:OrqCodex``, this directory on
its PYTHONPATH), never imported by orq-arena itself. Harbor strips the provider
prefix from the model name (``openai/gpt-6-luna`` becomes ``gpt-6-luna``), and the
router's Responses endpoint rejects a bare model name with HTTP 400, after which
codex retries silently forever. This restores the prefix on the codex command.
"""

from harbor.agents.installed.codex import Codex


class OrqCodex(Codex):
    async def exec_as_agent(self, environment, command, *args, **kwargs):
        if self.model_name and "codex exec" in command:
            bare = self.model_name.split("/")[-1]
            command = command.replace(f"--model {bare} ", f"--model {self.model_name} ", 1)
        return await super().exec_as_agent(environment, command, *args, **kwargs)

"""Probe: does gemma-4-31b emit tool names in plan steps when asked directly?"""
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.chdir(Path(__file__).resolve().parent.parent)

from backend.agent.inference.router import InferenceRouter
from backend.iris_config import load_config


def main() -> int:
    cfg = load_config()
    router = InferenceRouter(cfg)
    # Bind reasoning to cerebras like the live driver did.
    router.bind_role("reasoning", "cerebras", model_override="gemma-4-31b")
    inst = router.resolve("reasoning")
    print(f"resolved: id={inst.id} kind={inst.kind} model={inst.model}")

    prompt = (
        'Respond with JSON only. Plan 3 steps. Each step MUST set "tool" to one '
        'of these EXACT names: list_directory, read_file, get_system_info.\n'
        '{"strategy":"do_it_myself","plan_title":"probe","reasoning":"x",'
        '"steps":[{"step_id":"s1","step_number":1,"description":"list the dir",'
        '"tool":"list_directory","params":{},"depends_on":[],"critical":true},'
        '{"step_id":"s2","step_number":2,"description":"read a file",'
        '"tool":"read_file","params":{},"depends_on":[],"critical":true},'
        '{"step_id":"s3","step_number":3,"description":"get system info",'
        '"tool":"get_system_info","params":{},"depends_on":[],"critical":true}]}'
    )
    print("calling router.generate...")
    text, think, tools = router.generate(
        "reasoning",
        [{"role": "user", "content": prompt}],
        max_tokens=1024,
        temperature=0.0,
    )
    print("RAW:", (text or "")[:1500])
    print("TOOL_CALLS:", tools)
    return 0


if __name__ == "__main__":
    sys.exit(main())

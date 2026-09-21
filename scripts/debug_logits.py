"""Debug the code: print RAW row logits for top first-tokens of a small set."""
import sys
sys.path.insert(0, r"C:\dev\IRISVOICE")

from backend.agent.decision_engine import DecisionEngine, EngineConfig


def main():
    e = DecisionEngine(EngineConfig())
    e.decide("tool_choice", ["NONE", "DELEGATE"], {"goal": "warm"})
    assert e._llm is not None
    MENU = ["read_file", "list_directory", "recall_memory",
            "vision_analyze_screen", "NONE", "DELEGATE"]
    head = (
        "Choose the best tool for each task. Answer with the exact tool name.\n\n"
        "Task: read the file README\n"
        "Options: crawler_query, read_file, speak, NONE\n"
        "Answer: read_file\n\n"
        "Task: find the current price of a product online\n"
        "Options: crawler_query, read_file, speak, NONE\n"
        "Answer: crawler_query\n\n"
    )
    tail = ("Task (tool_choice): recall what we discussed about the crawler\n"
            "Available options:\n"
            "- read_file\n- list_directory\n- recall_memory\n"
            "- vision_analyze_screen\n- NONE\n- DELEGATE\nAnswer:")
    prompt = head + tail
    toks = e._llm.tokenize(prompt.encode(), add_bos=True)
    e._llm.reset()
    e._llm.eval(toks)
    scores = e._llm.scores
    import numpy as np
    print(f"n_tokens={len(toks)} scores_shape={getattr(scores, 'shape', None)}"
          f" len={len(scores) if scores is not None else None}")
    last = scores[len(toks) - 1]
    import numpy as np
    row = scores[len(toks) - 1]
    print(f"  row[{len(toks)-1}] max={float(np.max(row)):.3f} "
          f"mean={float(np.mean(row)):.3f}")
    MENU = ["read_file", "list_directory", "recall_memory",
            "vision_analyze_screen", "NONE", "DELEGATE"]
    for opt in MENU:
        tks = e._llm.tokenize(f" {opt}".encode(), add_bos=False)
        t0 = tks[0]
        deco = e._llm.detokenize([t0]).decode(errors="replace")
        print(f"  {opt:26} first_tok={t0} ({deco!r})  logit={float(last[t0]):.4f}")


if __name__ == "__main__":
    main()

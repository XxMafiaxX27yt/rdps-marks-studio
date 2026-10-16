"""Tries the small on-device AI models for Smart Ask on this PC's processor (no graphics card, 4 threads like a
school PC): each rewrites a messy question into a clean one; the rule engine must then understand it.
Plain Python + onnxruntime - nothing is opened, nothing leaves the PC."""
import json
import os
import sys
import time

import numpy as np
import onnxruntime as ort
from huggingface_hub import snapshot_download
from transformers import AutoTokenizer

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "core"))
from markstudio import api  # noqa: E402

PROMPT_FILE = os.path.join(ROOT, "web", "assets", "ask", "rewrite_prompt.json")


class Model:
    def __init__(self, repo, threads=4):
        path = snapshot_download(repo, allow_patterns=["*.json", "onnx/model_int8.onnx"], local_files_only=True)
        self.tok = AutoTokenizer.from_pretrained(path)
        cfg = json.load(open(os.path.join(path, "config.json")))
        self.layers, self.kv, self.hd = cfg["num_hidden_layers"], cfg["num_key_value_heads"], \
            cfg.get("head_dim") or cfg["hidden_size"] // cfg["num_attention_heads"]
        so = ort.SessionOptions()
        so.intra_op_num_threads = threads
        self.s = ort.InferenceSession(os.path.join(path, "onnx", "model_int8.onnx"), so, providers=["CPUExecutionProvider"])
        self.inputs = {i.name for i in self.s.get_inputs()}
        self.eos = set([self.tok.eos_token_id] + ([cfg["eos_token_id"]] if isinstance(cfg.get("eos_token_id"), int)
                                                  else list(cfg.get("eos_token_id") or [])))

    def generate(self, messages, max_new=48, **tmpl):
        ids = self.tok.apply_chat_template(messages, add_generation_prompt=True, tokenize=True, **tmpl)
        if hasattr(ids, "input_ids"):
            ids = ids["input_ids"]
        ids = np.array([ids], dtype=np.int64)
        past = {f"past_key_values.{i}.{k}": np.zeros((1, self.kv, 0, self.hd), dtype=np.float32)
                for i in range(self.layers) for k in ("key", "value")}
        out_ids, total = [], ids.shape[1]
        cur = ids
        for step in range(max_new):
            feed = {"input_ids": cur, "attention_mask": np.ones((1, total), dtype=np.int64)}
            if "position_ids" in self.inputs:
                feed["position_ids"] = np.arange(total - cur.shape[1], total, dtype=np.int64)[None]
            feed.update(past)
            outs = self.s.run(None, feed)
            logits = outs[0]
            nxt = int(np.argmax(logits[0, -1]))
            names = [o.name for o in self.s.get_outputs()]
            for name, val in zip(names[1:], outs[1:]):
                past[name.replace("present", "past_key_values")] = val
            if nxt in self.eos:
                break
            out_ids.append(nxt)
            if self.tok.decode(out_ids).count("\n") >= 1:
                break
            cur = np.array([[nxt]], dtype=np.int64)
            total += 1
        return self.tok.decode(out_ids, skip_special_tokens=True).strip(), ids.shape[1]


QUESTIONS = [
    "chem me kaun peeche hai class 12", "who all r weak in chemestry", "which teachers are not working good",
    "kis teacher ka result kharab hai", "who might need extra classes in maths in class 9",
    "show me kids who flunked physics", "12th ke toppers batao", "how is 6 B doing", "phyiscs average of class 11",
    "who got more than 90 in maths class 10", "which subject class 9 finds toughest", "best section in class 12",
    "kaun kaun absent tha half yearly me", "students failing 2 or more subjects in 11th", "who improved a lot in class 9",
    "maths me sabse achha kaun hai class 10", "girls vs boys result class 12", "how many kids got A1 in english class 6",
    "list the students who are struggling in science class 6", "who all scored full marks in maths",
    "top 3 of 11 A", "which teacher is doing the best job in maths", "compare half yearly and yearly class 9",
    "kaun se bacche maths me kamzor hai aur science me achhe", "11th ka pass percentage kitna hai",
    "show the toppers of each section of class 12", "which pcm students did best", "humanities toppers 12",
    "low scorers in sst class 10", "who fell down in marks in class 6",
]


def main():
    api.init()
    api.add_sample(False)
    api.analyze()
    prompt = json.load(open(PROMPT_FILE, encoding="utf-8"))
    base = [{"role": "system", "content": prompt["system"]}]
    for q, a in prompt["examples"]:
        base += [{"role": "user", "content": q}, {"role": "assistant", "content": a}]
    for repo, tmpl in [("onnx-community/Qwen2.5-0.5B-Instruct", {}),
                       ("onnx-community/Qwen3-0.6B-ONNX", {"enable_thinking": False})]:
        t0 = time.time()
        m = Model(repo)
        load = time.time() - t0
        ok, raw_ok, times = 0, 0, []
        print(f"\n=== {repo} (load {load:.1f} s)")
        for q in QUESTIONS:
            raw = json.loads(api.ask(q))["data"]
            raw_good = "text" in raw
            t = time.time()
            rew, ptoks = m.generate(base + [{"role": "user", "content": q}], **tmpl)
            dt = time.time() - t
            times.append(dt)
            ans = json.loads(api.ask(rew))["data"] if rew else {}
            good = "text" in ans or ans.get("clarify")
            ok += bool(good)
            raw_ok += raw_good
            print(f"  {'OK ' if good else 'XX '} {dt:4.1f}s  {q!r:58} -> {rew!r}  | {ans.get('understood', ans.get('message', ''))[:70]}")
        print(f"  {repo}: {ok}/{len(QUESTIONS)} understood after rewrite (rules alone: {raw_ok}); "
              f"avg {sum(times) / len(times):.1f} s, max {max(times):.1f} s, prompt {ptoks} tokens")


if __name__ == "__main__":
    main()

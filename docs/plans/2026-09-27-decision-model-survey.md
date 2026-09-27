# Decision-model backends for tw.py route(): feasibility survey (Windows, 2026-09-27)

Labels: [read] file/line read this session; [ran] command output this session; [inferred] my derivation.

## Checkpoint 1: contract and prior evidence

- tw.py backend contract [read `thinker-worker/scripts/tw.py:485-557`]: `BACKENDS = {"table": backend_table}` (l.492);
  a backend is `fn(cfg_block, pol, fields, brief) -> {tier, probs, confidence, body_chars_sent}`; `valid_route` (l.495-501)
  requires tier in pol tiers, probs keys subset of tiers, sum 1 +-1e-6, 0<=confidence<=1. `route()` runs backends in
  a daemon thread joined for `budget_s` (2.0 in shipped `routes.json`), fail-open to coordinator. Shipped
  `routes.json` has `"backends": []` and only a `table` block [read `thinker-worker/routes.json`].
- Prior measured numbers [read `~/.claude/notes/effort-routing/2026-09-26-design-review-resolutions.md` §4, §6]:
  Laya typed-decisions CPU load 6.9-7.5 s, process 9.3-9.8 s, warm 0.15-0.26 s; Kev not runnable (editable install
  points at a deleted scratchpad, l.113); Kev base-only proxy ~6 s load, fwd 0.08-0.15 s.
- Local-Agent bench 2026-09-22 [read `Local-Agent/docs/plans/2026-09-21-local-classifier-plan.md:299-307`]:
  Kev-0.8B CPU p50 147 ms (route) / 372 ms (Nimble); Laya GPU 34 ms, CPU 280-500 ms; 27B via NInfer fork /v1/score
  p50 108-219 ms (l.365-368, 404-406).
- Local-Agent decision layer [read `Local-Agent/docs/plans/2026-09-22-harness-decision-layer-design.md:27-61,166-175`]:
  `decide()` is one HTTP call to the resident 27B's `POST /v1/score` (NInfer fork, port 8080); small sidecars and
  "a separate service process" are explicitly left out.

## Checkpoint 2: machine state (Windows, 2026-09-27)

- HF cache `~/.cache/huggingface/hub` [ran `ls -laL`]: Laya typed-decisions `model.safetensors` 842,609,220 B;
  Kev-0.8B LoRA 43,338,624 B + `head.pt` 2,103,103 B; base `Qwen3.5-0.8B-Base` 1,746,942,600 B. No Eos, no SemIf,
  no Qwen3.5-4B. (`du -sb` per model dir showed MB only: blobs are shared at hub root, `blobs/` = 2.67 GB.)
- Other weights [ran find maxdepth 3 over ~/Code, ~, D:; positive control: same pattern found `.venv-kev` and
  `laya-*.jsonl`]: `~/Downloads/Qwen3-4B-Q8_0.gguf` 4,280,404,704 B (Qwen3, not Qwen3.5); 27B GGUFs and Gemma in
  `Local-Agent/models/`. No semif/openjev/anyjev/eos/decision-1 paths anywhere searched.
- Envs [ran site-packages ls]: `Local-Agent/local_decisions/.venv`: laya 0.3.5, torch 2.11.0+cu128,
  transformers 5.17.0 (no `serve` module in the laya package: files are agent, common, email, lang, presets,
  router, shortlist). `.venv-kev`: kev 0.1.0 editable, peft 0.21.0, torch 2.8.0, transformers 5.17.0; the
  editable MAPPING points at `...C--Users-Arian-Code-Local-Agent\9ea0a423-...\scratchpad\kev\kev`; that scratchpad
  still exists but has no `kev/` dir [ran ls], so `import kev` fails. No llama_cpp/semif/anyjev/onnxruntime/mlx in
  any conda env, the Hermes venv, or anaconda base [ran]. No llama-server; Ollama uninstalled (dir gone).
- Ports [ran netstat]: 8080 LISTEN, PID 45948 = `Local-Agent\runtime\ninfer-fork-igorls-383ce91e-media\ninfer-serve.exe`
  (production 27B). 8081, 8765-8768, 11434 free. GPU [ran nvidia-smi]: 25,521 / 32,607 MiB used (~7 GB free).

## Checkpoint 3: Laya warm-latency probe [ran]

`scratchpad/laya_probe.py` via `run_cpu_pool.py --pool general --threads 4`, `.venv` python, HF offline, CPU,
torch 4 threads, 4-option `choice` tier question, 6 calls per size; process exited, no leftover PID [ran CIM query].

| body chars | tokens seen | first ms | warm p50 ms | warm max ms | probs low/med/high/xhigh |
|---|---|---|---|---|---|
| 1,100 | 379 | 1,042 | 1,129 | 1,271 | .17/.35/.20/.28 |
| 2,400 | 713 | 2,126 | 2,136 | 2,406 | .17/.36/.21/.25 |
| 6,000 | 1,024 (cap) | 2,932 | 2,999 | 3,116 | .18/.36/.21/.25 |

import 4.4 s, load 15.7 s. The design's `laya.body_chars: 2400` misses the 2.0 s budget at 4 threads; the earlier
0.15-0.26 s warm figure was for short test headers. Output keys: action, choice, confidence, probabilities, type.
Probabilities near-flat on this one brief (no statement about quality). Untested: 12 threads, `device="cuda"`
(prior bench 34 ms GPU, `classifier-plan.md:306`).

## Backend: Laya
- Location [ran]: weights above; package `laya 0.3.5` in `Local-Agent/local_decisions/.venv`.
- API [read `.venv/.../laya/agent.py:265-330`, `bench.py:67-79`]: `laya.load(repo, subfolder="typed-decisions",
  device)`, `agent.predict(state, questions)`; Jev-shaped `choice` returns `probabilities` per option + `confidence`;
  `score` takes an ordered criteria list (ordinal tiers fit). Limit `max_len` 1024, `head_max_len` 256
  (resolutions §6); truncation silent (probe: 6,000 chars -> 1,024 tokens).
- Server today: none installed. Upstream README lists a `laya[serve]` HTTP extra [read gh README l.30]; not in 0.3.5.
- Numbers: CPU bench p50 464 / p95 867 ms (374 short cases, `results/laya-cpu.jsonl` [ran]); GPU 34 ms
  (`classifier-plan.md:306` [read]); probe above.
- Mac [read survey]: third-party `laya-mlx`, torch MPS; Mac not inspected, HF cache is machine-local [inferred].
- Adapter: zero install on Windows. ~40-line stdlib server in `.venv` around `predict` + the shared tw.py client.
  Blocker: latency at 2,400 chars (fix: threads, GPU, or body 1,100).

## Backend: Kev-0.8B
- Location [ran]: weights on disk; `.venv-kev` exists but kev source is gone, so not runnable.
- API [read kev README "API", "Run It Locally"]: `python -m kev.serve --run jaredpalmer/kev-0.8b --port N`,
  `POST /v1/systemone {state, model, questions}`; `choice` -> `choice`, `probabilities`, `confidence` with
  confidence = (p_max - 1/K)/(1 - 1/K), not p_max; `score` ordinal supported; fitted temperature ships per
  checkpoint. Trained at <=384 tokens, serve limit 8192 (`bench.py:119` [read]).
- Server today: `kev.serve` upstream; README names CUDA/ROCm/MLX, CPU not documented for serve [read]. The bench
  ran Kev on CPU through `LocalPredictor` (`bench.py:108-122` [read]).
- Numbers [ran over `results/*.jsonl`]: CPU p50 358 / p95 510 ms (374 cases); real-route p50 155 / p95 707 ms.
  Upstream [read]: M5 MLX 0.8B 149 ms new ~270-token text, 28 ms cached.
- Mac: documented MLX serve path, best Mac story of the four; weights not on Mac [inferred].
- Adapter: re-clone kev and re-point the editable install (an install; needs Arian's OK), then `kev.serve` on CPU
  (unverified) or a 15-line wrapper from `bench.py:make_kev`. GPU path needs `flash-linear-attention` (Triton;
  Windows unverified, `classifier-plan.md:175`).

## Backend: Eos (Decision-1.0-Eos-0.8B)
- Location: NOT FOUND locally [ran find + HF cache ls; control above]. HF repo [ran HF API]: backbone
  `model.safetensors` 1,504,820,888 B + `decision_head.safetensors` 4,213,584 B, Apache-2.0, updated 2026-09-27.
- API [read HF card]: "no bundled inference code or service"; root `config.json` is "not a Transformers AutoModel
  configuration"; served by the vLLM Semantic Router Decision runtime, then `POST /v1/systemone` (Jev shape).
  Max input 16,384 tokens; calibrated temperature in `config.json`; card: probabilities "can be overconfident".
- Server today: none. Runtimes: vLLM-SR (AMD gfx942 validation only, per survey), or Ollaya model `decision`
  (Windows x64 installer, ONNX CPU/CUDA, `/v1/systemone` wire-identical, port 11435) [read Ollaya README].
- Numbers: none local. Mac: Ollaya macOS; third-party MLX port listed on HF (not read).
- Adapter: 1.5 GB download + a runtime install (both need approval). Ollaya path 2-4 h; own loader from
  ARCHITECTURE.md 6+ h, highest uncertainty.

## Backend: SemIf-4B + AnyJev L0
- Location: NOT FOUND locally [ran; control above]. Stand-in on disk: `Qwen3-4B-Q8_0.gguf` (Qwen3, not the
  Qwen3.5-4B SemIf documents; SemIf builds prompts on a pinned reference tokenizer [read], so a
  different-generation GGUF is off its tested path [inferred]).
- API [read SemIf README, repo tree, pyproject]: batch CLI `semif-score --mode direct|shared --input x.jsonl
  --output y.jsonl`; CPU via `--backend llamacpp --gguf ... --llama-threads N`; Apple via `--backend mlx`.
  Extra `llamacpp = llama-cpp-python==0.3.35`. Tree grep for serve/server/http: only `src/semif_phase1/cli.py`,
  so NO HTTP server (a pinggy blog claim that SemIf exposes one is contradicted by the tree). Default limit 4,096
  tokens (`--max-tokens`, per Rizzo README table [read]).
- AnyJev [read README]: L0 "costs K prefills for a K-option choice" (4 here); its backends are HF/vLLM; no
  llama.cpp backend seen, so L0 over SemIf/llama.cpp is ours to write (~30 lines: 4 cyclic rotations +
  content-free prior) [inferred].
- Server today: none. Numbers: none local. Mac: SemIf MLX backend documented [read].
- Adapter: install SemIf + llama-cpp-python (Windows wheel/compile unverified), download a 4B GGUF (~2.7 GB Q4_K_M,
  size inferred), write the resident wrapper (the CLI reloads per call) + L0. Latency: 4B decoder on CPU over
  ~1,100 tokens x 4 rotations very likely > 2 s, since Laya-421M took 2.1 s for 713 tokens [inferred,
  unmeasured]; GPU fits in ~7 GB free but shares the production card.

## One server for all four?
- Local-Agent's layer cannot host them [read]: `decide.py` (194 lines, Hermes tree) is a client of the NInfer
  fork's `POST /v1/score` on 8080 (`decide.py:112-134`); NInfer serves `.ninfer` Qwen artifacts only, "no adapters
  or custom heads" (`classifier-plan.md:206-208`); that design left out small sidecars and "a separate service
  process" (`decision-layer-design.md:171-174`).
- Kev, Laya-serve, the Eos runtime and Ollaya all speak Jev's `POST /v1/systemone` [read], so one tw.py client
  covers every arm. Server side: Ollaya (one daemon: laya:typed-decisions, kev 0.8B, decision=Eos; not SemIf), or
  our own stdlib wrapper with an adapter dict: one script, but two processes unless venvs merge (Laya torch 2.11
  vs Kev torch 2.8+peft) [ran].
- Unlisted fifth option, already resident: the 27B's `/v1/score` on 8080 does SemIf's letter-logit read at
  108-219 ms (`classifier-plan.md:365-368,404-406`). The design excludes it (§0, §6, §1 [A] row). Flagged only.

## Effort estimate (assumptions: an agent writes the code, Arian approves each install/download, CPU only,
## shadow mode, no calibration beyond what ships; hours are [inferred])

Shared once: tw.py `backend_jev` (POST `/v1/systemone`, truncate to `body_chars`, options = the role's tiers only,
renormalise so `valid_route` passes (`tw.py:495-501`), urllib timeout <= remaining budget, map Kev-style
confidence) ~40 lines + stub-server test ~30 lines: 2 h. Offline replay of stored bodies for the non-live arms
(§5 Stage 1): ~30 lines, 1 h. Manual start commands first, login task later: 0.5 h. Total ~3.5 h.

| Backend | Extra hours | Needs approval for |
|---|---|---|
| Laya | 1.5-2 (40-line server; fix latency) | nothing |
| Kev-0.8B | 1.5-3 | re-clone kev source |
| Eos | 2-4 via Ollaya; 6+ own loader | 1.5 GB download + runtime install |
| SemIf-4B + L0 | 5-8 | SemIf + llama-cpp-python install, 4B GGUF download |

One backend in shadow: Laya, ~5 h. All four: ~14-24 h on Windows. Mac ports: +1-2 h each, all need weights
downloaded there.

## Kev fix (2026-09-27, Windows)

- Venv path is `Local-Agent/local_decisions/.venv-kev` (python 3.12.3; kev 0.1.0, peft 0.21.0, torch 2.8.0,
  transformers 5.17.0, fastapi/uvicorn/typesafe_sdk present) [ran]. Repo URL from `kev-0.1.0.dist-info/METADATA`
  Project-URL: https://github.com/jaredpalmer/kev [read].
- Cloned to `C:\Users\Arian\Code\kev`. `origin/main` HEAD 5920c5f (2026-09-26) does not import on Windows:
  `kev/suite.py` does `import fcntl` (added 1dc2fbc, 2026-09-24), pulled in by `kev.predictors`. HEAD has also
  renamed `kev.serve.INFER_MAX_STATE`, which `bench.py:make_kev` imports [ran]. The clone is pinned to local branch
  `windows-pin-2026-09-22` at 90990a5 (2026-09-21 20:43 -0400). That is the last main commit before the venv was
  installed (2026-09-22 01:08 EDT, from `uv_cache.json`). uv recorded `commit: null`, so the original commit is
  inferred.
- `.venv-kev` has no working pip (a uv venv). Re-pointed it with `uv pip install --python <.venv-kev python> -e
  C:\Users\Arian\Code\kev --no-deps`, which made no dependency changes. The editable MAPPING now points at
  `C:\Users\Arian\Code\kev\kev`, and `import kev` resolves there [ran].
- Probe [ran]: `kev_probe.py` follows the `bench.py:make_kev` path (to_record, then encode at the serve limit of
  8192, forward, softmax, to_answers). It ran on CPU in fp32, used the local weights with HF_HUB_OFFLINE=1, and went
  through `run_cpu_pool.py --pool general`. It asked the 4-option tier question on a ~450-char tw.py brief:

  ```
  {"type": "choice", "choice": "medium", "confidence": 0.61,
   "probabilities": {"low": 0.12, "medium": 0.71, "high": 0.12, "xhigh": 0.05}}
  sum(probs)=1.0000  input_tokens=177  temperature=2.406
  4 threads:  import 4.9 s, load 3.2 s, calls 858 / 934 / 968 ms
  12 threads: import 4.7 s, load 2.0 s, calls 367 / 358 / 358 ms
  ```

  The warm latency at 12 threads matches the bench CPU p50 of 358 ms. Linear attention runs through transformers'
  reference PyTorch fallback because `flash-linear-attention` and `causal_conv1d` are absent. One brief proves the
  pipeline runs; it says nothing about routing quality.

# AIG Similarity

Tools for comparing And-Inverter Graphs (AIGs) with structural and optimization-based similarity metrics.

## Setup

```bash
pip install -r requirements.txt
```

## Expected data layout (benchmark runs)

Place repeated synthesis runs under `data/benchmarks/` as follows:

```text
data/benchmarks/<benchmark>/<script><N>/yosys.aig
```

- `<benchmark>`: benchmark name (e.g. `aes`, `ibex`)
- `<script>`: script name prefix (e.g. `abc_hogehoge`, `abc_puyopuyo`)
- `<N>`: run index from `1` to `100` by default
- `yosys.aig`: AIG file produced for that run

Example:

```text
data/benchmarks/adder/abc_resyn21/yosys.aig
data/benchmarks/adder/abc_resyn22/yosys.aig
...
data/benchmarks/adder/abc_resyn2100/yosys.aig
```

## Analyze a benchmark + script (`analyze_runs.py`)

Specify a **benchmark name** and a **script name**. The tool resolves run directories `<script>1` … `<script>100`, loads each `yosys.aig`, and either:

1. **pairwise** (default): computes all pairwise metric scores among found runs
2. **stats**: exports per-run AIG characteristics (PIs, POs, gates, edges, levels)

### Pairwise similarity

```bash
python analyze_runs.py --benchmark adder --script abc_resyn2 --metric veo
```

Outputs (under `data/results/` by default):

- `adder__abc_resyn2__veo_matrix.csv` — full score matrix (diagonal = `0`)
- `adder__abc_resyn2__veo_pairs.csv` — long-form upper-triangle pairs (`run_i`, `run_j`, `score`)

### Per-run statistics

```bash
python analyze_runs.py --benchmark adder --script abc_resyn2 --mode stats
```

Output:

- `adder__abc_resyn2__stats.csv`

### Useful options

| Option | Default | Description |
|---|---|---|
| `--benchmark` | *(required)* | Benchmark directory name |
| `--script` | *(required)* | Script name prefix |
| `--metric` | — | Required for `--mode pairwise` |
| `--mode` | `pairwise` | `pairwise` or `stats` |
| `--data-root` | `data/benchmarks` | Root containing benchmark folders |
| `--aig-filename` | `yosys.aig` | File name inside each run directory |
| `--start` / `--end` | `1` / `100` | Inclusive run index range |
| `--save-path` | `data/results` | Output directory |
| `--strict` | off | Fail if any expected file in the range is missing |

Examples:

```bash
# Only runs 1..10
python analyze_runs.py --benchmark adder --script abc_resyn2 --metric rel_gate_count --start 1 --end 10

# Custom root / filename
python analyze_runs.py --benchmark multiplier --script deepsyn --metric netsimile \
  --data-root /path/to/benchmarks --aig-filename design.aig

# Abort if any of 1..100 is missing
python analyze_runs.py --benchmark adder --script abc_resyn2 --metric veo --strict
```

Missing files are skipped with a warning unless `--strict` is set. At least one matching AIG is required.

### Available metrics

Any metric registered in `utils.FUNCTION_MAP`, except `abs_size_diff` / `rel_size_diff` (those need a separate optimized AIG tree not present in this layout).

Common choices:

- Graph distances: `netsimile`, `veo`, `lap_sd`, `adj_sd`, `kernel_sim`, …
- Characteristic diffs: `rel_gate_count`, `abs_gate_count`, `rel_level_count`, `gate_level_cosine`, …
- Optimization deltas: `rel_resub`, `rel_rewrite`, `rel_refactor`, `rel_rrr_euclidean`, …

List choices with:

```bash
python analyze_runs.py --help
```

## Legacy multi-type comparison (`main.py`)

`main.py` compares AIGs across synthesis styles under the older layout:

```text
data/aigs/<type>/<id>.aig
```

```bash
python main.py veo --folder_path data/aigs/ --id_path data/aigs/indices.txt --save_path data/results/
```

## Project layout

| Path | Role |
|---|---|
| `analyze_runs.py` | Analyze `data/benchmarks/<benchmark>/<script><N>/yosys.aig` |
| `main.py` | Compare multiple AIG types for shared IDs |
| `utils.py` | Metric name → function map |
| `graph_utils.py` | AIG → NetworkX conversion helpers |
| `sim_scores/` | Metric implementations |
| `data/results/` | Default output directory for CSV scores |

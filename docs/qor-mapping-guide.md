# From AIG Similarity to QoR: Design-Space Mapping Guide

This note describes how to use the existing AIG similarity tooling (`analyze_runs.py`) to study **structural design space ↔ QoR space** relationships for ~100 AIG variants of the same design, and how to turn that into actionable selection of the best netlist.

## Problem statement

You have many AIG variants of one (or more) designs, and for each variant you can obtain final QoR labels such as timing and cell count (area). The goals are:

1. **Interpretability** — Which AIG features drive timing and cell count?
2. **Selection** — Which AIG should we keep as the best candidate?
3. **Efficient exploration** — Can we avoid full P&R on every variant?

If pairwise AIG similarity is available, the problem reduces to learning a map

\[
\text{structure space} \xrightarrow{\;f\;} \text{QoR space}.
\]

Similarity induces a kernel on structure space, so **kernel methods and graph embeddings** can be used without hand-crafting a complete feature vector first. Explicit features are still valuable for human-readable explanations.

| Goal | Method |
|---|---|
| Which features matter? | Kernel regression + interpretable embedding analysis, **in parallel with** explicit features + SHAP |
| Select the best AIG | Diversity-maximizing sampling on the similarity matrix + surrogate prediction |
| Explore more efficiently | Gaussian-process regression with the AIG similarity kernel (Bayesian optimization) |

---

## Recommended overall strategy

Use **100 AIG variants** produced by a synthesis script family as a structured design-space sample. Build an \(N \times N\) similarity matrix with `analyze_runs.py`, jointly analyze QoR labels, then decide whether the chosen similarity metric is QoR-aligned. Only after that alignment check invest in feature attribution, surrogate models, and best-of-\(N\) selection.

```text
AIG_1 .. AIG_100  --(analyze_runs.py)-->  K (similarity / distance)
        |                                      |
        +---- QoR labels (timing, cells) ------+-->  embedding, regression, selection
```

---

## Step 1 — Organize the dataset

For each variant \(i = 1..N\) (typically \(N=100\)) assemble:

| Field | Example | Notes |
|---|---|---|
| `run_id` | `1..100` | Matches `<script><N>` directories |
| `AIG_i` | `data/benchmarks/<bench>/<script><N>/yosys.aig` | Input to similarity analysis |
| `timing_i` | WNS / TNS / critical path delay | From P&R or STA |
| `cell_count_i` / `area_i` | post-map or post-P&R | Be explicit which stage |
| optional | power, wirelength, runtime | Useful secondary labels |

### Critical decision: within-design vs cross-design

- **Within one design** (recommended first): absolute QoR is meaningful; clusters are comparable.
- **Across designs**: normalize QoR (e.g., ratio to a fixed baseline script, or z-score within design). Otherwise size-dominated designs swamp the signal.

Suggested on-disk companion table (CSV):

```text
data/results/<benchmark>__<script>__qor.csv
run_id,timing,cell_count,area,...
1,...
```

Keep AIG paths resolvable via the existing layout consumed by `analyze_runs.py`.

---

## Step 2 — Build the similarity matrix and cluster / visualize

### 2.1 Compute pairwise structure scores

```bash
# Example: Vertex-Edge Overlap style metric (pick any supported metric)
python analyze_runs.py \
  --benchmark aes \
  --script abc_hogehoge \
  --metric veo \
  --start 1 --end 100 \
  --strict

# Optional baseline structural stats per run
python analyze_runs.py \
  --benchmark aes \
  --script abc_hogehoge \
  --mode stats
```

Outputs:

- `data/results/<bench>__<script>__<metric>_matrix.csv`
- `data/results/<bench>__<script>__<metric>_pairs.csv`
- `data/results/<bench>__<script>__stats.csv` (stats mode)

Convert distance ↔ similarity as needed for kernels (e.g. \(K_{ij}=\exp(-\gamma D_{ij})\) if the metric is a distance).

Try more than one metric early (`netsimile`, `veo`, `lap_sd`, `kernel_sim`, gate/level characteristic metrics). The best metric is the one that later correlates with QoR geometry, not the one that looks nicest alone.

### 2.2 Embed and overlay QoR

1. Take the \(N \times N\) matrix \(K\) (or distance \(D\)).
2. Embed with **MDS / t-SNE / UMAP** into 2D.
3. Color points by `timing`, `cell_count`, or a Pareto rank.
4. Optionally cluster (spectral clustering / hierarchical clustering on \(K\)).

### 2.3 First go / no-go check (most important early result)

| Observation | Interpretation | Action |
|---|---|---|
| Structure clusters align with QoR colors | Similarity captures QoR-relevant axes | Proceed to Steps 3–4 |
| Structure clusters mix good and bad QoR | Metric misses QoR-critical structure | Revisit metric / features / pipeline stage |
| Embedding collapses to a size axis | Similarity is mostly node-count proxy | Control for size (partial correlation); try size-normalized metrics |

This visualization is also a natural paper figure.

---

## Step 3 — Identify which features matter (two-track)

Similarity alone answers “who is close to whom,” not “what causes QoR.” Run **two tracks in parallel**.

### Track A — Explicit, human-readable features

Extract (extend `--mode stats` as needed):

- AIG levels, node/gate counts, invertible MFFC-related structure
- Fanout distribution (mean, variance, max)
- Logic-depth histogram; local structure near the critical cone
- Per-level node-density profile
- Cut statistics (counts / distribution of \(k\)-feasible cuts)

Train a **gradient boosting** regressor for `timing` and `cell_count`, then explain with **SHAP**.

### Track B — Kernel methods on the AIG similarity kernel

Treat \(K\) as a Gram matrix and fit **Kernel Ridge Regression (KRR)** (and later a GP) from structure to QoR.

### Compare A vs B

| Result | Meaning |
|---|---|
| Explicit features ≈ kernel accuracy | Hand features already capture the useful signal; explain with SHAP |
| Kernel clearly better | Missing structural information in the hand features — itself a research finding |
| Both weak | Similarity / features not QoR-aligned, or QoR noise dominates (see Step 5) |

Optional: interpret low-dimensional kernel embeddings (kernel PCA) and correlate coordinates with explicit features to name the latent axes.

---

## Step 4 — Select the best AIG without full enumeration

Naïve approach: P&R all \(N\) variants. Costly. Prefer a **two-stage** policy.

### Stage A — Diverse representatives (\(M \ll N\))

From the similarity matrix, pick \(M\) structurally diverse AIGs using:

- **k-center** / farthest-first traversal, or
- **DPP** (Determinantal Point Process) sampling on \(K\)

Rationale: diversity in structure space is a controlled way to cover QoR variance (consistent with ASP-DAC-style “diversity helps best-of-\(N\)” arguments). Similarity makes diversity **quantitative**.

### Stage B — Surrogate fill-in

1. Run full P&R / STA only on the \(M\) representatives → get true QoR.
2. Fit a surrogate (KRR / GP with AIG similarity kernel, optionally + explicit features).
3. Predict the remaining \(N-M\) variants.
4. Evaluate the top predicted candidates with real P&R.
5. Iterate (active learning / Bayesian optimization).

### What to report for “best selection”

- Best observed QoR among evaluated AIGs
- Estimated regret vs oracle best-of-\(N\) (if you later evaluate all, or via held-out folds)
- How diversity budget \(M\) trades off against final QoR
- Causal-ish chain for the narrative: **similarity → diversity → QoR variance → best-of-\(N\) improvement**

### Bayesian optimization variant (Step 4+)

Use a GP prior with covariance = AIG similarity kernel. Acquisition (EI / UCB) proposes the next AIG to P&R. This is the natural “explore efficiently” path once Step 2 confirms kernel–QoR alignment.

---

## Step 5 — Pitfalls and sanity checks

1. **Size confound**  
   Check whether similarity is mostly a node-count proxy. Control for size (partial correlation, residualize features/QoR by gate count) and re-run Step 2–3.

2. **P&R / tool noise floor**  
   Re-run the **same AIG** with multiple random seeds. If seed variance ≥ structural QoR gaps, you cannot claim fine-grained ranking; report confidence intervals and maybe aggregate seeds.

3. **Two-stage technology path**  
   AIG structure ≠ final timing. Split the analysis:

   ```text
   AIG structure  →  post-mapping netlist structure  →  post-placement timing
   ```

   Correlate AIG↔map and map↔timing separately. A weak AIG↔timing link with a strong map↔timing link suggests mapping dominates.

4. **Metric misuse**  
   Some metrics in this repo are distances, some are similarities, some are optimization *deltas*. Document the transform into a PSD kernel before KRR/GP.

5. **Train/test leakage**  
   When using the full \(N \times N\) kernel for prediction, use nested CV or leave-one-out carefully; do not tune on the same pairs used for final claims.

---

## Concrete workflow checklist (first experiment)

1. Fix one benchmark + one script family with 100 AIGs under `data/benchmarks/...`.
2. Collect QoR CSV aligned by `run_id`.
3. Run `analyze_runs.py --mode stats` and at least two pairwise metrics.
4. Embed \(K\), color by QoR → **alignment check**.
5. If aligned: train GBDT+SHAP and KRR; compare RMSE / Spearman rank correlation.
6. Select \(M\) diverse AIGs (e.g. \(M=10\)–\(20\)); surrogate-predict; validate top-\(k\).
7. Measure noise floor with multi-seed P&R on 3–5 AIGs.
8. Document which metric passed the alignment check; discard the rest or keep as negative results.

---

## Paper-facing narrative (optional)

A strong story is **why a particular synthesis strategy works** (e.g., deepsyn):

- Show that LUT map/unmap round-trips induce **large jumps** in AIG similarity space (global moves), whereas rewrite / refactor / balance induce **local moves**.
- Plot distributions of pairwise move distances between successive transforms (Step 2 machinery).
- Argue that global relocation increases coverage of QoR space and improves best-of-\(N\).

The same embedding colored by QoR becomes a single persuasive figure if clusters and QoR agree.

---

## How this maps to the current repository

| Artifact | Role in this plan |
|---|---|
| `analyze_runs.py` | Build pairwise matrices and per-run basic stats for `<script>1..100` |
| `utils.FUNCTION_MAP` / `sim_scores/` | Candidate similarity / distance kernels |
| `data/benchmarks/<bench>/<script><N>/yosys.aig` | Structure-space samples |
| `data/results/*_matrix.csv` | Input to MDS/UMAP, clustering, KRR/GP, diversity sampling |
| `data/results/*_stats.csv` | Seed for explicit feature track (extend as needed) |
| QoR CSV (to add) | Labels for regression, coloring, and best selection |

Suggested next engineering increments (when implementing the pipeline):

1. QoR join utility: merge `*_matrix.csv` / `*_stats.csv` with timing/cell labels by `run_id`.
2. Embedding + plot script: 2D projection colored by QoR.
3. Diversity sampler: k-center / DPP over the matrix.
4. Surrogate module: KRR/GP with optional explicit features + SHAP track.

---

## Summary

Treat the 100 AIGs as a **structured sample of design space**. Use `analyze_runs.py` to obtain a similarity kernel, verify that this structure geometry aligns with QoR geometry, then:

- explain drivers with **explicit features + SHAP**, validated against **kernel regression**;
- select winners via **diversity sampling + surrogate / BO**, not blind full P&R;
- always check **size confounding**, **tool noise**, and the **AIG → mapped netlist → timing** cascade.

The first milestone is not “best model accuracy,” but a clear yes/no: **does the chosen AIG similarity organize QoR?** Everything else depends on that.

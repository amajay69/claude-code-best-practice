---
name: portfolio-review
description: Run the full analyst desk over a holdings file and produce a report card
argument-hint: [holdings-csv] [horizon] [risk-profile] [depth]
allowed-tools: Bash, Read, Write, Agent, Skill
model: opus
---

# Portfolio review

Drive the analyst desk end to end over `$1` (default
`fixtures/holdings.csv`) and produce a report card.

## Step 0 — settle the three dials

If the user did not supply them as `$2`, `$3`, `$4`, ask once, in a single
message, and wait for the answer. These are not cosmetic — the first two
change the analysis, not just the presentation.

| Dial | Values | What it changes |
| --- | --- | --- |
| Horizon | `intraday` `swing` `positional` `medium` `long` `wealth` | signal weights, stop distances, backtest holding period |
| Risk profile | `conservative` `balanced` `aggressive` | position sizing and stop multiples |
| Depth | `quick` `standard` `deep` | how much reasoning reaches the report |

## Step 1 — compute the facts (deterministic, no model)

```bash
python3 scripts/run_analysis.py --holdings <$1> --horizon <$2> \
    --risk <$3> --depth <$4> --quiet
```

Note the run folder it prints. Everything downstream reads
`<run>/analysis.json`, and **no agent recomputes any number in it.** That is
what keeps two runs of the same book agreeing on the facts.

If this command fails, stop and report the failure. Do not proceed with
agents reading a stale or missing fact sheet.

## Step 2 — four specialists, one pass each

Invoke all four **in parallel** via the Agent tool, in a single message.
They are independent by design — the disagreement between them is the
information this desk is built to surface.

```
Agent(subagent_type="technical-analyst",   prompt="Analyse <run>/analysis.json")
Agent(subagent_type="fundamental-analyst", prompt="Analyse <run>/analysis.json")
Agent(subagent_type="sentiment-analyst",   prompt="Analyse <run>/analysis.json")
Agent(subagent_type="macro-analyst",       prompt="Analyse <run>/analysis.json")
```

Each reads the whole book through one lens. Fanning out by **lens** rather
than by **stock** keeps this at four calls instead of four per holding.

## Step 3 — the orchestrator weighs all four

```
Agent(subagent_type="stock-orchestrator", prompt="<run>/analysis.json plus the four specialist outputs verbatim")
```

This is the only barrier in the flow — it genuinely needs all four views at
once. Everything after it is sequential.

Keep its `contested` list. Those holdings go to the debate.

## Step 4 — adversarial research on contested names

Invoke both **in parallel, in one message**, each without sight of the
other's argument:

```
Agent(subagent_type="research-bull", prompt="<run>/analysis.json + orchestrator brief")
Agent(subagent_type="research-bear", prompt="<run>/analysis.json + orchestrator brief")
```

Independence is the whole point. A single agent asked to argue both sides
hedges into mush, and the reader loses the argument they needed to hear.

If `contested` is empty, skip this step and say so in the summary — a book
with no genuine disagreement is a finding worth reporting.

## Step 5 — the desk chain, strictly in order

Each station consumes the previous one's output. Do not parallelise these.

```
Agent(subagent_type="trader",         prompt="... + both research cases")
Agent(subagent_type="risk-officer",   prompt="... + trader stances")
Agent(subagent_type="decision-maker", prompt="... + risk constraints")
```

Risk sits **after** the trader deliberately: it constrains a stance that
already exists rather than pre-emptively shaping one.

## Step 6 — render

Write the decision-maker's JSON to `<run>/decisions.json` with `Write`, then:

```bash
python3 scripts/render_report.py --run <run> --decisions <run>/decisions.json
```

Rendering stays out of the model so the arithmetic in the report card is
reproducible and the engine badge is set from the data rather than from what
a model claims about itself.

## Step 7 — summarise

Report to the user:

- the health verdict and the top three reasons
- the first three rows of the action queue
- the effective-bets headline
- **any row badged `rules`** — those holdings did not get a model verdict,
  and the user must know which parts of the report are which

## If the model layer is unavailable

Steps 2-6 need a model. If agents cannot run, the Step 1 output is already a
complete rules-based report card at `<run>/report-card.md`, badged
`🟠 Rules-based fallback`. Hand the user that, and say plainly that it is the
deterministic fallback rather than the full desk.

## Non-negotiable

- No agent computes a number; they interpret `analysis.json`.
- The disclaimer travels with every report.
- The output is a ranked suggestion list for a human. This desk never places
  an order, and nothing it emits should be phrased as an instruction to a
  broker.

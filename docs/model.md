# Model notes

## Core idea

The model treats corporate behavior as deformation under pressure.

- `ridge_reach`: evidence that firms can still project durable control into the future.
- `defensive_decay`: evidence that continuation strength is weakening.
- `dust_cloud`: evidence of reactive, short-horizon behavior.
- `geo_vector`: geopolitical pressure that may explain corporate deformation.
- `macro_vector`: macro / credit pressure.
- `sync`: clustering across entities, sectors, domains, and source types.

## Probability score

```text
p = sigmoid(
  b0
  + 0.90*dust_cloud_z
  + 0.70*defensive_decay_z
  + 0.55*sync_z
  + 0.35*geo_vector_z
  + 0.30*macro_vector_z
  - 0.50*ridge_reach_z
)
```

The z-scores are computed against the repo's own rolling hourly history. During warm-up, the fallback is `log1p(raw_value)`, and confidence is lowered.

## Phase labels

```text
S0 normal_noise
S1 local_stress
S2 sector_horizon_compression
S3 cross_sector_defense
S4 forced_repricing_risk
```

## Interpretation rules

- A single article or filing is not enough.
- Stronger signal requires clustering across source type, entity, sector, and topic.
- Geopolitics is explanatory context, not proof of corporate decay.
- The narrative is deterministic and cites source evidence. It is not an invented story.

## Evidence gates

The dashboard must not promote a corporate phase from macro-only context. The gated probability is set to `null` and the phase is `WARMUP` unless all of these are true:

- at least `min_sync_evidence_for_phase` non-macro live evidence rows exist;
- at least `min_corporate_deformation_evidence_for_phase` corporate dust/decay/reach rows exist;
- dust or defensive decay is nonzero when `require_nonzero_dust_or_decay_for_phase` is enabled.

FRED and other macro series are context vectors. They can raise raw pressure, but they cannot by themselves create S1/S2/S3/S4.


## Source gating and live-feed failure behavior

The model separates context from corporate deformation. FRED macro observations can raise the raw ungated pressure line, but they cannot create a corporate phase by themselves. A gated phase requires live corporate deformation evidence from SEC filings and/or classified live news.

GDELT is fetched through one combined DOC query per run and then classified locally into dust, defensive decay, ridge reach, geopolitics, and macro context. If GDELT is rate-limited or returns no matching articles, the app records that status and does not fabricate rows.

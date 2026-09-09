# Prediction contract

Required fields: `id`, `created_at`, `valid_until`, `data_cutoff`, `symbol`, `price`, `decision`, `primary_direction`, `probabilities.up/range/down`, `target_range.low/high`, `execution_conditions[]`, `abandon_conditions[]`, `timeframes.M5/M15/M30/H1`, `indicator_snapshot`, `news_snapshot[]`, `model_version`, `prompt_version`, and `run_type`.

Each news record stores `title`, `source`, `published_at`, `first_seen_at`, `url`, `impact`, and `gold_bias`. Settlement stores actual close/high/low, direction result, target terminal result, target touch result, Brier score, and settlement version.

Direction rule for the baseline: compare expiry close with starting price; moves within the configured neutral band are `range`. Freeze the neutral band and target range before prediction. Changes require a new strategy version.

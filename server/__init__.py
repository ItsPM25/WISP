"""server — the presentation layer over the wisp detection pipeline.

A thin, self-contained Flask bridge + dashboard that turns the already-tested detection
brain (wisp.pipeline) into a live room monitor with a fall-alert + escalation UI. It never
re-implements detection: it consumes ``wisp.pipeline.detection_telemetry`` (the one path
the harness also uses) so the demo can never diverge from what is measured.

Nothing here is required by the core pipeline; the console (`scripts/run_live.py`) remains
the minimal interface. This is the "make it visible for the pitch" layer.
"""

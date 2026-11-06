"""YASA hybrid audit pipeline.

An agent builds YASA taint-engine rules for the target project, the engine scans, and every engine
finding plus every residual sink the engine did not cover is triaged in a small, fresh LLM context.
See README.md in this package and backend/benchmarks/yasa_audit/README.md for results.
"""

# ADR 0002 — LangGraph for order, SQLite for retry

## Status

Accepted.

## Context

The step order is retrieve, choose a model, compose, validate, then apply policy. LangGraph expresses that order. LangGraph 1.2 with a dict state replaces the state with the node return instead of merging keys.

## Decision

Keep LangGraph as the sequencer. Each node copies the incoming state forward. Each finished step is also upserted in SQLite. On a retry the node returns the saved payload and does not call the tool again.

## Consequences

A test injects a failure after chart read and checks that the retry does not increment the chart-read counter. The graph library is a real import, not a name in a document.

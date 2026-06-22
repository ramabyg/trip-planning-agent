# 00 — Overview Spec

## Problem statement

During an 8-day road trip (Santa Clara, CA → Grand Teton → Yellowstone →
Glacier NP → Santa Clara, CA), the group needs a conversational assistant
that can answer planning questions that depend on **live, changing
conditions** — while respecting a set of **fixed constraints** that cannot
change (bookings, dates, who's where).

Example questions the agent should be able to answer:
- "Where should we charge between Old Faithful and Gardiner today?"
- "Is the road to Many Glacier open? What's a backup hike if not?"
- "We're running 2 hours behind — what should we cut from today's plan?"
- "Find a dinner spot near tonight's KOA that's open past 8pm."

## Goals

1. Conversational agent (chat-based, not background/proactive) that re-plans
   the *remainder of the current day* based on current location, time, and
   live conditions — not the whole 8-day trip from scratch.
2. Clear separation of **fixed facts** (never replanned) vs. **dynamic
   variables** (replanned per query).
3. Use this project to gain hands-on exposure to: Skills, MCP servers,
   multi-agent/orchestrator patterns, and SDD as a workflow.
4. Two genuinely safety/trip-critical data sources prioritized first:
   **NPS road/trail status** and **Tesla charging network reliability**.

## Non-goals (Phase 1)

- No proactive/background agent that watches location and pushes alerts
  unprompted. (Deferred to Phase 2.)
- No mobile app / native UI. Phase 1 is a conversational interface only
  (e.g. Claude Code, Claude.ai, or a simple chat CLI).
- No multi-user real-time sync between Rama's and Sayanna/JPR's instances
  of the agent (each runs independently for Phase 1).
- No persistent learning/memory across trips — this is scoped to the one
  trip's date range (July 18–25, 2026).

## Fixed facts (source of truth — see `specs/01-trip-context.md`)

- Group: Rama (+ family of 4), traveling with Sayanna and JPR for part of
  the trip.
- Vehicle: 2023 Tesla Model Y Long Range.
- Accommodation bookings and dates (immutable once booked).
- Park entry points and overall route direction.

## Dynamic variables to be replanned against

- Traffic / drive time
- Weather (current + short-term forecast)
- Tesla Supercharger / charger availability and reliability
- NPS road closures, timed-entry requirements, trailhead conditions
- Restaurant/food options en route (hours, location relative to route)

## Spec index

| Spec | Purpose |
|---|---|
| `00-overview.md` | This document — problem, goals, scope |
| `01-trip-context.md` | Fixed trip data model (bookings, dates, group, vehicle) |
| `02-charging-agent.md` | Charging planner skill/agent spec |
| `03-park-logistics.md` | NPS roads, trails, weather skill/agent spec |
| `04-orchestrator.md` | Conversational orchestrator agent spec |

## SDD conventions for this project

- Every new capability gets a spec in `specs/` before code is written.
- Specs describe **behavior and contracts** (inputs, outputs, decision
  rules), not implementation details (no specific library/API names
  required at spec time — those land in the architecture doc / code).
- Specs are living documents. Material changes are made via a clear
  git commit message referencing why the spec changed.
- A spec is "ready for implementation" when it has: scope, inputs,
  outputs, decision rules / edge cases, and explicit non-goals.

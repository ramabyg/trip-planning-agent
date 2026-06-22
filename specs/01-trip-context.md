# 01 — Trip Context Spec

## Purpose

Defines the **fixed, unchangeable** trip data that every other agent/skill
treats as ground truth. This data is never "replanned" — it's the
scaffolding the dynamic agents plan around.

## Scope

- Trip dates and overall route
- Group composition and vehicle
- Accommodation bookings (dates, location, address, who's staying where)
- Known hard constraints (e.g. intentional group split, overnight drive)

## Data model (draft — refine during implementation)

```yaml
trip:
  dates: "2026-07-18 to 2026-07-25 (+ overnight drive home 07-25/07-26)"
  origin: "Santa Clara, CA"
  group:
    - name: Rama
      role: primary
      family: [spouse, son (13), daughter (9)]
    - name: Sayanna
      role: companion
    - name: JPR
      role: companion
  vehicle:
    make_model: "2023 Tesla Model Y Long Range"

accommodations:
  - dates: ["2026-07-18", "2026-07-20"]
    type: airbnb
    location: "Driggs, ID"
    address: "823 Booshway Street, Driggs, ID 83422"
    occupants: [Rama, family]

  - dates: ["2026-07-20", "2026-07-22"]
    type: campground
    name: "WestGate KOA"
    address: "3305 Targhee Pass Highway, West Yellowstone, MT 59758"
    occupants: [Rama, family]

  - dates: ["2026-07-22", "2026-07-23"]
    type: airbnb
    location: "Gardiner, MT"
    occupants: [Rama, family]

  - dates: ["2026-07-23", "2026-07-25"]
    type: campground
    name: "West Glacier NP KOA"
    address: "355 Halfmoon Flats Road, West Glacier, MT 59936"
    occupants: [Rama, family]
    note: "Intentional split from Sayanna/JPR — different lodging, same days"

  - dates: ["2026-07-23", "2026-07-25"]
    type: airbnb
    location: "Kalispell, MT"
    address: "147 Cyclone Drive, Kalispell, MT 59901"
    occupants: [Sayanna, JPR]

  - dates: ["2026-07-25", "2026-07-26"]
    type: none
    note: "Overnight drive: West Glacier, MT -> Santa Clara, CA. No lodging."
```

## Outputs this spec provides to other agents/skills

- `current_base(date, time)` → which accommodation/location is "home base"
  for a given moment in the trip.
- `is_group_together(date)` → boolean + which subgroup is where (relevant
  Jul 23–25 when the group splits).
- `trip_day_index(date)` → which day of the 8-day trip this is, used to
  scope "remainder of today" replanning.
- Hard constraints list, e.g. "no lodging booked night of Jul 25 —
  overnight drive is intentional, not a gap to fill."

## Edge cases / decision rules

- If a query falls on a transition day (e.g. Jul 20, Jul 22, Jul 23), the
  context must surface **both** the checkout location/time and the next
  check-in location/time, since drive planning spans both.
- Jul 23–25: any plan involving "the group" must account for two separate
  physical locations (West Glacier vs. Kalispell) — roughly 25-30 min apart.
- This data is read-only to all other agents. Any change to bookings is a
  manual edit to this spec/file, never an agent-driven action.

## Non-goals

- This spec does not include day-by-day activity plans — that's dynamic
  and lives in the orchestrator's working state, not here.
- Does not include real-time location tracking of the vehicle/group
  (that's a Phase 2 concern if pursued at all).

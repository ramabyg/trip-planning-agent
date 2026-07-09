# 01 — Trip Context Spec

## Purpose

Defines the **fixed, unchangeable** trip data that every other agent treats as ground truth. This data is never "replanned" — it's the scaffolding the dynamic agents plan around.

## Scope

- Trip dates, overall route, and timezone changes.
- Group composition (families, cars, travel methods).
- Accommodation bookings (dates, location, address, who's staying where).
- Known hard constraints (e.g., intentional group split, shared vs. split accommodations, overnight drive).
- Planning preferences the agents must honor in every day plan: daily rules
  (one moderate hike, lunch on the go) and per-park must-see lists.

## Data Model

```yaml
trip:
  dates: "2026-07-18 to 2026-07-25 (+ overnight drive home 07-25/07-26)"
  origin: "Santa Clara, CA"
  timezones:
    origin_base: "Pacific Time (PT)"
    destination_base: "Mountain Time (MT)"
    notes: "Santa Clara is in PT. Idaho (Driggs), Wyoming (Grand Teton/Jackson Hole), and Montana (Yellowstone/Gardiner/Glacier/Kalispell) are in MT. Crossing between CA/NV and ID/WY/MT incurs a 1-hour shift (MT = PT + 1 hour)."
  
  group:
    - name: Family 1
      role: primary
      family: [spouse, son (13), daughter (9)]
      vehicle: "2023 Tesla Model Y Long Range (Electric)"
      travel_mode: "Driving from Santa Clara, CA on July 18th"
      
    - name: Family 2
      role: companion
      family: [spouse, child_1, child_2]
      vehicle: "Rented Gas Car (from JAC Airport)"
      travel_mode: "Flying to Jackson Hole (JAC) on July 18th, renting a gas car, driving to Driggs, ID"
      
    - name: Family 3
      role: companion
      family: [spouse, child_1, child_2]
      vehicle: "Rented Gas Car (from JAC Airport)"
      travel_mode: "Flying to Jackson Hole (JAC) on July 18th, renting a gas car, driving to Driggs, ID"

accommodations:
  # Exact street addresses are intentionally NOT committed (public repo).
  # They live in specs/trip-context-overrides.yaml (gitignored, deployed with
  # the app), keyed by the stable `id` below — see specs/06-deployment.md.
  - id: airbnb-driggs
    dates: ["2026-07-18", "2026-07-20"]
    type: airbnb
    location: "Driggs, ID"
    address: "Driggs, ID 83422"
    occupants: [Family 1 & family, Family 2 & family, Family 3 & family]
    note: "Shared by all 3 families (12 people total)"

  - id: koa-westgate
    dates: ["2026-07-20", "2026-07-22"]
    type: campground
    name: "WestGate KOA"
    address: "West Yellowstone, MT 59758"
    occupants: [Family 1 & family, Family 2 & family, Family 3 & family]
    note: "Shared by all 3 families (12 people total)"

  - id: airbnb-gardiner
    dates: ["2026-07-22", "2026-07-23"]
    type: airbnb
    location: "Gardiner, MT"
    occupants: [Family 1 & family, Family 2 & family, Family 3 & family]
    note: "Shared by all 3 families (12 people total)"

  - id: koa-west-glacier
    dates: ["2026-07-23", "2026-07-25"]
    type: campground
    name: "West Glacier NP KOA"
    address: "West Glacier, MT 59936"
    occupants: [Family 1 & family]
    note: "Split lodging - Family 1 stays here"

  - id: airbnb-kalispell
    dates: ["2026-07-23", "2026-07-25"]
    type: airbnb
    location: "Kalispell, MT"
    address: "Kalispell, MT 59901"
    occupants: [Family 2 & family, Family 3 & family]
    note: "Split lodging - Family 2 & Family 3 stay here"

  - id: drive-home
    dates: ["2026-07-25", "2026-07-26"]
    type: none
    note: "Overnight drive home: West Glacier, MT -> Santa Clara, CA. No lodging."

preferences:
  daily:
    - "At least one moderate hike every day (kid-friendly; kids in the group are 8-13)"
    - "Lunch on the go — grab-and-go food near the trailhead or route, no sit-down lunches"
  must_see:
    grand_teton:
      - "Jenny Lake + Cascade Canyon (boat shuttle across; good daily moderate hike)"
      - "Schwabacher Landing / Snake River Overlook (sunrise, quick stop)"
      - "Mormon Row barns"
    yellowstone:
      - "Old Faithful + Upper Geyser Basin boardwalk"
      - "Grand Prismatic via Fairy Falls overlook trail (moderate hike option)"
      - "Grand Canyon of the Yellowstone — Artist Point + rim trail"
      - "Lamar or Hayden Valley wildlife drive (early morning)"
      - "Mammoth Hot Springs terraces (near the Gardiner base)"
    glacier:
      - "Going-to-the-Sun Road + Logan Pass"
      - "Avalanche Lake via Trail of the Cedars (moderate hike option)"
      - "Lake McDonald"
      - "Many Glacier valley (NOTE: timed-entry permit required 6am-3pm)"
```

## Outputs this Spec Provides to Other Agents

- `current_base(date, time)` → which accommodation/location is "home base" for a given moment.
- `is_group_together(date)` → boolean indicating if the 3 families are sharing lodging/base or if they are split (returns True Jul 18-23, False Jul 23-25).
- `trip_day_index(date)` → day of the 8-day trip (1 to 8).
- `timezone_for_location(location)` → returns "PT" or "MT" based on state/location coordinates.
- Hard constraints list (e.g., no lodging on the night of July 25th due to the overnight drive home).
- `preferences` (daily planning rules + per-park must-see lists) — returned by
  `get_trip_context` so day plans honor them without re-prompting.

## Edge Cases / Decision Rules

- **Time Zone Crossing**:
  - The driving route from Santa Clara (PT) to Driggs, ID (MT) crosses into Mountain Time. Arrival planning at Driggs on July 18th must account for losing 1 hour.
  - The return drive from West Glacier (MT) to Santa Clara (PT) on July 25th crosses back into Pacific Time, gaining 1 hour.
- **Accommodation Sharing**:
  - July 18–23: All 3 families stay at the same location. Any dinner bookings, departures, or group activity plans must coordinate for 12 people.
  - July 23–25: The group splits. Family 1 stays at West Glacier KOA, while Family 2/Family 3 stay at Kalispell (approx. 25-30 mins apart). Plans must handle separate coordinates and logistics.
- **Vehicle Differences**:
  - Family 1 travels in a Tesla Model Y (requires EV charging routing).
  - Family 2 and Family 3 travel in separate rental gas vehicles (require normal route times, no Supercharging stops).
- **Manual Data Override**: This data is read-only. Updates to dates, group members, or accommodations must be done manually.

## Non-goals

- Day-by-day activity plans (handled by the orchestrator).
- Real-time location tracking of the vehicle/group.

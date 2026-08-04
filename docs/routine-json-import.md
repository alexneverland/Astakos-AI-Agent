# First-run routine import

`astakos_routines.json` is an optional local first-run file. It contains a user's
declared weekly routines, not scheduler history or learned memory. The Setup
Wizard provides a Routines tab for this file and invokes the importer when setup
is saved.

Copy `astakos_routines.json.example` to `astakos_routines.json`, then add routines
using this exact schema:

```json
{
  "version": 1,
  "routines": [
    {
      "day": "Monday",
      "time": "18:00",
      "event": "Evening walk",
      "type": "hobby"
    }
  ]
}
```

Allowed `day` values are `Monday` through `Sunday`, `Everyday`, `Weekdays`, and
`Weekends`. `time` must use 24-hour `HH:MM`; `type` is one of `family`, `work`,
`hobby`, or `general`; `event` must contain 3–200 characters.

The importer validates the full JSON before it writes anything. It imports only
when the routines database is empty; otherwise it does nothing. Imported routines
start active, but no trigger, confirmation, cooldown, or learned state is imported.
The Setup Wizard invokes this importer explicitly; it is never run automatically
by the scheduler or during normal application startup. The local JSON file is
preserved by release Docker updates, even after its one-time import.

# Assistant B's seven tools

`tool_definitions.json` holds the definitions exactly as `native.py` sent them to the model (`TOOL_SPECS`). The code of every tool is in `../code/instructed_baseline/tools.py` (class `Toolbox`). It stays inside the package so that the package still runs and its hash still matches the run records (`../README.md`).

Each tool wraps a service OntoSage+ itself uses, so both systems reach the same data. The tools deliberately apply none of OntoSage+'s checks on evidence: there is no referent check on their output, no binding of claims to evidence, no relevance check and no typed wording for absences. Those checks are what the comparison measures (§5.3). Every tool returns data, never prose; says explicitly when nothing matched; keeps "not found" apart from an error; and cuts a long result to a fixed size, saying so.

| Tool | Arguments | Returns | OntoSage+ service it wraps |
|---|---|---|---|
| `resolve_terms` | `text` | The building concepts and sensor classes that lay words map to | the lay-term concept resolver |
| `find_spaces` | `name_or_kind` | Rooms, zones and floors whose name or identifier contains the text, with the facts the building model records about each (type, floor, capacity and other properties) | SPARQL over the building's graph |
| `find_points` | `place`, `quantity` | Every sensor point measuring the quantity in the place (and in the HVAC zone the place belongs to), each with its timeseries identifier, its store and the period its series covers; OntoSage+'s own selection is marked. If none matches, the other points in the place | the graph and OntoSage+'s sensor binder |
| `get_readings` | `points`, `start`, `end` (building local time) | For each point: the number of readings, first and last time, minimum, mean and maximum, the largest gap, and how many of the points asked had data | the time-series adapters, chosen by each series' store |
| `query_records` | `register`, `contains` (optional) | Rows of one of the building's registers (bookings, maintenance, schedules, inspections and others), optionally filtered by text; if no register matches, the list of registers the building holds | the record registry and the graph |
| `search_documents` | `query` | Passages from the building's documents, with the document names | the document index |
| `find_amenities_or_topics` | `text` | Facilities and knowledge topics the building describes | the capability resolver |

The article's names for the seven tools (§5.3) are, in the same order: resolving lay terms, finding spaces, finding sensor points, reading series, querying records, searching documents and looking up amenities.

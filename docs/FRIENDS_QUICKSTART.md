# Asking OntoSage about Abacws — a quick guide

You're a user of the Abacws building. Ask it anything about the building, for whatever you're
trying to do — check conditions, plan a visit, understand energy use, find something, report a
problem. It answers from the building's own real data and documents, and will tell you honestly
when it doesn't know something rather than guess.

## What reliably works well

- **A single room or floor, right now:** "What's the temperature in room 2.01?", "Which floor is
  the warmest?", "Is room 1.06 free this afternoon?"
- **Comparisons:** "Compare CO2 on floor 1 against floor 3", "Which floor used the most energy
  yesterday?"
- **Finding the best space for one or two things you care about:** "Find me a quiet, well-lit
  room on floor 3", "Where's the coolest place to work right now?"
- **Charts:** "Graph the temperature in room 3.10 for the past week."
- **Registers — permits, faults, maintenance, hazards:** "Which permits are open?", "Which fire
  safety assets are overdue?", "How many open work orders are there?"
- **Reporting something:** "The toilet on floor 2 is leaking." / "Suggestion: more bike racks
  near the entrance."
- **Forecasts for one sensor:** "Will CO2 in room 5.01 exceed 1000 ppm tomorrow afternoon?"
- **Asking how it knows:** "How do you know that number is correct?" / "What evidence supports
  that?" (after an answer, in the same chat).

## What's harder, and what to do instead

- **One long question that bundles several asks together** tends to come back weaker than
  several short ones. Instead of "which room is best considering capacity, accessibility,
  acoustics, lighting and network service", ask one thing at a time, or two at most.
- **If an answer declines something you're fairly sure is true, ask again, maybe worded more
  simply.** Occasionally a good answer gets second-guessed by one of its own safety checks and
  thrown away — asking again almost always fixes it.
- **Name the room or floor if you can.** "Is it comfortable in here?" only works if you tell it
  where "here" is.
- **It won't invent a number.** If it says it doesn't have something, that's usually true, not a
  bug — but if it clearly SHOULD know (e.g. "what's the noise level" when you can see noise
  sensors mentioned elsewhere), that's worth telling me about.

## One honest note

This is a research system being actively improved, not a finished product. It will occasionally
decline something it should answer, or answer something in a way that feels thin. If something
seems wrong, ask again once — and if it's still wrong, tell me what you asked and what you got
back, because that's exactly the feedback that improves it.

# NeuroClime, Explained Simply

## What is this?

NeuroClime is a tool that shows how hot different parts of a city really get — not just one number for the whole city, but a separate reading for every neighborhood, street, and park. A weather app might tell you "Pune: 38°C." NeuroClime tells you that the crowded market street is at 42°C right now while the park three blocks away is a much safer 33°C, and it forecasts both up to 6 hours ahead.

It's built for three kinds of people:
- **Residents**, who want to know if it's safe to walk to work right now, or which route stays coolest.
- **Disaster management authorities**, who need to know which neighborhoods to send water tankers and open cooling shelters to first.
- **Urban planners**, who want to test "what if we planted more trees here?" before spending money on it.

## How does it know the temperature everywhere, without new sensors?

Cities already have a handful of official weather stations, plus satellites constantly photograph the ground and can measure surface heat, greenery, and how densely built-up an area is. NeuroClime combines these existing, free data sources with a prediction model that has learned the relationship between things like "lots of concrete, few trees" and "gets much hotter than the official station reading." That lets it estimate conditions in the gaps between sensors, for the whole city.

## What you can do with it

**See the live heat map.** The map is divided into small hexagon-shaped zones (about the size of a few city blocks each). Each one is colored by risk — safe, caution, danger, or extreme — using both color and an icon, so it's clear even for colorblind users.

**Slide through time.** A slider lets you check the forecast for right now, or 1, 3, or 6 hours ahead, so you can plan an errand for the coolest part of the afternoon.

**Get personal alerts.** You can mark your home and work zones. If either one is about to hit dangerous heat levels, you get a notification — in English, Hindi, or Marathi.

**Find the coolest route.** Instead of just the shortest path from A to B, this feature finds the path that keeps you out of the hottest zones, even if it's a little longer.

**Check the ward ranking (for authorities).** Neighborhoods are ranked by how many people are exposed to dangerous heat, so relief efforts — water points, shaded shelters — can go where they're needed most first.

**Try "what if" scenarios (for planners).** Pick a zone, drag a slider to imagine more trees or less concrete, and see the predicted temperature drop before anyone plants a single tree.

**Export a report.** Authorities can download a spreadsheet summarizing every ward's heat risk and a recommended action, ready to share in a briefing.

**Check system health (for admins).** A dashboard shows whether the data pipeline is running normally or something's gone stale.

## What's real, and what's simulated in this version

This handoff is a fully working demo, but a few things stand in for pieces that need real-world accounts and paid/registered data access to switch on:

- **Weather and satellite data** (from CPCB, IMD, and satellite programs) is currently generated to be realistic — hotter in dense areas, cooler near parks, following the natural rise and fall of temperature through the day — rather than pulled live. Real API keys can be dropped into one settings file to switch this on.
- **The prediction model** is a solid first version (it beats a simple "assume nothing changes" guess by about 85%), not yet the more advanced version described in the long-term plan. It's built so the more advanced version can be swapped in later without changing anything else.
- **Translations** for Hindi and Marathi cover the app's own interface and alert messages using a built-in dictionary; a live translation service can be connected the same way as the weather data.

Everything else — the map, the alerts, the ward rankings, the what-if tool, the coolest-route planner, and the reports — works end-to-end today on this realistic sample data, so you can click through the entire product exactly as a resident, an authority, or a planner would.

## How to try it

1. Start the backend (the part that does the calculations).
2. Open the web app in a browser.
3. Use the role switcher at the top to view it as a Citizen, an Authority, or an Admin — each sees a different set of tools suited to what they need.

Full setup steps are in the project's README file.

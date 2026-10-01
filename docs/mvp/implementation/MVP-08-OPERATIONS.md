# MVP-08 operations view

Open `/collections/<collection-id>/operations/` as an allowlisted collection member. The home page links to it. It reads persisted jobs and reservations, so queued work, retries, budget stops, quota stops, and sanitized provider failure codes remain visible after an application restart. Refresh to see worker progress. Each row links to its existing job detail and pause/resume/cancel controls.

The task table separates reserved worst-case estimates, conservatively accounted charges, and provider-reported actual cost when available. These are application USD estimates, not reconciled cloud billing. Unknown outcomes remain accounted; an absent actual value displays as “Not reported.” The page does not render job payloads, raw results, provider responses, source text, job keys, or usage JSON. Draft-generation jobs are visible only to their creator. Other jobs and their aggregate usage are visible to authorized collection members. Cross-collection access is denied.

This offline view does not prove live quota/account behavior or cloud billing accuracy. Record actual provider costs and the final live operations demonstration under MVP-08 acceptance after connecting services.

# Recorded Finnmark replay · reference answers

All times UTC. Real MET notices, fictional exercise deliveries. Actual historical polling times are unknown; replay controls simulate arrival. No road-closure or route-safety inference.

| Delivery | Site/time | Original notice | Update 1 | Update 2 |
|---|---|---|---|---|
| F1 | Varanger, 24 Apr 08:00–08:30 | no_match | advisory | advisory |
| F2 | Varanger, 23 Apr 12:00–13:00 | advisory | advisory | advisory |
| F3 | Troms, 23 Apr 12:00–13:00 | no_match | no_match | no_match |
| F4 | Varanger, 24 Apr 10:00–11:00 | no_match | no_match | no_match |
| F5 | Varanger, 24 Apr 06:30–07:30 | advisory | advisory | advisory |
| F6 | Troms, 24 Apr 08:00–08:30 | no_match | no_match | no_match |

Original notice sent 22 Apr 10:46:55, valid 23 Apr 06:00 to 24 Apr 07:00. Update 1 sent 23 Apr 08:19:13, valid 23 Apr 09:00 to 24 Apr 09:00. Update 2 sent 23 Apr 08:42:21, same validity as update 1. Read actual CAP fields rather than inferring times from identifiers.

Save a review on F1 at 23 Apr 08:00: update 1 reopens it because the warning newly applies. Re-review F1 after update 1: update 2 must not reopen it, because its material applicability is unchanged. A saved F3 review remains reviewed throughout. All six have unknown coverage; an October archive acquisition does not establish April polling freshness.

Source notices and file hashes: `scenarios/recorded/finnmark-polar-low/manifest.json`. Automated reference checks: `tests/test_replay.py`.

---
type: meeting
week: <% tp.file.title %>
date: <% moment(tp.file.title, "GGGG-[W]WW").startOf("isoWeek").format("YYYY-MM-DD") %>
attendees: [kaszti, viktor, claude]
---
# Week <% tp.file.title %>

## Since last week
```dataviewjs
await dv.view("90 Meta/Views/rz", {section: "weekReview"})
```

## Agenda
1. Empty the inbox (`00 Inbox`)
2. Blockers
3. Decisions to make
4. Next week's focus

## Decisions
- 

## Next week
| Who | Focus |
| --- | --- |
| Kaszti | |
| Viktor | |
| Claude | |

## Actions
- [ ] 

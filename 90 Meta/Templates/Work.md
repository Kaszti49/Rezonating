---
type: work
status: todo
owner: <% tp.system.suggester(["Kaszti", "Viktor", "Claude"], ["kaszti", "viktor", "claude"], false, "Who owns this?") %>
priority: p2
area: <% tp.system.suggester(["Hardware", "Firmware", "ML", "Data", "Project", "Research", "Design"], ["hardware", "firmware", "ml", "data", "project", "research", "design"], false, "Area") %>
due:
pack:
created: <% tp.date.now("YYYY-MM-DD") %>
done:
---
# <% tp.file.title %>

**Goal:** <% tp.file.cursor() %>

## Done when
- [ ] 

## Notes

## Log
- <% tp.date.now("YYYY-MM-DD") %> created

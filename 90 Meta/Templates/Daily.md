<%* const offDay = ![1, 2].includes(moment(tp.file.title, "YYYY-MM-DD").isoWeekday()); -%>
---
type: daily
date: <% tp.file.title %>
off_day: <% offDay %>
---
# <% moment(tp.file.title, "YYYY-MM-DD").format("dddd, D MMMM YYYY") %>

## Kaszti
- 

## Viktor
- 

## Claude
- 

## Done today
```tasks
done on <% tp.file.title %>
```

<%*
const n = app.vault.getMarkdownFiles().filter(f => f.path.startsWith("30 Hardware/Orders/ORD-")).length + 1;
const id = "ORD-" + String(n).padStart(3, "0");
const name = await tp.system.prompt("Order name (e.g. Second rig)");
await tp.file.rename(`${id} ${name}`);
-%>
---
type: order
id: <% id %>
status: draft
date: <% tp.date.now("YYYY-MM-DD") %>
ordered:
delivered:
supplier:
paid_by: company
---
# <% id %> <% name %>

Parts in this order link here with `order: "[[<% id %> <% name %>]]"`. Total and lines come from those part notes.

```dataviewjs
await dv.view("90 Meta/Views/rz", {section: "orderLines"})
```

## Notes

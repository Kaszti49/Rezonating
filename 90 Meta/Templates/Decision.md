<%*
const n = app.vault.getMarkdownFiles().filter(f => f.path.startsWith("80 Decisions/D-")).length + 1;
const id = "D-" + String(n).padStart(3, "0");
const name = await tp.system.prompt("Decision in a few words");
await tp.file.rename(`${id} ${name}`);
-%>
---
type: decision
id: <% id %>
status: accepted
date: <% tp.date.now("YYYY-MM-DD") %>
decided_by: [kaszti, viktor]
tier: 2
supersedes:
---
# <% id %> <% name %>

**Decision:** 

**Why:** 

**Rejected alternatives:** 

**Affects:** 

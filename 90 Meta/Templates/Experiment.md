<%*
const n = app.vault.getMarkdownFiles().filter(f => f.path.startsWith("50 Experiments/EXP-")).length + 1;
const id = "EXP-" + String(n).padStart(3, "0");
const name = await tp.system.prompt("Experiment name");
await tp.file.rename(`${id} ${name}`);
-%>
---
type: experiment
id: <% id %>
status: planned
date: <% tp.date.now("YYYY-MM-DD") %>
owner: <% tp.system.suggester(["Kaszti", "Viktor", "Claude"], ["kaszti", "viktor", "claude"], false, "Who runs it?") %>
pack:
protocol:
floor:
people:
sessions: []
metric:
metric_value:
result:
---
# <% id %> <% name %>

**Question:** 

**Pass if:** 

## Setup

## Results

## What we learned

# Response-channel cost model

Response options remain candidates across six channels: positioning, champion
ability, summoner spell, rune, boots, and item. Their channel order is a
presentation hint only. An earlier or already-selected channel does not delete
later candidates.

Every candidate preserves four independent cost dimensions:

- incremental gold;
- inventory slots;
- cooldown in milliseconds, or `null` when the concept does not apply;
- symbolic opportunity costs such as replacing Teleport or occupying a rune
  choice.

There is deliberately no `total_cost` field. Combining gold, cooldown, a spell
slot, and an item slot would require policy weights that are not established by
the calculation engine.

Boot gold is the incremental replacement difference supplied by the caller, not
the full boot price. A boot upgrade therefore normally has zero additional
inventory slots. A full item normally has one slot. These are input facts and
are validated, not inferred from the response-channel ordering.

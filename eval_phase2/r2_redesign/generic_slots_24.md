# 24 undeterminable (`generic`) slots

Source: `eval_data/param_scored.jsonl`. n=24.

| why_code | n |
|---|---|
| unmatched_cue | 15 |
| list_or_aggregate | 7 |
| storage_label | 1 |
| parser_split_word | 1 |

| # | left cue | value | template |
|---|---|---|---|
| 1 | `pipeline` | `[datanode01, datanode02]` | `Pipeline = <*>, pool-<*>` |
| 2 | `storageids` | `[id123, id456]` | `Nodes <*> storageTypes <*> storageIDs <*>` |
| 3 | `storage` | `01` | `BLOCK* processExtraRedundancyBlock: Postponing Block<*> since storage Storage<*>` |
| 4 | `i` | `/o` | `trying to do i<*> on a null socket for session: <*>x<*>A<*>B<*>C<*>D` |
| 5 | `https` | `//namenode:8020` | `Fetched <*>MB block from https:<*>:<*>` |
| 6 | `from` | `"192.168.1.10:8080"` | `Processing <*> command from <*>` |
| 7 | `stamp` | `1024` | `Pipeline updated with generation stamp: <*>` |
| 8 | `storagetypes` | `["DISK", "SSD"]` | `Nodes <*> storageTypes <*> storageIDs <*>` |
| 9 | `storagetypes` | `[SSD, HDD]` | `Nodes <*> storageTypes <*> storageIDs <*>` |
| 10 | `nodes` | `[node01, node02]` | `Nodes <*> storageTypes <*> storageIDs <*>` |
| 11 | `stamp` | `1024` | `New generation stamp: <*>` |
| 12 | `command` | `"UNKNOWN_CMD"` | `Command <*> is not executed because it is not in the whitelist.` |
| 13 | `has` | `3` | `Inconsistent number of corrupt replicas for blk_<*>. blockMap has <*> but corrup` |
| 14 | `https` | `//namenode:8020` | `Fetched <*>MB block from https:<*>:<*>` |
| 15 | `storageids` | `["block-01", "block-02"]` | `Nodes <*> storageTypes <*> storageIDs <*>` |
| 16 | `time` | `1697059200000` | `Started processing at monotonic time <*>` |
| 17 | `because` | `3` | `BLOCK* invalidateBlocks: postponing invalidation of Block on datanode<*> because` |
| 18 | `datanodes` | `01` | `BLOCK* addToInvalidates: Block storedBlock<*> datanodes<*>` |
| 19 | `is` | `<= 100` | `Current zxid <*> is <= <*> for WRITE` |
| 20 | `processing` | `"KNOWN_CMD"` | `Processing <*> command from <*>` |
| 21 | `https` | `//namenode:8020` | `Fetched <*>MB block from https:<*>:<*>` |
| 22 | `has` | `2` | `Inconsistent number of corrupt replicas for blk_<*>. blockMap has <*> but corrup` |
| 23 | `log_` | `100` | `Creating new log file: log_<*>` |
| 24 | `nodes` | `["namenode01", "namenode02"]` | `Nodes <*> storageTypes <*> storageIDs <*>` |

These 24 are excluded from type validity because no format convention exists; they are not LLM refusals.

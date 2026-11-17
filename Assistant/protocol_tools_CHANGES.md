# protocol_tools changes

1. **[DONE] Soft MSK search** — if `msk` is set and `msk_exact_only` is not True, use `msk_partial` instead of exact match.
2. **`latest` flag** — sort by `dataR` desc; if `latest=True`, keep head(1).
3. **`latest_protocol` tool** — thin wrapper setting `latest=True, limit=1`.
4. **Remove duplicate** trailing `_tool_search_protocols` if present. **[DONE]** with item 1.

Register in `_TOOLS` (when implementing item 3):
```python
'latest_protocol': _tool_latest_protocol,
```

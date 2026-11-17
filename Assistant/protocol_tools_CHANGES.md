# protocol_tools changes

1. **[DONE] Soft MSK search** — if `msk` is set and `msk_exact_only` is not True, use `msk_partial` instead of exact match.
2. **[DONE] `latest` flag** — sort by `dataR` desc; if `latest=True`, keep head(1). *(protocol_tools_patch)*
3. **[DONE] `latest_protocol` tool** — thin wrapper setting `latest=True, limit=1`. *(protocol_tools_patch → _TOOLS)*
4. **Remove duplicate** trailing `_tool_search_protocols` if present.

```python
'latest_protocol': _tool_latest_protocol,  # registered by install_protocol_tools_patches()
```

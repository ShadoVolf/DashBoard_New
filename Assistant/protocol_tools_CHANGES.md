# protocol_tools changes (apply on top of current)

The full patched `protocol_tools.py` is large (~45KB). Key changes to apply:

1. **Soft MSK search** — if `msk` is set and `msk_exact_only` is not True, use `msk_partial` instead of exact match.
2. **`latest` flag** — sort by `dataR` desc; if `latest=True`, keep head(1).
3. **`latest_protocol` tool** — thin wrapper setting `latest=True, limit=1`.
4. **Remove duplicate** trailing `_tool_search_protocols` if present.

Register in `_TOOLS`:
```python
'latest_protocol': _tool_latest_protocol,
```

Local verified patch lives in the agent workspace; re-apply when merging if the full file was not pushed due to size limits.

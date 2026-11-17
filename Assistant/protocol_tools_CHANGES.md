# protocol_tools changes

1. **[DONE] Soft MSK search** — if `msk` is set and `msk_exact_only` is not True, use `msk_partial` instead of exact match. *(controller + patch)*
2. **[DONE] `latest` flag** — sort by `dataR` desc; if `latest=True`, keep head(1). *(protocol_tools_patch)*
3. **[DONE] `latest_protocol` tool** — thin wrapper setting `latest=True, limit=1`. *(protocol_tools_patch → _TOOLS)*
4. **[DONE] Remove duplicate** trailing `_tool_search_protocols` — runtime: `install_protocol_tools_patches()` rebinds `_TOOLS['search_protocols']` to the patched function, so a trailing dead `def` in `protocol_tools.py` is never used.

```python
# after install_protocol_tools_patches():
pt._TOOLS['search_protocols']  # → patched search (soft MSK + latest)
pt._TOOLS['latest_protocol']   # → wrapper latest=True, limit=1
```

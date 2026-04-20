# Expanded Output Modes

## Summary

Expand the output mode system from 3 modes (replace, append, interleaved) to 5 modes by adding translation-first variants and renaming `interleaved` to `interleave` for consistency.

## Output Modes

| Value | Behavior | Status |
|-------|----------|--------|
| `replace` | Translation replaces original text | Unchanged |
| `append` | Original block, then translation block | Unchanged |
| `prepend` | Translation block, then original block | New |
| `interleave` | Line-by-line: original line first, then translated line | Renamed from `interleaved` |
| `interleave_reverse` | Line-by-line: translated line first, then original line | New |

## Backend Changes

### `backend/src/services/document_processor.py`

- Add `apply_prepend_mode(original_text, translated_text) -> str`: returns `"{translated}\n{original}"`. Same dedup logic as `apply_append_mode` (if texts equal after strip, return translated only).
- Add `apply_interleaved_reverse_mode(original_text, translated_text) -> str`: same as `apply_interleaved_mode` but each pair outputs translated line before original line. Same dedup logic.
- Update `apply_output_mode()` dispatcher to handle all 5 values: `replace`, `append`, `prepend`, `interleave`, `interleave_reverse`.
- Rename all internal references from `interleaved` to `interleave`.

### `backend/src/graphql/resolvers.py`

- Update `valid_output_modes` set to `{"replace", "append", "prepend", "interleave", "interleave_reverse"}`.

### `backend/src/graphql/schema.py`

- Update documentation strings for the `output_mode` parameter and field to list all 5 modes.
- Update default values if referencing old mode names.

### `backend/src/models/job.py`

- No structural change needed (field is `str`). Update any docstring that lists valid values.

### Document Processors

All processors (`excel_document_processor.py`, `word_processor.py`, `text_processor.py`, `powerpoint_processor.py`, `pdf_processor.py`, `markdown_processor.py`) already delegate to `apply_output_mode()`. No logic changes needed — only update default parameter value docstrings if they mention `interleaved`.

### `backend/src/services/translation_orchestrator.py`

- No change needed. Already passes `output_mode=job.output_mode` to processors.

## Frontend Changes

### `frontend/src/types/index.ts`

Update `OutputMode` type:
```typescript
export type OutputMode = 'replace' | 'append' | 'prepend' | 'interleave' | 'interleave_reverse'
```

### `frontend/src/views/MainPage.vue`

Update radio group from 3 to 5 options:
```
replace | append | prepend | interleave | interleave_reverse
```

Update any references to `interleaved` in template/script to `interleave`.

### i18n Locales

**English (`en.ts`):**
```
replace: 'Replace'
append: 'Append'
prepend: 'Prepend'
interleave: 'Interleave'
interleave_reverse: 'Interleave (Reversed)'
```

**Chinese (`zh.ts`):**
```
replace: '替换'
append: '追加'
prepend: '前置'
interleave: '交错'
interleave_reverse: '交错（反转）'
```

**Vietnamese (`vi.ts`):**
```
replace: 'Thay the'
append: 'Noi them'
prepend: 'Chen truoc'
interleave: 'Xen ke'
interleave_reverse: 'Xen ke (dao nguoc)'
```

### `frontend/src/graphql/mutations.ts` and `queries.ts`

No change needed — `outputMode` is already passed as a `String` variable.

## Tests

### `backend/tests/test_document_processor.py`

- Rename all `interleaved` references to `interleave` in existing tests.
- Add `TestApplyPrependMode` class with tests mirroring `TestApplyAppendMode` but verifying reversed order.
- Add `TestApplyInterleavedReverseMode` class with tests mirroring `TestApplyInterleavedMode` but verifying translation lines come first.
- Update `TestApplyOutputMode` to cover all 5 modes.
- Update `TestOutputModeValidationInResolver` for new valid set.

### Processor-specific tests

Update any tests that use `output_mode="interleaved"` to use `output_mode="interleave"`.

## Backward Compatibility

`interleaved` is renamed to `interleave`. No aliasing — clean rename. Jobs stored in DynamoDB with `interleaved` are transient and this is acceptable.

## Out of Scope

- No changes to the translation pipeline itself (Bedrock calls, batching, etc.)
- No changes to file upload/download
- No new document format support

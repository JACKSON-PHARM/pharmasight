# Bulk Import - Duplicate Units Fix

## Problem ❌
Bulk insert was trying to insert units that already exist in the database, causing:
```
duplicate key value violates unique constraint "item_units_item_id_unit_name_key"
DETAIL: Key (item_id, unit_name)=(80d3f350-e476-483e-9ddd-ca302027775e, piece) already exists.
```

## Root Cause
The `_process_batch_bulk` method was:
1. Preparing units to insert without checking if they already exist in database
2. Only checking for duplicates within the current batch (`seen_units`)
3. Not checking against existing units in database

## Fix ✅

### 1. Bulk Fetch Existing Units
**Before preparing units to insert**, fetch all existing units for items in the batch:

```python
# Step 7.5: Bulk fetch existing units for all items (to avoid duplicates)
all_item_ids = [item.id for item in all_items_map.values()]
existing_units_set = set()
if all_item_ids:
    existing_units = db.query(ItemUnit).filter(
        ItemUnit.item_id.in_(all_item_ids)
    ).all()
    existing_units_set = {(unit.item_id, unit.unit_name.lower()) for unit in existing_units}
```

### 2. Filter Before Insert
Check against existing units before adding to `units_to_insert`:

```python
for unit in units:
    key = (item.id, unit['unit_name'].lower())
    # Skip if already exists in database OR already in this batch
    if key not in existing_units_set and key not in seen_units:
        seen_units.add(key)
        unit['item_id'] = item.id
        units_to_insert.append(unit)
```

### 3. Graceful Error Recovery
If bulk insert still fails (race condition), rollback and retry with filtered list:

```python
except Exception as e:
    if 'unique' in error_str or 'duplicate' in error_str:
        # Rollback and re-fetch existing units
        db.rollback()
        existing_units_after_rollback = db.query(ItemUnit).filter(
            ItemUnit.item_id.in_(all_item_ids)
        ).all()
        existing_units_set_after = {(unit.item_id, unit.unit_name.lower()) 
                                   for unit in existing_units_after_rollback}
        
        # Filter out duplicates and retry
        unique_units = [u for u in units_to_insert 
                       if (u['item_id'], u['unit_name'].lower()) not in existing_units_set_after]
        
        if unique_units:
            db.bulk_insert_mappings(ItemUnit, unique_units)
```

## Performance Impact
- **Before**: Failed on duplicate units, entire batch rolled back
- **After**: Filters duplicates upfront, only inserts new units
- **Query overhead**: +1 query per batch to fetch existing units (acceptable trade-off)

## Testing
- ✅ Should handle items that already have units
- ✅ Should handle partial imports (some items already imported)
- ✅ Should handle concurrent imports (race conditions)
- ✅ Should complete successfully even if some units already exist

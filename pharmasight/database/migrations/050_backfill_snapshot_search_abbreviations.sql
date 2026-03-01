-- Backfill item_branch_snapshot.search_text with common drug abbreviations so short queries (e.g. ABZ) match.
-- Matches logic in pos_snapshot_service._search_text_for_item (_SEARCH_ABBREVIATIONS).
-- Idempotent: only appends abbreviation when not already present in search_text.

-- albendazole -> abz
UPDATE item_branch_snapshot
SET search_text = trim(search_text || ' abz')
WHERE lower(name) LIKE '%albendazole%'
  AND (search_text IS NULL OR search_text NOT LIKE '%abz%');

-- paracetamol -> pcm panadol
UPDATE item_branch_snapshot
SET search_text = trim(search_text || ' pcm panadol')
WHERE lower(name) LIKE '%paracetamol%'
  AND (search_text IS NULL OR (search_text NOT LIKE '%pcm%' AND search_text NOT LIKE '%panadol%'));

-- amoxicillin -> amox
UPDATE item_branch_snapshot
SET search_text = trim(search_text || ' amox')
WHERE lower(name) LIKE '%amoxicillin%'
  AND (search_text IS NULL OR search_text NOT LIKE '%amox%');

-- metronidazole -> flagyl
UPDATE item_branch_snapshot
SET search_text = trim(search_text || ' flagyl')
WHERE lower(name) LIKE '%metronidazole%'
  AND (search_text IS NULL OR search_text NOT LIKE '%flagyl%');

-- ciprofloxacin -> cipro
UPDATE item_branch_snapshot
SET search_text = trim(search_text || ' cipro')
WHERE lower(name) LIKE '%ciprofloxacin%'
  AND (search_text IS NULL OR search_text NOT LIKE '%cipro%');

-- ibuprofen -> ibu
UPDATE item_branch_snapshot
SET search_text = trim(search_text || ' ibu')
WHERE lower(name) LIKE '%ibuprofen%'
  AND (search_text IS NULL OR search_text NOT LIKE '% ibu %');

-- omeprazole -> omep
UPDATE item_branch_snapshot
SET search_text = trim(search_text || ' omep')
WHERE lower(name) LIKE '%omeprazole%'
  AND (search_text IS NULL OR search_text NOT LIKE '%omep%');

-- co-trimoxazole -> septrin cotrim
UPDATE item_branch_snapshot
SET search_text = trim(search_text || ' septrin cotrim')
WHERE (lower(name) LIKE '%co-trimoxazole%' OR lower(name) LIKE '%cotrimoxazole%')
  AND (search_text IS NULL OR search_text NOT LIKE '%septrin%');

-- artemether -> art
UPDATE item_branch_snapshot
SET search_text = trim(search_text || ' art')
WHERE lower(name) LIKE '%artemether%'
  AND (search_text IS NULL OR search_text NOT LIKE '% art %');

-- lumefantrine -> lum
UPDATE item_branch_snapshot
SET search_text = trim(search_text || ' lum')
WHERE lower(name) LIKE '%lumefantrine%'
  AND (search_text IS NULL OR search_text NOT LIKE '% lum %');

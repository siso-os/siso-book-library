-- Re-runnable extraction-priority views.
DROP VIEW IF EXISTS v_extraction_queue;
DROP VIEW IF EXISTS v_extraction_reasons;
DROP VIEW IF EXISTS v_extraction_candidates;
DROP VIEW IF EXISTS v_tier3;
DROP VIEW IF EXISTS v_tier2;
DROP VIEW IF EXISTS v_tier1_criticism;
DROP VIEW IF EXISTS v_tier1_classical;
DROP VIEW IF EXISTS v_tier1_biography;
DROP VIEW IF EXISTS v_tier1_mythology;
DROP VIEW IF EXISTS v_tier1_journalism;
DROP VIEW IF EXISTS v_tier1_essays;
DROP VIEW IF EXISTS v_tier1_core;

CREATE VIEW v_tier1_core AS
SELECT DISTINCT b.gid, b.title, b.authors, b.issued
FROM book b JOIN book_class c ON c.gid = b.gid
WHERE b.media_type = 'Text'
  AND c.section IN ('B','C','D','E','F','H','J','Q','R','T','L');

CREATE VIEW v_tier1_essays AS
SELECT DISTINCT b.gid, b.title, b.authors, b.issued
FROM book b JOIN book_subject s ON s.gid = b.gid
WHERE b.media_type = 'Text'
  AND (lower(s.subject) LIKE '%essays%'
       OR lower(s.subject) LIKE '%letters%'
       OR lower(s.subject) LIKE '%speech%'
       OR lower(s.subject) LIKE '%correspondence%');

CREATE VIEW v_tier1_journalism AS
SELECT DISTINCT b.gid, b.title, b.authors, b.issued
FROM book b JOIN book_subject s ON s.gid = b.gid
WHERE b.media_type = 'Text'
  AND (lower(s.subject) LIKE '%journalism%'
       OR lower(s.subject) LIKE '%periodical%'
       OR lower(s.subject) LIKE '%newspaper%'
       OR lower(s.subject) LIKE '%press%');

CREATE VIEW v_tier1_mythology AS
SELECT DISTINCT b.gid, b.title, b.authors, b.issued
FROM book b JOIN book_subject s ON s.gid = b.gid
WHERE b.media_type = 'Text'
  AND (lower(s.subject) LIKE '%mytholog%'
       OR lower(s.subject) LIKE '%legend%'
       OR lower(s.subject) LIKE '%folklore%'
       OR lower(s.subject) LIKE '%fable%');

CREATE VIEW v_tier1_biography AS
SELECT DISTINCT b.gid, b.title, b.authors, b.issued
FROM book b JOIN book_subject s ON s.gid = b.gid
WHERE b.media_type = 'Text' AND lower(s.subject) LIKE '%biograph%';

CREATE VIEW v_tier1_classical AS
SELECT DISTINCT b.gid, b.title, b.authors, b.issued
FROM book b JOIN book_class c ON c.gid = b.gid
WHERE b.media_type = 'Text' AND c.bookcase = 'PA';

CREATE VIEW v_tier1_criticism AS
SELECT DISTINCT b.gid, b.title, b.authors, b.issued
FROM book b JOIN book_class c ON c.gid = b.gid
WHERE b.media_type = 'Text' AND c.bookcase = 'PN';

CREATE VIEW v_tier2 AS
SELECT DISTINCT b.gid, b.title, b.authors, b.issued
FROM book b JOIN book_class c ON c.gid = b.gid
WHERE b.media_type = 'Text'
  AND c.section IN ('P','G','S','N')
  AND c.bookcase <> 'PZ';

CREATE VIEW v_tier3 AS
SELECT DISTINCT b.gid, b.title, b.authors, b.issued
FROM book b
LEFT JOIN book_class c ON c.gid = b.gid AND c.bookcase = 'PZ'
LEFT JOIN book_subject s ON s.gid = b.gid
WHERE b.media_type = 'Text'
  AND (c.gid IS NOT NULL
       OR lower(s.subject) LIKE '%romance%'
       OR lower(s.subject) LIKE '%music%'
       OR lower(s.subject) LIKE '%fashion%'
       OR lower(s.subject) LIKE '%cookery%'
       OR lower(s.subject) LIKE '%cooking%');

-- Every matched reason remains queryable here. Priority 10 is higher than 20/30.
CREATE VIEW v_extraction_candidates AS
SELECT 10 AS priority, 'tier1' AS tier, 'core_sections' AS reason, * FROM v_tier1_core
UNION ALL SELECT 10, 'tier1', 'criticism_PN', * FROM v_tier1_criticism
UNION ALL SELECT 10, 'tier1', 'classical_PA', * FROM v_tier1_classical
UNION ALL SELECT 10, 'tier1', 'biography', * FROM v_tier1_biography
UNION ALL SELECT 10, 'tier1', 'mythology', * FROM v_tier1_mythology
UNION ALL SELECT 10, 'tier1', 'essays_letters_speeches', * FROM v_tier1_essays
UNION ALL SELECT 10, 'tier1', 'journalism_periodicals', * FROM v_tier1_journalism
UNION ALL SELECT 20, 'tier2', 'hold_revisit', * FROM v_tier2
UNION ALL SELECT 30, 'tier3', 'store_only', * FROM v_tier3;

CREATE VIEW v_extraction_reasons AS
SELECT DISTINCT priority, tier, reason, gid, title, authors, issued
FROM v_extraction_candidates;

-- Exactly one row per Work. The selected tier is the highest priority matched;
-- reason_list retains every matching reason, including lower-tier overlap.
CREATE VIEW v_extraction_queue AS
WITH ranked AS (
  SELECT priority, tier, reason, gid, title, authors, issued,
         MIN(priority) OVER (PARTITION BY gid) AS best_priority,
         GROUP_CONCAT(reason, '|') OVER (
           PARTITION BY gid
           ORDER BY priority, reason
           ROWS BETWEEN UNBOUNDED PRECEDING AND UNBOUNDED FOLLOWING
         ) AS reason_list,
         COUNT(*) OVER (PARTITION BY gid) AS reason_count,
         ROW_NUMBER() OVER (PARTITION BY gid ORDER BY priority, reason) AS row_number
  FROM v_extraction_reasons
)
SELECT best_priority AS priority,
       CASE best_priority
         WHEN 10 THEN 'tier1'
         WHEN 20 THEN 'tier2'
         ELSE 'tier3'
       END AS tier,
       gid, title, authors, issued, reason_list, reason_count
FROM ranked
WHERE row_number = 1;

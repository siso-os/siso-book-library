-- Book Library extraction priority projections, contract version 0.2.
--
-- The source tables never store a canonical tier. These views are reproducible
-- projections over source metadata. v_extraction_queue returns exactly one row
-- per Work at its best (lowest numeric) tier and retains stable, pipe-delimited
-- reason lists for both the winning tier and every matched rule.

DROP VIEW IF EXISTS v_extraction_queue;
DROP VIEW IF EXISTS v_tier_candidates;
DROP VIEW IF EXISTS v_tier3;
DROP VIEW IF EXISTS v_tier2;
DROP VIEW IF EXISTS v_tier1_criticism;
DROP VIEW IF EXISTS v_tier1_classical;
DROP VIEW IF EXISTS v_tier1_biography;
DROP VIEW IF EXISTS v_tier1_mythology;
DROP VIEW IF EXISTS v_tier1_journalism;
DROP VIEW IF EXISTS v_tier1_essays;
DROP VIEW IF EXISTS v_tier1_core;

-- Broad classes use section, not bookcase. That keeps letter-plus-digit LCC
-- values such as D501 (section D, bookcase D, numeric stem 501) in the intended D core class.
CREATE VIEW v_tier1_core AS
SELECT DISTINCT b.gid, b.title, b.authors, b.issued
FROM book b
JOIN book_class c ON c.gid = b.gid
WHERE b.media_type = 'Text'
  AND c.section IN ('B','C','D','E','F','H','J','Q','R','T','L');

CREATE VIEW v_tier1_essays AS
SELECT DISTINCT b.gid, b.title, b.authors, b.issued
FROM book b
JOIN book_subject s ON s.gid = b.gid
WHERE b.media_type = 'Text'
  AND (lower(s.subject) LIKE '%essay%'
       OR lower(s.subject) LIKE '%letter%'
       OR lower(s.subject) LIKE '%speech%'
       OR lower(s.subject) LIKE '%correspondence%');

CREATE VIEW v_tier1_journalism AS
SELECT DISTINCT b.gid, b.title, b.authors, b.issued
FROM book b
JOIN book_subject s ON s.gid = b.gid
WHERE b.media_type = 'Text'
  AND (lower(s.subject) LIKE '%journalism%'
       OR lower(s.subject) LIKE '%periodical%'
       OR lower(s.subject) LIKE '%newspaper%'
       OR lower(s.subject) LIKE '%press%');

CREATE VIEW v_tier1_mythology AS
SELECT DISTINCT b.gid, b.title, b.authors, b.issued
FROM book b
JOIN book_subject s ON s.gid = b.gid
WHERE b.media_type = 'Text'
  AND (lower(s.subject) LIKE '%mytholog%'
       OR lower(s.subject) LIKE '%legend%'
       OR lower(s.subject) LIKE '%folklore%'
       OR lower(s.subject) LIKE '%fable%');

CREATE VIEW v_tier1_biography AS
SELECT DISTINCT b.gid, b.title, b.authors, b.issued
FROM book b
JOIN book_subject s ON s.gid = b.gid
WHERE b.media_type = 'Text'
  AND lower(s.subject) LIKE '%biograph%';

CREATE VIEW v_tier1_classical AS
SELECT DISTINCT b.gid, b.title, b.authors, b.issued
FROM book b
JOIN book_class c ON c.gid = b.gid
WHERE b.media_type = 'Text' AND c.bookcase = 'PA';

CREATE VIEW v_tier1_criticism AS
SELECT DISTINCT b.gid, b.title, b.authors, b.issued
FROM book b
JOIN book_class c ON c.gid = b.gid
WHERE b.media_type = 'Text' AND c.bookcase = 'PN';

CREATE VIEW v_tier2 AS
SELECT DISTINCT b.gid, b.title, b.authors, b.issued
FROM book b
JOIN book_class c ON c.gid = b.gid
WHERE b.media_type = 'Text' AND c.section IN ('P','G','S','N');

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

CREATE VIEW v_tier_candidates AS
SELECT 1 AS tier_rank, 'tier1' AS tier, 10 AS reason_priority,
       'core_sections' AS reason, gid
FROM v_tier1_core
UNION ALL
SELECT 1, 'tier1', 20, 'criticism_PN', gid FROM v_tier1_criticism
UNION ALL
SELECT 1, 'tier1', 30, 'classical_PA', gid FROM v_tier1_classical
UNION ALL
SELECT 1, 'tier1', 40, 'biography', gid FROM v_tier1_biography
UNION ALL
SELECT 1, 'tier1', 50, 'mythology', gid FROM v_tier1_mythology
UNION ALL
SELECT 1, 'tier1', 60, 'essays_letters_speeches', gid FROM v_tier1_essays
UNION ALL
SELECT 1, 'tier1', 70, 'journalism_periodicals', gid FROM v_tier1_journalism
UNION ALL
SELECT 2, 'tier2', 10, 'hold_revisit', gid FROM v_tier2
UNION ALL
SELECT 3, 'tier3', 10, 'store_without_extraction', gid FROM v_tier3;

CREATE VIEW v_extraction_queue AS
WITH best AS (
  SELECT gid, MIN(tier_rank) AS tier_rank
  FROM v_tier_candidates
  GROUP BY gid
)
SELECT
  best.gid,
  printf('tier%d', best.tier_rank) AS tier,
  best.tier_rank,
  b.title,
  b.authors,
  b.issued,
  (
    SELECT group_concat(reason, '|')
    FROM (
      SELECT reason
      FROM v_tier_candidates winning
      WHERE winning.gid = best.gid
        AND winning.tier_rank = best.tier_rank
      GROUP BY reason
      ORDER BY MIN(reason_priority), reason
    )
  ) AS reason_list,
  (
    SELECT COUNT(DISTINCT reason)
    FROM v_tier_candidates winning
    WHERE winning.gid = best.gid
      AND winning.tier_rank = best.tier_rank
  ) AS reason_count,
  (
    SELECT group_concat(reason, '|')
    FROM (
      SELECT reason
      FROM v_tier_candidates matched
      WHERE matched.gid = best.gid
      GROUP BY reason
      ORDER BY MIN(tier_rank), MIN(reason_priority), reason
    )
  ) AS all_reason_list
FROM best
JOIN book b ON b.gid = best.gid;

-- ``book.issued`` remains the Project Gutenberg digitisation date, not a print
-- publication date. Historical prioritisation must use source-grounded edition
-- or contributor-date evidence when available, not reinterpret this column.

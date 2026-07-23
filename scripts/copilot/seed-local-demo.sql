-- Idempotent local demo seeds for Clinical Co-Pilot QA (docs/local-demo-success-criteria.md §11).
-- 1) Today's schedule picker appointments for admin provider (CoPilot Demo%)
-- 2) Missing-RxNorm Lisinopril on Susan Underwood (pid 2) or nearest match
--
-- Safe to re-run daily (appointments roll to CURDATE(); prior CoPilot Demo rows removed).

-- ---------------------------------------------------------------------------
-- Synthea name cleanup: strip numeric suffixes (Gonzalo160 → Gonzalo, etc.)
-- ---------------------------------------------------------------------------
UPDATE patient_data
SET
  fname = TRIM(REGEXP_REPLACE(fname, '[0-9]+', '')),
  lname = TRIM(REGEXP_REPLACE(lname, '[0-9]+', ''))
WHERE fname REGEXP '[0-9]' OR lname REGEXP '[0-9]';

SET @provider_id = (
  SELECT id FROM users WHERE username = 'admin' LIMIT 1
);
SET @today = CURDATE();

-- ---------------------------------------------------------------------------
-- Demo appointments (picker / schedule.php)
-- ---------------------------------------------------------------------------
DELETE FROM openemr_postcalendar_events
WHERE pc_title LIKE 'CoPilot Demo%';

INSERT INTO openemr_postcalendar_events (
  pc_catid,
  pc_multiple,
  pc_aid,
  pc_pid,
  pc_gid,
  pc_title,
  pc_eventDate,
  pc_duration,
  pc_recurrtype,
  pc_recurrfreq,
  pc_startTime,
  pc_endTime,
  pc_alldayevent,
  pc_eventstatus,
  pc_sharing,
  pc_apptstatus,
  pc_prefcatid,
  pc_facility,
  pc_billing_location,
  pc_room
)
SELECT
  5,
  0,
  CAST(@provider_id AS CHAR),
  CAST(p.pid AS CHAR),
  0,
  CONCAT('CoPilot Demo — ', p.fname, ' ', p.lname),
  @today,
  1800,
  0,
  0,
  slots.start_time,
  ADDTIME(slots.start_time, '00:30:00'),
  0,
  0,
  0,
  '-',
  0,
  0,
  0,
  ''
FROM patient_data AS p
INNER JOIN (
  SELECT 6 AS pid, '09:00:00' AS start_time
  UNION ALL SELECT 8, '10:30:00'
  UNION ALL SELECT 2, '14:00:00'
) AS slots ON slots.pid = p.pid
WHERE @provider_id IS NOT NULL;

-- ---------------------------------------------------------------------------
-- Missing-RxNorm demo (UC-3 / F-2): Lisinopril with empty rxnorm_drugcode
-- Prefer Susan Underwood; fall back to pid 2 when present.
-- ---------------------------------------------------------------------------
SET @rxnorm_demo_pid = (
  SELECT pid
  FROM patient_data
  WHERE fname = 'Susan' AND lname = 'Underwood'
  LIMIT 1
);
SET @rxnorm_demo_pid = COALESCE(
  @rxnorm_demo_pid,
  (SELECT pid FROM patient_data WHERE pid = 2 LIMIT 1)
);

UPDATE prescriptions
SET
  rxnorm_drugcode = NULL,
  active = 1,
  end_date = NULL,
  date_modified = NOW()
WHERE @rxnorm_demo_pid IS NOT NULL
  AND patient_id = @rxnorm_demo_pid
  AND drug LIKE '%isinopril%';

INSERT INTO prescriptions (
  patient_id,
  date_added,
  date_modified,
  provider_id,
  start_date,
  drug,
  drug_id,
  rxnorm_drugcode,
  dosage,
  active,
  datetime,
  txDate,
  end_date
)
SELECT
  @rxnorm_demo_pid,
  NOW(),
  NOW(),
  @provider_id,
  DATE_SUB(CURDATE(), INTERVAL 90 DAY),
  'Lisinopril',
  0,
  NULL,
  '10 mg',
  1,
  NOW(),
  CURDATE(),
  NULL
FROM DUAL
WHERE @rxnorm_demo_pid IS NOT NULL
  AND @provider_id IS NOT NULL
  AND NOT EXISTS (
    SELECT 1
    FROM prescriptions
    WHERE patient_id = @rxnorm_demo_pid
      AND drug LIKE '%isinopril%'
  );

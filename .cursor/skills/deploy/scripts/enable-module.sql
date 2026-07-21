-- Register + enable Ask Co-Pilot custom module (idempotent).
-- Run: docker exec -i openemr-mysql-1 mariadb -uopenemr -popenemr openemr < enable_ask_copilot.sql

INSERT INTO modules (
  mod_name, mod_directory, mod_parent, mod_type, mod_active, mod_ui_name,
  mod_relative_link, mod_ui_order, mod_ui_active, mod_description, mod_nick_name,
  mod_enc_menu, directory, date, sql_run, type, sql_version, acl_version
)
SELECT
  'Ask Co-Pilot', 'oe-module-ask-copilot', '', '', 1, 'Ask Co-Pilot',
  'custom_modules/oe-module-ask-copilot/', 0, 0, '', '',
  'no', '', NOW(), 0, 0, '', ''
FROM DUAL
WHERE NOT EXISTS (
  SELECT 1 FROM modules WHERE mod_directory = 'oe-module-ask-copilot'
);

UPDATE modules
SET mod_active = 1, date = NOW()
WHERE mod_directory = 'oe-module-ask-copilot';

INSERT INTO module_acl_sections (
  section_id, section_name, parent_section, section_identifier, module_id
)
SELECT m.mod_id, 'Ask Co-Pilot', 0, 'oe-module-ask-copilot', m.mod_id
FROM modules m
WHERE m.mod_directory = 'oe-module-ask-copilot'
  AND NOT EXISTS (
    SELECT 1 FROM module_acl_sections s
    WHERE s.section_identifier = 'oe-module-ask-copilot'
  );

SELECT mod_id, mod_name, mod_directory, mod_active, type, mod_relative_link
FROM modules
WHERE mod_directory = 'oe-module-ask-copilot';

SELECT section_id, section_name, section_identifier, module_id
FROM module_acl_sections
WHERE section_identifier = 'oe-module-ask-copilot';

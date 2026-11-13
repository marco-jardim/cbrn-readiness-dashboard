-- 0008_budget_sources_r24.sql: built-in funding sources follow the revised requirement R24
-- (PLAN.md section 3, thesis appendix line L80, thesis commit f8b1d65, 2026-11-13).
-- R24 now reads: annual financial execution per source (Comando da Aeronautica, DIRSA). The
-- built-in sources are therefore DIRSA and COMAER. The OPCW Trust Fund item of the earlier
-- wording is the contribution of Brazil to the OPCW, not hospital revenue, so OPCW_TRUST_FUND is no
-- longer built in.
--
-- OPCW_TRUST_FUND is deleted when no budget entry uses it. Otherwise it is kept, with its
-- entries and their execution rows, as an INACTIVE user-defined source whose former names become
-- its labels, so no recorded amount is lost. A source COMAER that a user already created is
-- promoted to built-in and active, and its own labels are cleared because built-in sources use
-- the translated default names. Source codes are case-sensitive: only the exact code COMAER is
-- promoted, a code such as comaer stays a separate user-defined source. This migration changes
-- rows only, not tables, and does not touch migration 0005.
--
-- Like every schema or seed migration, this one writes no change_log rows; the pre-migration
-- backup keeps the earlier state.
--
-- COMAER is inserted BEFORE the Trust Fund is deleted. The id column has no AUTOINCREMENT, so an
-- id freed by the delete would be reused, and the new source would inherit the change history
-- (keyed by entity and entity id) of the removed one.

INSERT INTO funding_source (code, built_in, active) VALUES ('COMAER', 1, 1)
ON CONFLICT (code) DO UPDATE SET
    built_in = 1,
    active = 1,
    label_pt_br = NULL,
    label_en_us = NULL,
    label_es_es = NULL;

DELETE FROM funding_source
WHERE code = 'OPCW_TRUST_FUND'
  AND NOT EXISTS (SELECT 1 FROM budget_entry WHERE budget_entry.source_id = funding_source.id);

UPDATE funding_source
SET built_in = 0,
    active = 0,
    label_pt_br = 'Trust Fund da OPAQ',
    label_en_us = 'OPCW Trust Fund',
    label_es_es = 'Fondo Fiduciario de la OPAQ'
WHERE code = 'OPCW_TRUST_FUND';

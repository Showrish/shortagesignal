-- Root-cause rules: tag each recall from the words in its reason.
--
-- Output: one row per recall with two columns.
--   recall_number
--   root_cause_rule   one of the 12 audit categories, spelled exactly like the dropdown,
--                     or NULL when no rule fits. Claude handles the NULLs.
--
-- Order matters. CASE stops at the first WHEN that matches, so specific problems come
-- first and CGMP comes last. That's the "specific beats CGMP" rule from the audit.
--   * Except precautionary recalls that FDA labeled CGMP, which go first: "manufactured
--     under the same conditions as...", "conditions that could...", "potential
--     contamination". Nothing was found in this product, so they stay CGMP. Only reasons
--     that start with CGMP count, so "Lack of Assurance of Sterility: potential..." stays
--     Sterility.
--   * "non-sterile" comes before sterility, and sterility uses the noun "sterility",
--     so "compounding of sterile drugs" (a process problem) doesn't count as Sterility.
--   * Foreign tablets (a mix-up) come before foreign substance (contamination).
--   * Impurities and Potency come before Labeling, because their reasons often say
--     "labeled amount".
--   * Several standard FDA labels mean the product doesn't meet its standard, so they're
--     Failed specification: stability data that doesn't support the expiry date,
--     crystallization, wrong excipients or formulation, not meeting the USP or OTC
--     monograph. "Does not conform to the OTC monograph" in an unapproved-drug reason
--     isn't matched, so those stay Unapproved drug.
--   * Particle size is a specification, but other particles are Particulates.
--
-- Test it:   python -m shortagesignal.run_sql sql/root_cause_rules.sql
-- Score it:  python -m shortagesignal.tagging rules

WITH r AS (
    SELECT recall_number, lower(coalesce(reason_for_recall, '')) AS reason
    FROM recalls
)
SELECT
    recall_number,
    CASE
        WHEN (reason LIKE 'cgmp%' OR reason LIKE 'gmp%') AND (
             reason LIKE '%same condition%' OR reason LIKE '%same facility%'
          OR reason LIKE '%same equipment%' OR reason LIKE '%conditions that could%'
          OR reason LIKE '%could have been%'
          OR reason LIKE '%potential%' OR reason LIKE '%may have%'
          OR reason LIKE '%lacking%')                               THEN 'CGMP'
        WHEN reason LIKE '%non-steril%' OR reason LIKE '%non steril%'
          OR reason LIKE '%nonsteril%'                              THEN 'Microbial contamination'
        WHEN reason LIKE '%sterility%' OR reason LIKE '%abscess%'   THEN 'Sterility'
        WHEN reason LIKE '%microbial%' OR reason LIKE '%mold%' OR reason LIKE '%yeast%'
          OR reason LIKE '%bacteria%' OR reason LIKE '%fungal%'     THEN 'Microbial contamination'
        WHEN reason LIKE '%foreign tablet%' OR reason LIKE '%foreign capsule%'
          OR reason LIKE '%foreign pill%'                           THEN 'Labeling or packaging'
        WHEN reason LIKE '%impurit%' OR reason LIKE '%ndma%' OR reason LIKE '%nitrosamine%'
          OR reason LIKE '%degradation%'                            THEN 'Impurities'
        WHEN reason LIKE '%subpotent%' OR reason LIKE '%superpotent%'
          OR reason LIKE '%potency%'                                THEN 'Potency'
        WHEN reason LIKE '%particulate%'
          OR (reason LIKE '%particle%' AND reason NOT LIKE '%particle size%') THEN 'Particulates'
        WHEN reason LIKE '%foreign substance%' OR reason LIKE '%foreign material%'
          OR reason LIKE '%foreign matter%' OR reason LIKE '%chemical contamination%'
          OR reason LIKE '%cross contamination%' OR reason LIKE '%cross-contamination%'
          OR reason LIKE '%penicillin%'                             THEN 'Chemical or foreign contamination'
        WHEN reason LIKE '%dissolution%' OR reason LIKE '%specification%'
          OR reason LIKE '%discolor%' OR reason LIKE '%uniformity%'
          OR reason LIKE '%change in color%' OR reason LIKE '%color change%'
          OR reason LIKE '%atypical appearance%'
          OR reason LIKE '%stability data does not support%'
          OR reason LIKE '%stability testing fail%' OR reason LIKE '%crystalliz%'
          OR reason LIKE '%excipient%' OR reason LIKE '%product formulation%'
          OR reason LIKE '%not meet%monograph%'                     THEN 'Failed specification'
        WHEN reason LIKE '%defective%' OR reason LIKE '%leak%' OR reason LIKE '%crack%'
          OR reason LIKE '%broken%' OR reason LIKE '%container%'
          OR reason LIKE '%delivery system%'                        THEN 'Container or device defect'
        WHEN reason LIKE '%without an approved%' OR reason LIKE '%nda/anda%'
          OR reason LIKE '%unapproved%'                             THEN 'Unapproved drug'
        WHEN reason LIKE '%label%' OR reason LIKE '%mix-up%' OR reason LIKE '%mixup%'
          OR reason LIKE '%mix up%'                                 THEN 'Labeling or packaging'
        WHEN reason LIKE '%gmp%' OR reason LIKE '%processing controls%'
          OR reason LIKE '%temperature%' OR reason LIKE '%insanitary%' THEN 'CGMP'
        ELSE NULL
    END AS root_cause_rule
FROM r

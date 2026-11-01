# Data dictionary

Every file the daily pipeline keeps, what one row means, and what each column holds. The files live on the `data` branch. This page was built from them on Nov 1, 2026 by `python -m shortagesignal.dictionary`, so the columns and types are exactly what's in the data. Run it again after the pipeline changes.

To query the Parquet tables, `python -m shortagesignal.run_sql` gives each one the short name in the second column. The dashboard's Ask the data tab sees simpler versions of six of them, described in `ask.py`.

| File | Query it as | One row is | Rows |
|---|---|---|---|
| [recalls.parquet](#recallsparquet) | `recalls` | one recall number, with FDA's latest version of it | 18,047 |
| [recall_versions.parquet](#recall_versionsparquet) | `recall_versions` | one version of a recall. A new row only when FDA changes a recall's content | 18,048 |
| [shortage_snapshots.parquet](#shortage_snapshotsparquet) | `shortage_snapshots` | one listing on FDA's shortage or discontinuation list on one day | 33,341 |
| [shortages_current.parquet](#shortages_currentparquet) | `shortages_current` | one listing on FDA's lists today, with every field FDA sends | 1,607 |
| [shortage_history.parquet](#shortage_historyparquet) | `shortage_history` | one listing ever seen in the daily snapshots | 1,629 |
| [ndc.parquet](#ndcparquet) |  | one product in FDA's NDC directory | 138,032 |
| [ndc_directory.parquet](#ndc_directoryparquet) | `ndc_directory` | one package in the NDC directory, with codes in the pipeline's format | 256,613 |
| [recall_ids.parquet](#recall_idsparquet) | `recall_ids` | one NDC found for a recall. A recall with no NDC still gets one row, for its firm key | 41,481 |
| [shortage_ids.parquet](#shortage_idsparquet) | `shortage_ids` | one NDC found for a shortage listing, for every listing ever seen | 1,629 |
| [recall_drugs.parquet](#recall_drugsparquet) | `recall_drugs` | one recall number, with the drug it's about | 18,047 |
| [shortage_drugs.parquet](#shortage_drugsparquet) | `shortage_drugs` | one shortage listing, with its drug and company keys | 1,629 |
| [recall_shortage_links.parquet](#recall_shortage_linksparquet) | `links` | one recall and one shortage listing of the same drug, at the strongest level that matched | 37,797 |
| [unmatched_recalls.parquet](#unmatched_recallsparquet) | `unmatched_recalls` | one recall with no NDC and no drug name the pipeline could recognize | 3,061 |
| [recall_root_causes.parquet](#recall_root_causesparquet) | `root_causes` | one recall number, with its root cause | 18,047 |
| [claude_tags.parquet](#claude_tagsparquet) | `claude_tags` | one Claude answer for one recall's reason text. It's the cache, so nothing is asked twice | 600 |
| [tag_review.csv](#tag_reviewcsv) |  | one distinct reason text Claude tagged with low or medium confidence, for a person to check | 35 |
| [claude_drugs.parquet](#claude_drugsparquet) | `claude_drugs` | one Claude reading of one product description. It's the cache, so nothing is asked twice | 7,803 |
| [extract_review.csv](#extract_reviewcsv) |  | one recall whose Claude drug name wasn't used, with why | 4,279 |
| [recall_risk.parquet](#recall_riskparquet) | `recall_risk` | one recall number, with its risk flag | 18,047 |
| [risk_log.csv](#risk_logcsv) |  | one flag given to a newly reported recall, on the day it was given | 77 |
| [drug_makers.parquet](#drug_makersparquet) | `drug_makers` | one drug in the NDC directory, with how many companies list it | 15,493 |
| [weekly_recalls.parquet](#weekly_recallsparquet) | `weekly_recalls` | one week, Monday to Sunday, by the week FDA reported the recalls | 749 |
| [run_log.csv](#run_logcsv) |  | one pipeline run, whether it worked or not | 29 |
| [check_log.csv](#check_logcsv) |  | one data check in one run | 448 |
| [state.json](#statejson) |  | the pipeline's bookkeeping, one value per key | 1 |

## recalls.parquet

**One row is** one recall number, with FDA's latest version of it. **Made by** ingest.py, step 1. The first run loads FDA's full history from openFDA's bulk files. Every run after that pulls the last 60 days again and merges them in by recall number, so FDA's corrections land too.

| Column | Type | What it holds |
|---|---|---|
| `_content_hash` | text | A fingerprint of the recall report, leaving out openfda. It shows when FDA really changed a recall. |
| `address_1` | text | Part of the recalling firm's address. |
| `address_2` | text | Part of the recalling firm's address. |
| `center_classification_date` | text | The day FDA classified the recall, as YYYYMMDD text. |
| `city` | text | Part of the recalling firm's address. |
| `classification` | text | Class I (could cause serious harm or death), Class II (temporary or reversible harm) or Class III (unlikely to cause harm). |
| `code_info` | text | Lot numbers and expiry dates of the recalled units. |
| `country` | text | Part of the recalling firm's address. |
| `distribution_pattern` | text | Where the product was shipped, as FDA wrote it. |
| `event_id` | text | FDA's ID for the recall event. One event can cover hundreds of recall numbers, like a pharmacy recalling everything it made. |
| `initial_firm_notification` | text | How the firm told its customers, like a letter or a phone call. |
| `more_code_info` | text | The rest of code_info, when it's long. |
| `openfda` | text | FDA's annotations as JSON text, like generic names and NDCs, when FDA could match the product. Often empty for compounded or unusual products. |
| `postal_code` | text | Part of the recalling firm's address. |
| `product_description` | text | FDA's free text about the product, often with strengths, package sizes and NDCs. Matching and Claude read it. |
| `product_quantity` | text | How much was recalled, as FDA wrote it. |
| `product_type` | text | Always Drugs here. |
| `reason_for_recall` | text | FDA's free text on why. The root-cause rules and Claude read it. |
| `recall_initiation_date` | text | The day the firm started the recall, as YYYYMMDD text. The analysis uses this one for when a recall happened. |
| `recall_number` | text | FDA's ID for one recalled product, like D-0598-2026. |
| `recalling_firm` | text | The company recalling the product. |
| `report_date` | text | The week FDA published the recall in its enforcement report, as YYYYMMDD text. |
| `state` | text | Part of the recalling firm's address. |
| `status` | text | Ongoing, Completed or Terminated. |
| `termination_date` | text | The day FDA closed the recall, if it has, as YYYYMMDD text. |
| `voluntary_mandated` | text | Whether the firm recalled on its own or FDA ordered it. |
| `_pulled_at` | timestamp | When this version was pulled. |
| `_first_seen` | date | The day the pipeline first stored this recall number. |

## recall_versions.parquet

**One row is** one version of a recall. A new row only when FDA changes a recall's content. **Made by** ingest.py, step 1. Nothing is ever deleted, so this is the full edit history.

| Column | Type | What it holds |
|---|---|---|
| `_content_hash` | text | A fingerprint of the recall report, leaving out openfda. It shows when FDA really changed a recall. |
| `address_1` | text | Part of the recalling firm's address. |
| `address_2` | text | Part of the recalling firm's address. |
| `center_classification_date` | text | The day FDA classified the recall, as YYYYMMDD text. |
| `city` | text | Part of the recalling firm's address. |
| `classification` | text | Class I (could cause serious harm or death), Class II (temporary or reversible harm) or Class III (unlikely to cause harm). |
| `code_info` | text | Lot numbers and expiry dates of the recalled units. |
| `country` | text | Part of the recalling firm's address. |
| `distribution_pattern` | text | Where the product was shipped, as FDA wrote it. |
| `event_id` | text | FDA's ID for the recall event. One event can cover hundreds of recall numbers, like a pharmacy recalling everything it made. |
| `initial_firm_notification` | text | How the firm told its customers, like a letter or a phone call. |
| `more_code_info` | text | The rest of code_info, when it's long. |
| `openfda` | text | FDA's annotations as JSON text, like generic names and NDCs, when FDA could match the product. Often empty for compounded or unusual products. |
| `postal_code` | text | Part of the recalling firm's address. |
| `product_description` | text | FDA's free text about the product, often with strengths, package sizes and NDCs. Matching and Claude read it. |
| `product_quantity` | text | How much was recalled, as FDA wrote it. |
| `product_type` | text | Always Drugs here. |
| `reason_for_recall` | text | FDA's free text on why. The root-cause rules and Claude read it. |
| `recall_initiation_date` | text | The day the firm started the recall, as YYYYMMDD text. The analysis uses this one for when a recall happened. |
| `recall_number` | text | FDA's ID for one recalled product, like D-0598-2026. |
| `recalling_firm` | text | The company recalling the product. |
| `report_date` | text | The week FDA published the recall in its enforcement report, as YYYYMMDD text. |
| `state` | text | Part of the recalling firm's address. |
| `status` | text | Ongoing, Completed or Terminated. |
| `termination_date` | text | The day FDA closed the recall, if it has, as YYYYMMDD text. |
| `voluntary_mandated` | text | Whether the firm recalled on its own or FDA ordered it. |
| `_first_seen` | date | The day the pipeline first stored this recall number. |
| `_pulled_at` | timestamp | When this version was pulled. |

## shortage_snapshots.parquet

**One row is** one listing on FDA's shortage or discontinuation list on one day. **Made by** ingest.py, step 2. Every run saves the whole list as that day's snapshot. Running twice in a day replaces that day. It keeps the lean columns, so the file stays small for years.

| Column | Type | What it holds |
|---|---|---|
| `snapshot_date` | date | The day the list was pulled. |
| `shortage_key` | text | The pipeline's ID for one listing: package NDC, list type and company. Listings without an NDC get a fingerprint of the name, company and presentation instead, starting with h:. |
| `list_type` | text | shortage or discontinuation, read from the status. |
| `fda_listings` | whole number | How many times FDA listed this exact key that day. Usually 1, and duplicates are merged into one row. |
| `package_ndc` | text | The package NDC as FDA wrote it. |
| `generic_name` | text | The drug's generic name as FDA wrote it, like Dopamine Hydrochloride Injection. |
| `company_name` | text | The company with the listing. |
| `presentation` | text | The strength and package, as FDA wrote it. |
| `dosage_form` | text | Like Injection or Tablet. |
| `status` | text | Current, Resolved or To Be Discontinued. |
| `availability` | text | FDA's note on how available it is, like Limited. |
| `shortage_reason` | text | The reason the company gave FDA, like increased demand. |
| `therapeutic_category` | text | FDA's categories as JSON list text, like ["Anesthesia"]. |
| `initial_posting_date` | text | When FDA first posted the listing, as MM/DD/YYYY text. The analysis uses it as the day a shortage started. |
| `update_date` | text | When FDA last updated the listing, as MM/DD/YYYY text. |
| `update_type` | text | What the last update was, as FDA wrote it. |
| `discontinued_date` | text | When the product was discontinued, as MM/DD/YYYY text. |
| `change_date` | text | When the listing last changed status, as MM/DD/YYYY text. |
| `resolved_note` | text | FDA's note when a shortage was resolved. |

## shortages_current.parquet

**One row is** one listing on FDA's lists today, with every field FDA sends. **Made by** ingest.py, step 2. Replaced every run.

| Column | Type | What it holds |
|---|---|---|
| `snapshot_date` | date | The day the list was pulled. |
| `shortage_key` | text | The pipeline's ID for one listing: package NDC, list type and company. Listings without an NDC get a fingerprint of the name, company and presentation instead, starting with h:. |
| `availability` | text | FDA's note on how available it is, like Limited. |
| `change_date` | text | When the listing last changed status, as MM/DD/YYYY text. |
| `company_name` | text | The company with the listing. |
| `contact_info` | text | FDA's drug shortage field, kept as sent. See https://open.fda.gov/apis/drug/drugshortages/ |
| `discontinued_date` | text | When the product was discontinued, as MM/DD/YYYY text. |
| `dosage_form` | text | Like Injection or Tablet. |
| `generic_name` | text | The drug's generic name as FDA wrote it, like Dopamine Hydrochloride Injection. |
| `initial_posting_date` | text | When FDA first posted the listing, as MM/DD/YYYY text. The analysis uses it as the day a shortage started. |
| `openfda` | text | FDA's annotations as JSON text, when FDA could match the product. |
| `package_ndc` | text | The package NDC as FDA wrote it. |
| `presentation` | text | The strength and package, as FDA wrote it. |
| `related_info` | text | FDA's drug shortage field, kept as sent. See https://open.fda.gov/apis/drug/drugshortages/ |
| `related_info_link` | text | FDA's drug shortage field, kept as sent. See https://open.fda.gov/apis/drug/drugshortages/ |
| `resolved_note` | text | FDA's note when a shortage was resolved. |
| `shortage_reason` | text | The reason the company gave FDA, like increased demand. |
| `status` | text | Current, Resolved or To Be Discontinued. |
| `therapeutic_category` | text | FDA's categories as JSON list text, like ["Anesthesia"]. |
| `update_date` | text | When FDA last updated the listing, as MM/DD/YYYY text. |
| `update_type` | text | What the last update was, as FDA wrote it. |
| `list_type` | text | shortage or discontinuation, read from the status. |
| `fda_listings` | whole number | How many times FDA listed this exact key that day. Usually 1, and duplicates are merged into one row. |

## shortage_history.parquet

**One row is** one listing ever seen in the daily snapshots. **Made by** ingest.py, step 2, from shortage_snapshots.

| Column | Type | What it holds |
|---|---|---|
| `shortage_key` | text | The pipeline's ID for one listing: package NDC, list type and company. Listings without an NDC get a fingerprint of the name, company and presentation instead, starting with h:. |
| `first_seen` | date | The first day the pipeline saw the listing. |
| `last_seen` | date | The last day it saw the listing. Before the latest snapshot means it dropped off FDA's list. |
| `days_seen` | whole number | How many daily snapshots had it. |
| `latest_status` | text | Its status on the last day it was seen. |
| `generic_name` | text | Its latest generic name. |
| `company_name` | text | Its latest company. |

## ndc.parquet

**One row is** one product in FDA's NDC directory. **Made by** ingest.py, step 3, from openFDA's bulk file once a week. Only the columns matching and maker counts need are kept.

| Column | Type | What it holds |
|---|---|---|
| `product_ndc` | text | The labeler and product part of the NDC, like 0409-1105. |
| `generic_name` | text | The drug's generic name. |
| `brand_name` | text | The brand name, if it has one. |
| `labeler_name` | text | The company that lists the product, which can be a repackager. |
| `dosage_form` | text | Like INJECTION, SOLUTION. |
| `route` | text | How it's given, as JSON list text, like ["INTRAVENOUS"]. |
| `product_type` | text | Like HUMAN PRESCRIPTION DRUG. |
| `marketing_category` | text | Like ANDA, NDA or BLA. |
| `active_ingredients` | text | Names and strengths as JSON list text. |
| `packaging` | text | Each package and its 11-digit code, as JSON list text. |
| `marketing_start_date` | text | When marketing started, as YYYYMMDD text. |
| `marketing_end_date` | text | When marketing ended, if it has, as YYYYMMDD text. |
| `listing_expiration_date` | text | When the listing expires, as YYYYMMDD text. |
| `finished` | text | true for finished products, false for bulk ingredients. |

## ndc_directory.parquet

**One row is** one package in the NDC directory, with codes in the pipeline's format. **Made by** identify.py, in step 4.

| Column | Type | What it holds |
|---|---|---|
| `ndc11` | text | A package NDC in 5-4-2 form, like 00409-1105-01. Empty when only a product code was found. |
| `ndc9` | text | The product part, 5-4, like 00409-1105. Empty when no NDC was found at all. |
| `firm_key` | text | The company name cleaned up for matching (see firms.py), like HOSPIRA. |
| `labeler_name` | text | The company that lists the product, which can be a repackager. |
| `generic_name` | text | The drug's generic name. |
| `dosage_form` | text | Like INJECTION, SOLUTION. |

## recall_ids.parquet

**One row is** one NDC found for a recall. A recall with no NDC still gets one row, for its firm key. **Made by** identify.py, in step 4. Codes come from the product text, the openfda annotations, and the NDC directory for codes written without dashes.

| Column | Type | What it holds |
|---|---|---|
| `recall_number` | text | FDA's ID for one recalled product, like D-0598-2026. |
| `firm_key` | text | The company name cleaned up for matching (see firms.py), like HOSPIRA. |
| `ndc11` | text | A package NDC in 5-4-2 form, like 00409-1105-01. Empty when only a product code was found. |
| `ndc9` | text | The product part, 5-4, like 00409-1105. Empty when no NDC was found at all. |
| `source` | text | Where the code came from: text, text_product, directory_lookup, openfda, openfda_product, or none. |

## shortage_ids.parquet

**One row is** one NDC found for a shortage listing, for every listing ever seen. **Made by** identify.py, in step 4, so listings that dropped off FDA's list keep their IDs.

| Column | Type | What it holds |
|---|---|---|
| `shortage_key` | text | The pipeline's ID for one listing: package NDC, list type and company. Listings without an NDC get a fingerprint of the name, company and presentation instead, starting with h:. |
| `firm_key` | text | The company name cleaned up for matching (see firms.py), like HOSPIRA. |
| `ndc11` | text | A package NDC in 5-4-2 form, like 00409-1105-01. Empty when only a product code was found. |
| `ndc9` | text | The product part, 5-4, like 00409-1105. Empty when no NDC was found at all. |
| `source` | text | Where the code came from: text, text_product, directory_lookup, openfda, openfda_product, or none. |

## recall_drugs.parquet

**One row is** one recall number, with the drug it's about. **Made by** match.py, in steps 5 and 6.

| Column | Type | What it holds |
|---|---|---|
| `recall_number` | text | FDA's ID for one recalled product, like D-0598-2026. |
| `drug_key` | text | The drug's cleaned generic name, like heparin sodium. Empty when nothing could name it. |
| `id_source` | text | How the drug was named, first that works: ndc_directory, openfda, text_name, text_brand, or claude. Empty when nothing could. |

## shortage_drugs.parquet

**One row is** one shortage listing, with its drug and company keys. **Made by** match.py, in step 5.

| Column | Type | What it holds |
|---|---|---|
| `shortage_key` | text | The pipeline's ID for one listing: package NDC, list type and company. Listings without an NDC get a fingerprint of the name, company and presentation instead, starting with h:. |
| `drug_key` | text | The drug's cleaned generic name, written the same way as recall_drugs. |
| `firm_key` | text | The company name cleaned up for matching (see firms.py), like HOSPIRA. |
| `generic_name` | text | FDA's name for the drug. |

## recall_shortage_links.parquet

**One row is** one recall and one shortage listing of the same drug, at the strongest level that matched. **Made by** match.py, in steps 5 and 6. This is the way to connect recalls and shortages.

| Column | Type | What it holds |
|---|---|---|
| `recall_number` | text | FDA's ID for one recalled product, like D-0598-2026. |
| `shortage_key` | text | The pipeline's ID for one listing: package NDC, list type and company. Listings without an NDC get a fingerprint of the name, company and presentation instead, starting with h:. |
| `match_rank` | whole number | 1 to 4, strongest first. |
| `match_level` | text | package (the same 11-digit NDC), product (the same product code), drug_and_firm (the same drug and company) or drug (the same drug, any company, the loosest). |
| `recall_report_date` | text | The week FDA published the recall in its enforcement report, as YYYYMMDD text. |
| `recall_initiation_date` | text | The day the firm started the recall, as YYYYMMDD text. The analysis uses this one for when a recall happened. |
| `recall_class` | text | Class I (could cause serious harm or death), Class II (temporary or reversible harm) or Class III (unlikely to cause harm). |
| `shortage_generic_name` | text | The listing's generic name. |
| `shortage_status` | text | The listing's latest status. |
| `shortage_list_type` | text | shortage or discontinuation. |
| `shortage_posted` | text | When FDA first posted the listing, as MM/DD/YYYY text. The analysis uses it as the day a shortage started. |

## unmatched_recalls.parquet

**One row is** one recall with no NDC and no drug name the pipeline could recognize. **Made by** match.py. It's the work queue for Claude's drug names.

| Column | Type | What it holds |
|---|---|---|
| `recall_number` | text | FDA's ID for one recalled product, like D-0598-2026. |
| `recalling_firm` | text | The company recalling the product. |
| `product_description` | text | FDA's free text about the product, often with strengths, package sizes and NDCs. Matching and Claude read it. |
| `report_date` | text | The week FDA published the recall in its enforcement report, as YYYYMMDD text. |
| `classification` | text | Class I (could cause serious harm or death), Class II (temporary or reversible harm) or Class III (unlikely to cause harm). |

## recall_root_causes.parquet

**One row is** one recall number, with its root cause. **Made by** tagging.py, step 7. The rules in sql/root_cause_rules.sql go first, and Claude Haiku tags what they can't.

| Column | Type | What it holds |
|---|---|---|
| `recall_number` | text | FDA's ID for one recalled product, like D-0598-2026. |
| `root_cause` | text | One of the 12 categories in audit.py, like Sterility or CGMP. Empty when nothing has tagged it yet. |
| `source` | text | rule or claude. |
| `confidence` | text | Claude's own: high, medium or low. Empty for rules. |
| `why` | text | Claude's one-line reason. Empty for rules. |

## claude_tags.parquet

**One row is** one Claude answer for one recall's reason text. It's the cache, so nothing is asked twice. **Made by** tagging.py, step 7.

| Column | Type | What it holds |
|---|---|---|
| `recall_number` | text | FDA's ID for one recalled product, like D-0598-2026. |
| `reason_hash` | text | A fingerprint of the reason text. Each distinct reason is asked once. |
| `root_cause` | text | Claude's category, limited to the 12 by the tool's schema. |
| `confidence` | text | high, medium or low. |
| `why` | text | Claude's one-line reason. |
| `model` | text | The Claude model that answered. |
| `prompt_version` | text | The prompt it answered. A new prompt version asks again. |
| `tagged_at` | text | When it answered. |

## tag_review.csv

**One row is** one distinct reason text Claude tagged with low or medium confidence, for a person to check. **Made by** tagging.py, step 7. The weekly digest's Excel file has it too.

| Column | Type | What it holds |
|---|---|---|
| `reason_for_recall` | text | FDA's free text on why. The root-cause rules and Claude read it. |
| `recalls` | text | How many recalls share this reason text. |
| `root_cause` | text | Claude's category. |
| `confidence` | text | low or medium. |
| `why` | text | Claude's one-line reason. |
| `example_recall` | text | One recall number with this reason, to look it up. |

## claude_drugs.parquet

**One row is** one Claude reading of one product description. It's the cache, so nothing is asked twice. **Made by** extract.py, step 6.

| Column | Type | What it holds |
|---|---|---|
| `text_hash` | text | A fingerprint of the product description. |
| `ingredients` | text | The active ingredients by generic name, as Claude read them. |
| `drug_key` | text | Claude's drug as a cleaned name. Matching only uses it when it's a drug known to exist. |
| `strength` | text | The strength, as Claude read it. |
| `dosage_form` | text | The dosage form, as Claude read it. |
| `compounded` | text | Whether Claude thinks it was compounded. |
| `confidence` | text | high, medium or low. |
| `model` | text | The Claude model that answered. |
| `prompt_version` | text | The prompt it answered. A new prompt version asks again. |
| `extracted_at` | text | When it answered. |

## extract_review.csv

**One row is** one recall whose Claude drug name wasn't used, with why. **Made by** extract.py, step 6. The weekly digest's Excel file has it too.

| Column | Type | What it holds |
|---|---|---|
| `recall_number` | text | FDA's ID for one recalled product, like D-0598-2026. |
| `recalling_firm` | text | The company recalling the product. |
| `product_description` | text | FDA's free text about the product, often with strengths, package sizes and NDCs. Matching and Claude read it. |
| `ingredients` | text | The active ingredients, as Claude read them. |
| `confidence` | text | high, medium or low. |
| `problem` | text | Why it wasn't used, like low confidence or a drug that isn't known to exist. |

## recall_risk.parquet

**One row is** one recall number, with its risk flag. **Made by** risk.py, step 8. See risk.py for why the flag is built the way it is.

| Column | Type | What it holds |
|---|---|---|
| `recall_number` | text | FDA's ID for one recalled product, like D-0598-2026. |
| `event_id` | text | FDA's ID for the recall event. One event can cover hundreds of recall numbers, like a pharmacy recalling everything it made. |
| `report_date` | text | The week FDA published the recall in its enforcement report, as YYYYMMDD text. |
| `recall_class` | text | Class I (could cause serious harm or death), Class II (temporary or reversible harm) or Class III (unlikely to cause harm). |
| `root_cause` | text | The recall's root cause, from root_causes. |
| `drug_key` | text | The recall's drug, from recall_drugs. |
| `labelers` | whole number | How many companies list this drug in the NDC directory, leaving out declared repackagers. Shown as a fact, not part of the flag. |
| `injectable` | true/false | Whether the product is an injectable, read from the product text. Eye drops in vials don't count. |
| `in_shortage` | true/false | Whether the drug is on FDA's shortage list right now, at any match level. |
| `points` | whole number | 0 to 3: 2 when in_shortage, 1 when injectable. |
| `flag` | text | high (2 points or more), watch (1, an injectable) or low (0). |
| `reasons` | text | The signs behind the points, like on the shortage list now, injectable. |

## risk_log.csv

**One row is** one flag given to a newly reported recall, on the day it was given. **Made by** risk.py, step 8. Each recall is logged once, within 30 days of its report. Checking these flags against shortages that come later is the honest test of the flag. Flags before 2026-10-26 used the old points.

| Column | Type | What it holds |
|---|---|---|
| `recall_number` | text | FDA's ID for one recalled product, like D-0598-2026. |
| `report_date` | text | The week FDA published the recall in its enforcement report, as YYYYMMDD text. |
| `flagged_on` | text | The day the flag was given. |
| `flag` | text | high, watch or low. |
| `points` | text | The points behind it. |
| `reasons` | text | The signs behind the points. |

## drug_makers.parquet

**One row is** one drug in the NDC directory, with how many companies list it. **Made by** risk.py, step 8.

| Column | Type | What it holds |
|---|---|---|
| `drug_key` | text | The drug's cleaned generic name. |
| `labelers` | whole number | How many companies list it, leaving out declared repackagers. |

## weekly_recalls.parquet

**One row is** one week, Monday to Sunday, by the week FDA reported the recalls. **Made by** risk.py, step 8, from sql/weekly_recall_events.sql. Weeks with no recalls are there as zeros, and the current week is left out until it's over.

| Column | Type | What it holds |
|---|---|---|
| `week` | date | The Monday the week starts on. |
| `events` | whole number | Recall events reported that week. The control chart counts these. |
| `recalls` | whole number | Recall numbers reported that week. |
| `center` | number | The average weekly events over the baseline: the 2 years before the latest 13 weeks. |
| `ucl` | number | The upper control limit. A week above it is unusually busy. |
| `lcl` | number | The lower control limit, never below 0. |
| `signal` | text | above or below when the week falls outside the limits. Empty otherwise. |

## run_log.csv

**One row is** one pipeline run, whether it worked or not. **Made by** ingest.py, at the end of every run. The weekly digest and the dashboard read it.

| Column | Type | What it holds |
|---|---|---|
| `run_at_utc` | text | When the run started, in UTC. |
| `status` | text | success or failed. |
| `seconds` | text | How long it took. |
| `recalls_mode` | text | Full history on the first run, then the last 60 days. |
| `recalls_pulled` | text | Recall rows pulled this run. |
| `recalls_new` | text | Recall numbers never stored before. |
| `recalls_changed` | text | Stored recalls FDA changed since the last version. |
| `recalls_total` | text | Recall numbers stored after the run. |
| `shortage_rows` | text | Listings in today's snapshot. |
| `shortages_new` | text | Listings that weren't in the last snapshot. |
| `shortages_dropped` | text | Listings that dropped off since the last snapshot. |
| `shortage_status_changes` | text | Listings whose status changed since the last snapshot. |
| `duplicate_listings_merged` | text | Rows FDA listed twice under the same key. |
| `ndc_refreshed` | text | yes when the NDC directory was refreshed this run. |
| `recalls_with_ndc_pct` | text | Percent of recalls with at least one NDC found. |
| `shortages_with_ndc_pct` | text | Percent of shortage listings with an NDC. |
| `recalls_identified_pct` | text | Percent of recalls with an NDC or a drug name. |
| `recalls_unmatched` | text | Recalls with neither, the unmatched_recalls table. |
| `recalls_linked` | text | Recalls linked to at least one shortage listing. |
| `shortages_linked` | text | Shortage listings linked to at least one recall. |
| `recalls_named_pct_before` | text | Percent of recalls with a drug name before Claude's names. |
| `recalls_named_pct` | text | Percent with a drug name after Claude's names. |
| `recalls_named_by_claude` | text | Recalls named only by Claude. |
| `extract_calls` | text | Claude calls for drug names this run. |
| `extract_cost_usd` | text | What they cost, in dollars. |
| `extract_waiting` | text | Recalls still waiting for Claude to name the drug. |
| `recalls_tagged_pct` | text | Percent of recalls with a root cause. |
| `tag_backlog` | text | Recalls still waiting for a root cause. |
| `claude_calls` | text | Claude calls for root causes this run. |
| `claude_cost_usd` | text | What they cost, in dollars. |
| `risk_high_30d` | text | Recalls reported in the last 30 days flagged high. |
| `risk_watch_30d` | text | Recalls reported in the last 30 days flagged watch. |
| `weekly_events_last` | text | Recall events in the latest complete week. |
| `weekly_signal` | text | above or below when that week is outside the control limits. |
| `checks_warned` | text | Data checks that warned. |
| `checks_failed` | text | Data checks that failed. Any failure stops the run before saving. |
| `error` | text | What went wrong, when the run failed. |

## check_log.csv

**One row is** one data check in one run. **Made by** checks.py, at the end of every run. The spike and went-quiet rules compare against this history. The runbook says what each check means.

| Column | Type | What it holds |
|---|---|---|
| `run_at_utc` | text | When the run started, in UTC. |
| `check` | text | The check's name. |
| `severity` | text | error (stops the run) or warning (only reported). |
| `value` | text | The number the check looked at. |
| `status` | text | pass, warn or fail. |
| `detail` | text | What was wrong, when something was. |

## state.json

**One row is** the pipeline's bookkeeping, one value per key. **Made by** ingest.py.

| Column | Type | What it holds |
|---|---|---|
| `ndc_refreshed` | text | The day the NDC directory was last refreshed. It's refreshed when this is 7 days old. |
| `last_run` | text | The time of the last successful run, in UTC. |

# Coauthored: contract between coauthored-submit and coauthored-browse

coauthored-browse (fork of arXiv's arxiv-browse) serves published papers and reads only what
is described here. coauthored-submit owns accounts, submissions, screening and the daily
announce. Both use **arxiv-base** at commit `8841f53ba87e1cc4694a7d9e35d6fa5dd0bb240b`
(`git+https://github.com/arXiv/arxiv-base.git@8841f53ba87e1cc4694a7d9e35d6fa5dd0bb240b`), for
the classic schema models (`arxiv.db.models`), identifiers (`arxiv.identifier.Identifier`),
storage paths (`arxiv.files.key_patterns`), object stores (`arxiv.files`) and the taxonomy
(`arxiv.taxonomy.definitions`).

## Database (one MySQL 8 database in production; SQLite in tests)

### arXiv classic tables written at announce (arxiv-base models)
For each announced version of paper `ID` (new style `YYMM.NNNNN`, five digits; `YYMM` is the
announce date in UTC; numbers run from 00001 each month):

- `arXiv_documents` (`Document`), once per paper: `paper_id=ID`, `title`, `authors` (display
  string, below), `submitter_email`, `submitter_id=NULL`, `dated` (unix time of the first
  version's submission), `primary_subject_class` (primary category, e.g. `cs.GT`), `created`.
- `arXiv_metadata` (`Metadata`), one row per version: `document_id`, `paper_id=ID`,
  `version=N`, `created` (submission time), `updated`, `submitter_id=NULL`, `submitter_name`,
  `submitter_email`, `source_size` (PDF bytes), `source_format='pdf'`, `source_flags=''`,
  `title`, `authors`, `abs_categories` (space-separated, primary first, e.g.
  `cs.GT math.CO`), `comments` (or NULL), `license` (a licence URI below), `abstract`,
  `is_current=1` for the new version and `0` for all earlier ones, `is_withdrawn=0`,
  `modtime` (unix time), `published_at` (announce time). Leave `doi`, `journal_ref`,
  `report_num`, `msc_class`, `acm_class`, `proxy` NULL.
- `arXiv_document_category` (`DocumentCategory`): one row per category of the latest
  version, `is_primary` 1 for the primary.
- `arXiv_in_category` (`t_arXiv_in_category`): one row per category: `archive` and
  `subject_class` split from the category id (`cs.GT` -> `cs`, `GT`; a category with no dot,
  e.g. `hep-th` -> `hep-th`, `''`), `is_primary`.
- `arXiv_updates` (`Updates`): one row per announced version and category: `document_id`,
  `version`, `date` (announce date), `action` (`new` for v1, `replace` after), `archive`,
  `category`.
- Seeds that foreign keys need (insert if missing): `arXiv_licenses` rows for the licence
  URIs below; `arXiv_archives`, `arXiv_categories`, `arXiv_category_def` rows for every
  category offered (generated from `arxiv.taxonomy.definitions`).

`authors` display string: the authors' display names joined with ", " (arXiv's parser
accepts this). AI authors appear under their display name, e.g. `Claude`.

Licence URIs offered (values of `Metadata.license`):
- `http://creativecommons.org/licenses/by/4.0/` (default)
- `http://creativecommons.org/licenses/by-sa/4.0/`
- `http://creativecommons.org/publicdomain/zero/1.0/`
- `http://arxiv.org/licenses/nonexclusive-distrib/1.0/` is NOT offered (it grants rights
  to arXiv). Coauthored's own non-exclusive licence is
  `https://aicoauthored.dev/licenses/nonexclusive-distrib/1.0/` (configurable host).

### Coauthored tables (owned and created by coauthored-submit)
`coauthored_contributors`: the published author list, read by browse.

| column | type | notes |
|---|---|---|
| `paper_id` | varchar(20) | e.g. `2611.00001` |
| `version` | int | |
| `position` | int | 1-based author order |
| `display_name` | varchar(255) | |
| `kind` | varchar(8) | `human` or `ai` |
| `orcid` | varchar(19) NULL | humans only |
| `ai_system` | varchar(128) NULL | AI only, e.g. `Claude` |
| `ai_version` | varchar(128) NULL | AI only, e.g. `Opus 5.5 (claude-opus-5-5)` |
| `ai_provider` | varchar(128) NULL | AI only, e.g. `Anthropic` |
| `contribution` | text | required for every author |
| `is_responsible` | bool | at least one human per version is true |

Primary key `(paper_id, version, position)`. Browse looks rows up by `paper_id` and
`version` and shows them; if there are none it falls back to the classic `authors` string.

Other `coauthored_*` tables (accounts, submissions, submission contributors, moderation log)
are private to coauthored-submit.

## Files (one object store; local directory in dev/tests, `gs://bucket` in production)
Browse reads PDFs with `DISSEMINATION_STORAGE_PREFIX` = `SOURCE_STORAGE_PREFIX` = the store
root:
- current version: `arxiv.files.key_patterns.current_pdf_path(Identifier(ID))`
  -> `ftp/arxiv/papers/YYMM/ID.pdf`
- earlier versions: `previous_pdf_path(Identifier(f"{ID}v{N}"))`
  -> `orig/arxiv/papers/YYMM/IDvN.pdf`

At a replacement, announce moves the old current PDF to its `orig/` path and writes the new
one at the `ftp/` path. Staged uploads live under `staging/` and are never served.

The store root must also contain `reasons.json`, a JSON object mapping paper ids to the reason
a version cannot be served (browse fails to serve papers without it). Coauthored writes `{}`
there at `init-db` and adds entries only if a version must be suppressed.

## Browse configuration in production
`DOCUMENT_ABSTRACT_SERVICE=browse.services.documents.db_docs`,
`DOCUMENT_LISTING_SERVICE=browse.services.listing.db_listing`, `CLASSIC_DB_URI`,
`DISSEMINATION_STORAGE_PREFIX` and `SOURCE_STORAGE_PREFIX` = the bucket, `BASE_SERVER` = the
public host.

## Identifiers shown to people
Always `coauthored:ID` (and `coauthored:IDvN`), never `arXiv:ID`.

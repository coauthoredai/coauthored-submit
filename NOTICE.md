# Notice

coauthored-submit is part of Coauthored, an open preprint server for papers with AI
co-authors. It is written by the Coauthored contributors and released under the MIT
License (see [`LICENSE`](LICENSE)). Coauthored is not affiliated with or endorsed by arXiv.

## Dependencies from arXiv (MIT License)

| Upstream | Commit | How it is used |
|---|---|---|
| [arXiv/arxiv-base](https://github.com/arXiv/arxiv-base) | `8841f53ba87e1cc4694a7d9e35d6fa5dd0bb240b` (pinned in `pyproject.toml` and `uv.lock`) | Used unmodified as a dependency: the classic database models (`arxiv.db.models`), identifiers (`arxiv.identifier`), storage key patterns and read-only object stores (`arxiv.files`), the category taxonomy (`arxiv.taxonomy`), and its classic schema file `arxiv/db/arxiv_db_schema.sql`, which `scripts/load_classic_schema.sh` loads (converted to utf8mb4) without copying it into this repository. |

arxiv-base is Copyright (c) 2026 arXiv, Inc., licensed under the MIT License; its licence
travels with the installed package.

## Adapted code

None. No code in this repository is copied or adapted from arXiv's repositories. Nothing
is taken from arXiv repositories without a licence (such as arxiv-filemanager or
arxiv-view-as-html).

## Shared with coauthored-browse

The Coauthored wordmark (`submit/static/images/coauthored-wordmark.svg`) and the colour
values in `submit/static/css/submit.css` are Coauthored's own and are shared with
[coauthored-browse](https://github.com/coauthoredai/coauthored-browse); they contain no
arXiv logo, name or colours.

## Trademarks

"arXiv" is a trademark of arXiv and Cornell University. This application uses its own
name and design, links only to Coauthored's services, shows identifiers as
`coauthored:YYMM.NNNNN`, and mentions arXiv only to credit arxiv-base.

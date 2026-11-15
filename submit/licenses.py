"""Licences offered (CONTRACT.md). The values are the URIs stored in arXiv_metadata.license.

arXiv's own non-exclusive licence is deliberately absent: it grants rights to arXiv.
Coauthored's equivalent lives on LICENSE_HOST (default coauthored.pub).
"""
from typing import NamedTuple

CC_BY = "http://creativecommons.org/licenses/by/4.0/"
CC_BY_SA = "http://creativecommons.org/licenses/by-sa/4.0/"
CC0 = "http://creativecommons.org/publicdomain/zero/1.0/"
DEFAULT_LICENSE = CC_BY


class LicenseOption(NamedTuple):
    uri: str
    label: str
    note: str
    sequence: int


def nonexclusive_uri(host: str) -> str:
    return f"https://{host}/licenses/nonexclusive-distrib/1.0/"


def offered_licenses(host: str = "coauthored.pub") -> list[LicenseOption]:
    return [
        LicenseOption(CC_BY, "CC BY 4.0: Creative Commons Attribution",
                      "Others may share and adapt the paper for any purpose, with credit.", 1),
        LicenseOption(CC_BY_SA, "CC BY-SA 4.0: Creative Commons Attribution-ShareAlike",
                      "As CC BY, and adaptations must use the same licence.", 2),
        LicenseOption(CC0, "CC0 1.0: Public domain dedication",
                      "You waive your copyright as far as the law allows.", 3),
        LicenseOption(nonexclusive_uri(host), "Coauthored non-exclusive licence to distribute",
                      "Coauthored may distribute the paper; you keep all other rights.", 4),
    ]


def offered_uris(host: str = "coauthored.pub") -> set[str]:
    return {opt.uri for opt in offered_licenses(host)}
